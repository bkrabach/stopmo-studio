"""Rhubarb mouth cues with a deterministic, dependency-light energy fallback."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
import tempfile

import numpy as np

from .audio import SAMPLE_RATE, _read_wav, _run, _write_wav, wav_duration

SHAPES = "ABCDEFGHX"
_ROOT = Path(__file__).resolve().parents[2]
_PRIORITY = {"B": 0, "G": 1, "H": 1, "X": 2, "A": 3, "C": 3, "D": 3, "E": 3, "F": 3}


def _rhubarb() -> str | None:
    candidates = [os.environ.get("STOPMO_RHUBARB"), str(_ROOT / "vendor/rhubarb/rhubarb"),
                  shutil.which("rhubarb")]
    return next((str(p) for p in candidates if p and Path(p).is_file() and os.access(p, os.X_OK)), None)


def available_backends() -> list[str]:
    return (["rhubarb"] if _rhubarb() else []) + ["energy"]


def _append(cues: list[dict], start: float, end: float, shape: str) -> None:
    if end <= start:
        return
    if cues and cues[-1]["shape"] == shape:
        cues[-1]["end"] = end
    else:
        cues.append({"start": start, "end": end, "shape": shape})


def _contiguous(cues: list[dict], duration: float) -> list[dict]:
    result: list[dict] = []
    cursor = 0.0
    for cue in sorted(cues, key=lambda c: c["start"]):
        start = max(cursor, min(duration, float(cue["start"])))
        end = max(start, min(duration, float(cue["end"])))
        if start > cursor:
            _append(result, cursor, start, "X")
        shape = str(cue["shape"])
        if shape not in SHAPES or len(shape) != 1:
            raise ValueError(f"Unknown mouth shape {shape!r}")
        _append(result, start, end, shape)
        cursor = end
    _append(result, cursor, duration, "X")
    return result


def _energy(wav: Path, text: str | None, duration: float) -> list[dict]:
    samples = _read_wav(wav)
    window = round(0.04 * SAMPLE_RATE)
    if not len(samples):
        return []
    padded = np.pad(samples, (0, (-len(samples)) % window))
    rms = np.sqrt(np.mean(padded.reshape(-1, window) ** 2, axis=1))
    reference = max(0.015, float(np.percentile(rms, 95)))
    levels = rms / reference
    vowels = [c for c in (text or "").lower() if c in "aeiou"]
    voiced = np.flatnonzero(rms > max(0.0015, reference * 0.055))
    ranks = {int(index): rank for rank, index in enumerate(voiced)}
    cues: list[dict] = []
    for index, (level, power) in enumerate(zip(levels, rms)):
        if power <= max(0.0015, reference * 0.055):
            shape = "X"
        elif level < 0.16:
            shape = "A" if index % 3 == 0 else "B"
        elif level < 0.38:
            shape = "B"
        else:
            shape = "D" if level > 0.72 else "C"
            # Distributed vowel guesses, NOT a forced alignment or phoneme recognizer.
            if vowels:
                vowel = vowels[min(len(vowels) - 1, ranks[index] * len(vowels) // max(1, len(voiced)))]
                if vowel in "ou":
                    shape = "F" if vowel == "u" else "E"
        _append(cues, index * window / SAMPLE_RATE, min(duration, (index + 1) * window / SAMPLE_RATE), shape)
    return _contiguous(cues, duration)


def mouth_cues(wav: Path, text: str | None = None, *, backend: str = "auto") -> list[dict]:
    """Return contiguous seconds-based Rhubarb A..H/X cues covering the WAV.

    Empty WAVs return []; all nonempty WAVs have at least one positive-length cue.
    Energy is a visual fallback, not accurate phonetic lip-sync.
    """
    wav = Path(wav)
    duration = wav_duration(wav)
    if backend == "auto":
        backend = available_backends()[0]
    if backend not in ("energy", "rhubarb"):
        raise ValueError(f"Unknown lip-sync backend {backend!r}; choose auto, rhubarb, or energy")
    binary = _rhubarb()
    if backend == "rhubarb" and binary is None:
        raise RuntimeError("Rhubarb is not installed. On macOS, run tools/install_voice_tools.sh --rhubarb "
                           "(Rosetta required on Apple Silicon), or set STOPMO_RHUBARB to a local executable.")
    if duration <= 0:
        return []
    if backend == "energy":
        return _energy(wav, text, duration)
    with tempfile.TemporaryDirectory(prefix=".lipsync-", dir=wav.parent) as temp:
        # Canonical PCM input also handles callers supplying stereo/other PCM bit depths.
        source = Path(temp) / "source.wav"
        _write_wav(source, _read_wav(wav))
        command = [binary, "-f", "json", "--extendedShapes", "GHX", "-r", "pocketSphinx", "--threads", "2"]
        if text:
            dialogue = Path(temp) / "dialogue.txt"
            dialogue.write_text(text, encoding="utf-8")
            command += ["-d", str(dialogue)]
        result = _run(command + [str(source)])
        try:
            raw = json.loads(result.stdout)["mouthCues"]
            return _contiguous([{"start": c["start"], "end": c["end"], "shape": c["value"]} for c in raw], duration)
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Rhubarb returned invalid JSON mouth cues: {exc}") from exc


def _runs(frames: list[str]) -> list[list]:
    runs = []
    for frame, shape in enumerate(frames):
        if runs and runs[-1][2] == shape:
            runs[-1][1] = frame + 1
        else:
            runs.append([frame, frame + 1, shape])
    return runs


def quantize(cues: list[dict], fps: float, *, min_hold: int = 1) -> list[tuple[int, str]]:
    """Snap to exposure frames, retain only changes, and merge undersized holds.

    A frame takes its greatest-overlap shape; vowel/A wins overlap ties over B.
    Short important shapes can absorb an adjacent B rather than disappear. The
    final hold obeys min_hold too, unless the entire clip is shorter than it.
    """
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError("fps must be finite and positive")
    if isinstance(min_hold, bool) or not isinstance(min_hold, int) or min_hold < 1:
        raise ValueError("min_hold must be a positive integer")
    if not cues:
        return [(0, "X")]
    previous_end = 0.0
    for cue in cues:
        start, end, shape = float(cue["start"]), float(cue["end"]), cue["shape"]
        if not all(math.isfinite(v) for v in (start, end)) or start < previous_end - 1e-8 or end <= start:
            raise ValueError("Cues must have positive lengths, be sorted, and not overlap")
        if shape not in _PRIORITY:
            raise ValueError(f"Unknown mouth shape {shape!r}")
        previous_end = end
    count = max(1, math.ceil(previous_end * fps - 1e-9))
    frames = ["X"] * count
    overlaps = np.zeros(count)
    for cue in cues:
        first = max(0, math.floor(cue["start"] * fps))
        last = min(count, math.ceil(cue["end"] * fps))
        for frame in range(first, last):
            overlap = max(0, min(cue["end"], (frame + 1) / fps) - max(cue["start"], frame / fps))
            if overlap > overlaps[frame] + 1e-9 or (abs(overlap - overlaps[frame]) <= 1e-9
                                                       and _PRIORITY[cue["shape"]] > _PRIORITY[frames[frame]]):
                overlaps[frame] = overlap
                frames[frame] = cue["shape"]
    while True:
        runs = _runs(frames)
        short = next((i for i, (a, b, _) in enumerate(runs) if b - a < min_hold), None)
        if short is None or len(runs) == 1:
            break
        start, end, shape = runs[short]
        neighbors = [i for i in (short - 1, short + 1) if 0 <= i < len(runs)]
        weaker = [i for i in neighbors if _PRIORITY[runs[i][2]] < _PRIORITY[shape]]
        if weaker:
            chosen = min(weaker, key=lambda i: (_PRIORITY[runs[i][2]], runs[i][1] - runs[i][0]))
            a, b, _ = runs[chosen]
            frames[a:b] = [shape] * (b - a)
        else:
            chosen = max(neighbors, key=lambda i: (_PRIORITY[runs[i][2]], runs[i][1] - runs[i][0]))
            frames[start:end] = [runs[chosen][2]] * (end - start)
    return [(int(start), shape) for start, _, shape in _runs(frames)]
