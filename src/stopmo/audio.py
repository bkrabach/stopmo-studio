"""Local speech and sample-accurate mixing. This host module never imports bpy."""
from __future__ import annotations

from functools import lru_cache
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import wave

import numpy as np

SAMPLE_RATE = 48000
HANDLING_VERSION = "takes-hp70-compressor-v3"
DEFAULT_MIX = {
    "voice_lufs": -17, "voice_peak_db": -2.5,
    "duck": {"lead": 0.3, "ramp": 0.25, "hold": 0.15, "release": 0.6,
             "merge": 0.7, "min_db": -3.5, "max_db": -14},
    "voice_over_music_db": 12, "sfx_under_voice": 0.65, "music_gap_db": -24,
    "target_lufs": -15, "true_peak_db": -1.5,
}
_ROOT = Path(__file__).resolve().parents[2]
_VENDOR = _ROOT / "vendor"
_KOKORO_VOICES = {"narrator": "bm_george", "man": "bm_daniel", "woman": "bf_emma",
                  "old_man": "bm_fable", "child": "bf_isabella", "daniel": "bm_daniel"}


def _run(args: list[str], *, timeout: float = 300) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(args, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Could not run {args[0]}: {exc}") from exc
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed: {result.stderr.decode(errors='replace')[-2500:]}")
    return result


@lru_cache(maxsize=1)
def _ffmpeg() -> str:
    candidates = [os.environ.get("STOPMO_FFMPEG"), shutil.which("ffmpeg")]
    if importlib.util.find_spec("imageio_ffmpeg") is not None:
        import imageio_ffmpeg
        candidates.append(imageio_ffmpeg.get_ffmpeg_exe())
    for binary in dict.fromkeys(p for p in candidates if p):
        try:
            _run([binary, "-version"], timeout=10)
            return binary
        except RuntimeError:
            continue
    raise RuntimeError("No working FFmpeg. Install the base checkout dependencies "
                       "(uv pip install -e .) or set STOPMO_FFMPEG to a compatible executable.")


def _write_wav(path: Path, samples: np.ndarray, *, sample_rate: int = SAMPLE_RATE) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    samples = np.asarray(samples, dtype=np.float64)
    if samples.ndim != 1 or not np.isfinite(samples).all():
        raise ValueError("Audio must be a finite one-dimensional array")
    pcm = np.rint(np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())


def _read_wav(path: Path) -> np.ndarray:
    """Load arbitrary FFmpeg-readable audio as 48 kHz float mono; fast path for our WAVs."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        with wave.open(str(path), "rb") as wav:
            if wav.getnchannels() == 1 and wav.getsampwidth() == 2 and wav.getframerate() == SAMPLE_RATE:
                return np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(np.float64) / 32768
    except (wave.Error, EOFError):
        pass
    result = _run([_ffmpeg(), "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1",
                   "-ar", str(SAMPLE_RATE), "pipe:1"])
    return np.frombuffer(result.stdout, dtype="<f4").astype(np.float64)


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as wav:
        return wav.getnframes() / wav.getframerate()


LINE_RMS_DB = -23.0
ACTING_PYTHON = _VENDOR / "acting" / "venv" / "bin" / "python"
ENGINES = ("dramabox", "voxcpm", "breeze", "higgs")  # see src/stopmo_voice/engines.py


def kokoro_available() -> bool:
    """Whether explicitly chosen Kokoro speech/reference synthesis is present."""
    return (importlib.util.find_spec("kokoro_onnx") is not None
            and (_VENDOR / "kokoro/kokoro-v1.0.onnx").is_file()
            and (_VENDOR / "kokoro/voices-v1.0.bin").is_file())


def acting_available() -> bool:
    """Whether the acting-voice environment (tools/install_voice_tools.sh) is installed."""
    return ACTING_PYTHON.is_file() and os.access(ACTING_PYTHON, os.X_OK)


@lru_cache(maxsize=1)
def _kokoro():
    try:
        from kokoro_onnx import Kokoro
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.intra_op_num_threads = 4
        options.inter_op_num_threads = 1
        session = ort.InferenceSession(str(_VENDOR / "kokoro/kokoro-v1.0.onnx"),
                                       sess_options=options, providers=["CPUExecutionProvider"])
        return Kokoro.from_session(session, str(_VENDOR / "kokoro/voices-v1.0.bin"))
    except Exception as exc:
        raise RuntimeError(f"Kokoro could not load: {exc}. On macOS, run "
                           "tools/install_voice_tools.sh --kokoro; elsewhere see the manual setup guide.") from exc


def list_voices() -> list[str]:
    """Kokoro voice names (bm_george, bf_emma, ...)."""
    if not kokoro_available():
        raise RuntimeError("Kokoro is not installed. On macOS, run tools/install_voice_tools.sh --kokoro; "
                           "elsewhere see the manual setup guide.")
    with np.load(_VENDOR / "kokoro/voices-v1.0.bin") as voices:  # no need to load the network to list names
        return sorted(voices.files)


def _atempo(rate: float) -> list[str]:
    filters = []
    while rate < 0.5:
        filters.append("atempo=0.5")
        rate /= 0.5
    while rate > 2:
        filters.append("atempo=2")
        rate /= 2
    return filters + [f"atempo={rate:.10f}"]


def _trim(samples: np.ndarray) -> np.ndarray:
    # Sample threshold + 40 ms handles softly voiced onsets without half-second padding.
    active = np.flatnonzero(np.abs(samples) > 0.001)
    if not len(active):
        return samples[:min(len(samples), int(0.06 * SAMPLE_RATE))]
    pad = int(0.04 * SAMPLE_RATE)
    return samples[max(0, active[0] - pad):min(len(samples), active[-1] + pad + 1)]


def _check_rate_pitch(rate: float, pitch: float) -> None:
    if not math.isfinite(rate) or not 0.05 <= rate <= 8:
        raise ValueError("rate must be finite, between 0.05 and 8")
    if not math.isfinite(pitch) or abs(pitch) > 24:
        raise ValueError("pitch must be finite and within +/-24 semitones")


def finish_take(raw: Path, out_wav: Path, *, rate: float = 1.0, pitch: float = 0.0) -> float:
    """Turn any recorded take into a film line: 48 kHz mono, silence trimmed at both ends, optional
    tempo (`rate`) and pitch (semitones, length kept), 70 Hz high-pass, 3:1 compression, 4 ms fades.
    Returns the duration in seconds."""
    _check_rate_pitch(rate, pitch)
    out_wav = Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".take-", dir=out_wav.parent) as temp:
        converted = Path(temp) / "converted.wav"
        command = [_ffmpeg(), "-v", "error", "-y", "-i", str(raw)]
        if rate != 1:
            command += ["-af", ",".join(_atempo(rate))]
        _run(command + ["-ar", str(SAMPLE_RATE), "-ac", "1", "-c:a", "pcm_s16le", str(converted)])
        samples = _trim(_read_wav(converted))
        if pitch:
            source, shifted = Path(temp) / "source.wav", Path(temp) / "pitch.wav"
            _write_wav(source, samples)
            factor = 2 ** (pitch / 12)
            filters = [f"asetrate={SAMPLE_RATE * factor:.8f}", f"aresample={SAMPLE_RATE}"] + _atempo(1 / factor)
            _run([_ffmpeg(), "-v", "error", "-y", "-i", str(source), "-af", ",".join(filters),
                  "-c:a", "pcm_s16le", str(shifted)])
            shifted_samples = _read_wav(shifted)
            samples = np.pad(shifted_samples, (0, max(0, len(samples) - len(shifted_samples))))[:len(samples)]
        samples = _filter_samples(samples, "highpass=f=70,"
                                  "acompressor=threshold=-24dB:ratio=3:attack=5:release=120")
        # every line to the same speech level, whichever engine spoke it (the mix sets the final level)
        active = samples[np.abs(samples) > 0.003]
        if len(active):
            gain = 10 ** (LINE_RMS_DB / 20) / math.sqrt(float(np.mean(active ** 2)))
            samples = samples * min(gain, 0.9 / float(np.max(np.abs(samples))))
        edge = min(len(samples) // 2, int(0.004 * SAMPLE_RATE))
        if edge:
            ramp = np.linspace(0, 1, edge)
            samples[:edge] *= ramp
            samples[-edge:] *= ramp[::-1]
        _write_wav(out_wav, samples)
    return wav_duration(out_wav)


def synthesize(text: str, out_wav: Path, *, voice: str = "bm_george", rate: float = 1.0, pitch: float = 0.0) -> float:
    """Kokoro text-to-speech -> 48 kHz mono wav; returns seconds. `rate` is Kokoro's own speed.

    Kokoro reads a line evenly and takes no direction. It is used to make a character's reference
    clip (the voice the acting engines copy) and as the stand-in voice when they are not installed.
    """
    if not text.strip():
        raise ValueError("Speech text must not be empty")
    _check_rate_pitch(rate, pitch)
    chosen = _KOKORO_VOICES.get(voice.lower(), voice)
    if chosen not in list_voices():
        raise ValueError(f"Unknown Kokoro voice {voice!r}; see audio.list_voices()")
    try:
        samples, sr = _kokoro().create(text, voice=chosen, speed=rate,
                                       lang="en-gb" if chosen.startswith("b") else "en-us")
    except Exception as exc:
        raise RuntimeError(f"Kokoro synthesis failed: {exc}") from exc
    out_wav = Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".tts-", dir=out_wav.parent) as temp:
        raw = Path(temp) / "speech.wav"
        _write_wav(raw, samples, sample_rate=sr)
        return finish_take(raw, out_wav, pitch=pitch)


def expected_seconds(text: str, pace: str = "medium", event: str | None = None) -> float:
    """Roughly how long a line takes when acted. It is the time budget given to engines that fill a
    set duration, and the yardstick for rejecting takes that ran away (a long silence, extra words)."""
    seconds = len(text) / 15.0 + 0.25 * sum(text.count(ch) for ch in ".!?") + 0.5
    seconds *= {"slow": 1.2, "medium": 1.0, "fast": 0.9}.get(pace, 1.0)
    seconds += 0.5 * text.count("...") + (0.8 if event else 0.0)
    return round(max(seconds, 1.8), 1)


def act(engine: str, jobs: list[dict], workdir: Path) -> dict[str, dict]:
    """Record a batch of takes with one acting engine (the model is loaded once for the batch).

    jobs: [{"out": raw wav path, "line": {...}, "character": {...}, "seed": int}]; the line and
    character fields are described in src/stopmo_voice/engines.py. Returns {out path: {seconds,
    generate_seconds}} for the takes that were written; a missing entry means that take failed.
    """
    if engine not in ENGINES:
        raise ValueError(f"unknown acting engine {engine!r}; use one of {', '.join(ENGINES)}")
    if not acting_available():
        raise RuntimeError("Acting voices are not installed. On Apple Silicon, review model licenses, then run "
                           "tools/install_voice_tools.sh --acting --accept-model-licenses. "
                           "No substitute voice was generated.")
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    batch = workdir / f"jobs_{engine}_{os.getpid()}_{len(jobs)}.json"
    batch.write_text(json.dumps({"engine": engine, "jobs": jobs}))
    env = {**os.environ, "PYTHONPATH": str(_ROOT / "src")}
    try:
        result = subprocess.run([str(ACTING_PYTHON), "-m", "stopmo_voice.speak", str(batch)], env=env,
                                capture_output=True, timeout=600 + 400 * len(jobs))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Acting engine {engine!r} could not run: {exc}") from exc
    finally:
        batch.unlink(missing_ok=True)
    done = {}
    for row in result.stdout.decode(errors="replace").splitlines():
        if row.startswith('{"out"'):
            info = json.loads(row)
            done[info.pop("out")] = info
    if result.returncode and not done:
        raise RuntimeError(f"Acting engine {engine!r} failed: {result.stderr.decode(errors='replace')[-1500:]}")
    return done


def _mix_samples(tracks: list[dict], duration: float | None = None) -> np.ndarray:
    """Sum tracks in float; envelope times are relative to each track, gains multiply."""
    if duration is not None and (not math.isfinite(duration) or duration < 0):
        raise ValueError("duration must be finite and nonnegative")
    loaded = []
    end = 0
    for track in tracks:
        start, gain = float(track.get("start", 0)), float(track.get("gain", 1))
        fade_in, fade_out = float(track.get("fade_in", 0)), float(track.get("fade_out", 0))
        if not all(math.isfinite(v) for v in (start, gain, fade_in, fade_out)) or min(start, fade_in, fade_out) < 0:
            raise ValueError("Track start/fades must be finite and nonnegative; gain must be finite")
        samples = _read_wav(Path(track["path"])) * gain
        if track.get("envelope"):
            points = np.asarray(track["envelope"], dtype=float)
            if (points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all()
                    or np.any(points < 0) or np.any(np.diff(points[:, 0]) <= 0)):
                raise ValueError("Envelope needs finite nonnegative (seconds, gain) points in increasing time order")
            samples *= np.interp(np.arange(len(samples)) / SAMPLE_RATE, points[:, 0], points[:, 1])
        for seconds, reverse in ((fade_in, False), (fade_out, True)):
            count = min(len(samples), round(seconds * SAMPLE_RATE))
            if count:
                ramp = np.linspace(0, 1, count)
                if reverse:
                    samples[-count:] *= ramp[::-1]
                else:
                    samples[:count] *= ramp
        offset = round(start * SAMPLE_RATE)
        loaded.append((offset, samples))
        end = max(end, offset + len(samples))
    result = np.zeros(round(duration * SAMPLE_RATE) if duration is not None else end, dtype=np.float64)
    for offset, samples in loaded:
        count = min(len(samples), len(result) - offset)
        if count > 0:
            result[offset:offset + count] += samples[:count]
    return result


def mix(tracks: list[dict], out_wav: Path, *, duration: float | None = None) -> Path:
    """Mix WAVs with relative-time linear envelopes, gains/fades and a soft peak limiter."""
    result = _mix_samples(tracks, duration)
    if len(result) and np.max(np.abs(result)) > 0.98:
        result = 0.98 * np.tanh(result / 0.98)
    _write_wav(Path(out_wav), result)
    return Path(out_wav)


def _filter_samples(samples: np.ndarray, filters: str) -> np.ndarray:
    """Apply an FFmpeg audio filter to 48 kHz float samples without intermediate clipping."""
    if not len(samples):
        return samples.copy()
    with tempfile.TemporaryDirectory(prefix="stopmo-filter-") as temp:
        source = Path(temp) / "source.f32"
        np.asarray(samples, dtype="<f4").tofile(source)
        result = _run([_ffmpeg(), "-v", "error", "-f", "f32le", "-ar", str(SAMPLE_RATE),
                       "-ac", "1", "-i", str(source), "-af", filters,
                       "-ar", str(SAMPLE_RATE), "-ac", "1", "-f", "f32le", "pipe:1"])
    # Look-ahead filters must not move sync or length.
    output = np.frombuffer(result.stdout, dtype="<f4").astype(float)
    return np.pad(output, (0, max(0, len(samples) - len(output))))[:len(samples)]


def measure_loudness(wav: Path) -> dict:
    """Measure integrated LUFS and oversampled true peak using FFmpeg EBU R128."""
    result = _run([_ffmpeg(), "-hide_banner", "-nostats", "-i", str(wav),
                   "-af", "ebur128=peak=true", "-f", "null", "-"])
    summary = result.stderr.decode(errors="replace").rsplit("Summary:", 1)[-1]
    integrated = re.search(r"I:\s+([-\w.]+)\s+LUFS", summary)
    peak = re.search(r"Peak:\s+([-\w.]+)\s+dBFS", summary)
    if not integrated or not peak:
        raise RuntimeError("FFmpeg did not return EBU R128 loudness. Install imageio-ffmpeg or set STOPMO_FFMPEG.")
    def number(value: str) -> float | None:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    return {"integrated_lufs": number(integrated[1]), "true_peak_db": number(peak[1])}


def rms_db(samples: np.ndarray) -> float:
    """RMS in dBFS, with a finite -120 dB floor for silent/empty measurements."""
    return max(-120.0, 20 * math.log10(max(float(np.sqrt(np.mean(samples ** 2))), 1e-6))) if len(samples) else -120.0


def duck_envelope(spans: list[tuple[float, float]], duration: float, depth_db: float,
                  settings: dict | None = None) -> list[tuple[float, float]]:
    """Linear music gain knots; merge short speech gaps and safely intersect overlapping ramps.

    Lead/ramp/hold/release/merge are seconds. Depth is a negative dB attenuation.
    Fades are separate track parameters, so a fade and a duck multiply exactly.
    """
    cfg = {**DEFAULT_MIX["duck"], **(settings or {})}
    if duration <= 0 or not math.isfinite(duration) or not math.isfinite(depth_db) or depth_db > 0:
        raise ValueError("Duck duration must be positive and depth finite and nonpositive")
    if any(not math.isfinite(cfg[k]) or cfg[k] < 0 for k in ("lead", "ramp", "hold", "release", "merge")):
        raise ValueError("Duck times must be finite and nonnegative")
    stretches: list[list[float]] = []
    for start, end in sorted(spans):
        if not (math.isfinite(start) and math.isfinite(end) and 0 <= start <= end <= duration + 1e-6):
            raise ValueError("Speech spans must be finite, ordered, and inside the mix")
        if stretches and start - stretches[-1][1] < cfg["merge"]:
            stretches[-1][1] = max(end, stretches[-1][1])
        else:
            stretches.append([start, end])
    low = 10 ** (depth_db / 20)
    lanes = []
    for start, end in stretches:
        down = max(0.0, start - cfg["lead"])
        bottom = min(start, down + cfg["ramp"])
        # Starting at t=0 already under speech must start down, not ramp over its onset.
        points = {0.0: 1.0, duration: 1.0, down: 1.0, bottom: low,
                  min(duration, end + cfg["hold"]): low,
                  min(duration, end + cfg["hold"] + cfg["release"]): 1.0}
        # If the held section reaches the end, do not overwrite it with full level.
        if end + cfg["hold"] >= duration:
            points[duration] = low
        elif end + cfg["hold"] + cfg["release"] > duration and cfg["release"]:
            points[duration] = low + (1 - low) * (duration - end - cfg["hold"]) / cfg["release"]
        lanes.append(sorted(points.items()))
    times = sorted({0.0, duration} | {t for lane in lanes for t, _ in lane})
    # The lower of two ramps can cross between knots: retain that crossing.
    crossings = []
    for left, right in zip(times, times[1:]):
        for i, first in enumerate(lanes):
            a = np.interp([left, right], *np.asarray(first).T)
            for second in lanes[i + 1:]:
                delta = a - np.interp([left, right], *np.asarray(second).T)
                if delta[0] * delta[1] < 0:
                    crossings.append(left + (right - left) * delta[0] / (delta[0] - delta[1]))
    return [(t, min([1.0] + [float(np.interp(t, *np.asarray(lane).T)) for lane in lanes]))
            for t in sorted(set(times + crossings))]


def _limit(samples: np.ndarray, gain_db: float, ceiling_db: float, *, true_peak: bool = False) -> np.ndarray:
    """Gain then look-ahead limit without auto makeup; optionally work at 4x sample rate."""
    ceiling = 10 ** (ceiling_db / 20)
    filters = (["aresample=192000"] if true_peak else []) + [
        f"volume={gain_db:.8f}dB",
        f"alimiter=limit={ceiling:.8f}:attack=3:release=80:level=disabled:latency=1",
    ] + (["aresample=48000"] if true_peak else [])
    return _filter_samples(samples, ",".join(filters))


def mix_program(lines: list[dict], effects: list[dict], music: dict | None, out_wav: Path,
                *, duration: float, settings: dict | None = None) -> dict:
    """Level a set of voice tracks together, duck music, master and measure.

    Lines are timed tracks with path/start/gain/text and optional heard/match metadata.
    Settings override DEFAULT_MIX (duck merges recursively). Stem numbers are measured
    before the master, since nonlinear peak limiting prevents exact post-master stems.
    """
    cfg = {**DEFAULT_MIX, **(settings or {})}
    cfg["duck"] = {**DEFAULT_MIX["duck"], **(settings or {}).get("duck", {})}
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Program duration must be finite and positive")
    if (not all(math.isfinite(cfg[k]) for k in cfg if k != "duck")
            or not -60 <= cfg["voice_peak_db"] < 0 or not -60 <= cfg["true_peak_db"] < 0
            or not 0 <= cfg["sfx_under_voice"] <= 1
            or not cfg["duck"]["max_db"] <= cfg["duck"]["min_db"] <= 0):
        raise ValueError("Invalid mix settings: use finite levels, negative ceilings/depths and sfx_under_voice in [0,1]")
    out_wav = Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".mix-", dir=out_wav.parent) as temp_dir:
        temp = Path(temp_dir)
        sources = [_read_wav(Path(line["path"])) for line in lines]
        joined = np.concatenate(sources) if sources else np.zeros(SAMPLE_RATE)
        _write_wav(temp / "voice-before.wav", joined)
        before = measure_loudness(temp / "voice-before.wav")
        gain_db = cfg["voice_lufs"] - before["integrated_lufs"] if sources else 0.0
        leveled = [_limit(samples, gain_db, cfg["voice_peak_db"]) for samples in sources]
        _write_wav(temp / "voice-after.wav", np.concatenate(leveled) if leveled else joined)
        after = measure_loudness(temp / "voice-after.wav")
        voice_tracks, spans = [], []
        for i, (line, samples) in enumerate(zip(lines, leveled)):
            path = temp / f"voice-{i}.wav"
            _write_wav(path, samples)
            voice_tracks.append({**line, "path": path})
            start = float(line.get("start", 0))
            spans.append((start, min(duration, start + len(samples) / SAMPLE_RATE)))
        voice_stem = _mix_samples(voice_tracks, duration)
        gap_mask = np.ones(len(voice_stem), dtype=bool)
        for start, end in spans:
            gap_mask[round(start * SAMPLE_RATE):round(end * SAMPLE_RATE)] = False
        music_stem = np.zeros_like(voice_stem)
        depth, music_gain_db, music_gap_db = None, None, None
        margin_limited = False
        if music:
            music_track = {**music, "fade_in": 0.5, "fade_out": 1.5}
            base = _mix_samples([music_track], duration)
            if music.get("envelope"):  # stretches where the music is deliberately cut are not "gaps" to calibrate on
                points = np.asarray(music["envelope"], dtype=float)
                gap_mask &= np.interp(np.arange(len(base)) / SAMPLE_RATE - float(music.get("start", 0)), *points.T) > 0.5
            # Solve gap calibration and duck depth together. Raising gap gain
            # also raises music under speech, and merged short gaps stay ducked.
            required = 120.0
            for start, end in spans:
                a, b = round(start * SAMPLE_RATE), round(end * SAMPLE_RATE)
                required = min(required, rms_db(voice_stem[a:b]) - rms_db(base[a:b]) - cfg["voice_over_music_db"] - 0.05)
            times = np.arange(len(base)) / SAMPLE_RATE
            lower, upper = -80.0, 80.0
            for _ in range(20):
                music_gain_db = (lower + upper) / 2
                depth = max(cfg["duck"]["max_db"], min(cfg["duck"]["min_db"], required - music_gain_db))
                envelope = np.asarray(duck_envelope(spans, duration, depth, cfg["duck"]))
                music_stem = base * 10 ** (music_gain_db / 20) * np.interp(times, *envelope.T)
                measured = rms_db(music_stem[gap_mask] if gap_mask.any() else music_stem)
                if measured < cfg["music_gap_db"]:
                    lower = music_gain_db
                else:
                    upper = music_gain_db
            margin_limited = required - music_gain_db < cfg["duck"]["max_db"]
            music_gap_db = rms_db(music_stem[gap_mask]) if gap_mask.any() else None
        fx_tracks = []
        for fx in effects:
            under = any(start <= fx.get("start", 0) < end for start, end in spans)
            fx_tracks.append({**fx, "gain": fx.get("gain", 1) * (cfg["sfx_under_voice"] if under else 1)})
        premaster = voice_stem + music_stem + _mix_samples(fx_tracks, duration)
        # Measure without clipping a floating sum: fixed attenuation is restored
        # in the computed master gain, not applied to the final stem numbers.
        headroom_db = min(0.0, -1 - 20 * math.log10(max(float(np.max(np.abs(premaster))), 1e-9)))
        _write_wav(temp / "premaster.wav", premaster * 10 ** (headroom_db / 20))
        stats = measure_loudness(temp / "premaster.wav")
        master_db = cfg["target_lufs"] - stats["integrated_lufs"] + headroom_db
        mastered = _limit(premaster, master_db, cfg["true_peak_db"], true_peak=True)
        _write_wav(out_wav, mastered)
        final = measure_loudness(out_wav)
        trim_db = 0.0
        if final["true_peak_db"] is not None and final["true_peak_db"] > cfg["true_peak_db"]:
            trim_db = cfg["true_peak_db"] - final["true_peak_db"] - 0.1
            _write_wav(out_wav, mastered * 10 ** (trim_db / 20))
            final = measure_loudness(out_wav)
        reports = []
        for line, (start, end) in zip(lines, spans):
            a, b = round(start * SAMPLE_RATE), round(end * SAMPLE_RATE)
            vdb, mdb = rms_db(voice_stem[a:b]), rms_db(music_stem[a:b])
            reports.append({**{k: line.get(k) for k in ("text", "heard", "match", "transcribe_seconds")},
                            "start": start, "end": end, "voice_db": vdb, "music_db": mdb,
                            "voice_minus_music": vdb - mdb if music else None})
        ordered = sorted(spans)
        margins = [line["voice_minus_music"] for line in reports if line["voice_minus_music"] is not None]
        return {
            "settings": cfg, "voice_lufs_before": before["integrated_lufs"] if lines else None,
            "voice_lufs_after": after["integrated_lufs"] if lines else None, "voice_gain_db": gain_db,
            "duck_depth_db": depth, "duck_at_limit": margin_limited, "music_gain_db": music_gain_db,
            "lines": reports, "music_gap_db": music_gap_db, "stem_measurement_stage": "before master",
            "voice_over_music_db": min(margins) if margins else None,
            "minimum_line_gap": min((b[0] - a[1] for a, b in zip(ordered, ordered[1:])), default=None),
            "master_gain_db": master_db, "master_peak_trim_db": trim_db,
            "integrated_lufs": final["integrated_lufs"], "true_peak_db": final["true_peak_db"],
            "mismatched_lines": [line for line in reports if line["match"] is False],
            "seconds": len(mastered) / SAMPLE_RATE,
        }
