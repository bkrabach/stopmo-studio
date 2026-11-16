import wave

import numpy as np
import pytest

from stopmo import audio
from stopmo.sfx import music, sfx


@pytest.fixture
def audio_dir(tmp_path):
    return tmp_path


def check_wav(path, seconds=None):
    with wave.open(str(path), "rb") as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth(), wav.getcomptype()) == (48000, 1, 2, "NONE")
        data = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
        if seconds is not None:
            assert wav.getnframes() == round(seconds * 48000)
    assert np.isfinite(data).all()
    return data


@pytest.mark.skipif(not audio.kokoro_available(), reason="Kokoro model not installed")
def test_kokoro_synthesize(audio_dir):
    path = audio_dir / "kokoro.wav"
    seconds = audio.synthesize("Ready for a new idea.", path, voice="narrator")
    assert seconds > 0.2
    check_wav(path)
    assert "bm_george" in audio.list_voices()


def test_mix_duration_fades_and_limiting(audio_dir):
    source = audio_dir / "source.wav"
    audio._write_wav(source, np.ones(4800) * 0.8)
    mixed = audio.mix([{"path": source, "start": 0.05, "gain": 5, "fade_in": 0.02, "fade_out": 0.02},
                       {"path": source, "start": 0.05, "gain": 5}], audio_dir / "mixed.wav")
    samples = check_wav(mixed, 0.15).astype(float) / 32768
    assert np.max(np.abs(samples)) < 0.981
    assert np.all(samples[:2400] == 0)
    trimmed = audio.mix([{"path": source, "start": 0.05}], audio_dir / "trimmed.wav", duration=0.08)
    check_wav(trimmed, 0.08)
    faded = audio.mix([{"path": source, "fade_in": 0.02, "fade_out": 0.02}], audio_dir / "fade.wav")
    result = check_wav(faded, 0.1)
    assert result[0] == result[-1] == 0
    assert result[2000] > 0
    check_wav(audio.mix([], audio_dir / "empty.wav", duration=0.12), 0.12)


@pytest.mark.parametrize("kind,seconds", [("footstep", 0.22), ("pop", 0.18), ("boing", 0.85),
    ("whoosh", 0.65), ("clink", 0.75), ("thud", 0.4), ("squish", 0.5), ("click", 0.07),
    ("ding", 1.6), ("pour", 1.5), ("tick", 0.09), ("whirr", 1.3), ("choir", 3.2), ("sting", 2.2),
    ("crunch", 0.32), ("whistle", 1.3), ("slurp", 0.55), ("thunder", 2.6)])
def test_every_sfx(audio_dir, kind, seconds):
    path = audio_dir / f"{kind}.wav"
    assert sfx(kind, path, seed=7) == pytest.approx(seconds)
    samples = check_wav(path, seconds).astype(float) / 32768
    assert np.max(np.abs(samples)) == pytest.approx(10 ** (-6 / 20), abs=0.0001)
    assert abs(samples[0]) < 0.0001 and abs(samples[-1]) < 0.0001
    override = audio_dir / "override.wav"
    assert sfx(kind, override, duration=0.12345) == pytest.approx(round(0.12345 * 48000) / 48000)
    check_wav(override, 0.12345)


@pytest.mark.parametrize("style", ["brass_band", "music_box", "ukulele", "marimba", "starlight"])
def test_every_music_style(audio_dir, style):
    path = audio_dir / f"{style}.wav"
    assert music(path, duration=1.2345, style=style, key="Eb") == pytest.approx(1.2345)
    samples = check_wav(path, 1.2345).astype(float) / 32768
    assert np.max(np.abs(samples)) == pytest.approx(10 ** (-6 / 20), abs=0.0001)
    assert samples[0] == samples[-1] == 0


def test_sound_seed_reproducible(audio_dir):
    a, b, c = [audio_dir / name for name in ("a.wav", "b.wav", "c.wav")]
    sfx("pour", a, seed=42)
    sfx("pour", b, seed=42)
    sfx("pour", c, seed=43)
    assert a.read_bytes() == b.read_bytes() != c.read_bytes()
    music(a, duration=2, seed=42)
    music(b, duration=2, seed=42)
    assert a.read_bytes() == b.read_bytes()


def test_invalid_inputs_and_missing_backend(audio_dir, monkeypatch):
    path = audio_dir / "no.wav"
    for kwargs in ({"rate": 0}, {"rate": float("nan")}, {"pitch": 99}):
        with pytest.raises(ValueError):
            audio.synthesize("Hello", path, **kwargs)
    with pytest.raises(ValueError):
        audio.synthesize(" ", path)
    with pytest.raises(ValueError):
        audio.mix([], path, duration=-1)
    with pytest.raises(ValueError):
        sfx("missing", path)
    with pytest.raises(ValueError):
        sfx("pop", path, duration=0)
    with pytest.raises(ValueError):
        music(path, duration=1, style="missing")
    monkeypatch.setattr(audio, "kokoro_available", lambda: False)
    with pytest.raises(RuntimeError, match="install_voice_tools"):
        audio.synthesize("Hello", path)
    monkeypatch.setattr(audio, "acting_available", lambda: False)
    with pytest.raises(RuntimeError, match="install_voice_tools"):
        audio.act("dramabox", [], audio_dir)
    with pytest.raises(ValueError, match="unknown acting engine"):
        audio.act("chatterbox", [], audio_dir)


def test_mix_envelope_relative_to_track_and_multiplies_gain(audio_dir):
    source = audio_dir / "constant.wav"
    audio._write_wav(source, np.ones(48000) * 0.2)
    mixed = audio.mix([{"path": source, "start": 0.25, "gain": 2,
                        "envelope": [(0, 0), (0.5, 1), (1, 0)]}], audio_dir / "envelope.wav")
    data = audio._read_wav(mixed)
    assert data[round(0.25 * 48000)] == 0
    assert data[round(0.5 * 48000)] == pytest.approx(0.2, abs=1e-4)
    assert data[round(0.75 * 48000)] == pytest.approx(0.4, abs=1e-4)
    for envelope in ([(1, 1), (0, 0)], [(0, 1), (0, 0)], [(0, float("nan"))]):
        with pytest.raises(ValueError, match="Envelope"):
            audio.mix([{"path": source, "envelope": envelope}], audio_dir / "bad.wav")


def test_measure_loudness_synthetic_tone(audio_dir):
    path = audio_dir / "tone.wav"
    audio._write_wav(path, 0.1 * np.sin(2 * np.pi * 1000 * np.arange(3 * 48000) / 48000))
    stats = audio.measure_loudness(path)
    assert stats["integrated_lufs"] == pytest.approx(-23, abs=0.2)
    assert stats["true_peak_db"] == pytest.approx(-20, abs=0.2)


def test_kokoro_native_speed_no_atempo(audio_dir, monkeypatch):
    received = []
    class Model:
        def create(self, text, *, voice, speed, lang):
            received.append(speed)
            return 0.1 * np.sin(2 * np.pi * 200 * np.arange(24000) / 24000), 24000
    monkeypatch.setattr(audio, "list_voices", lambda: ["af_heart"])
    monkeypatch.setattr(audio, "_kokoro", Model)
    original_run, commands = audio._run, []
    def run(args, **kwargs):
        commands.append(args)
        return original_run(args, **kwargs)
    monkeypatch.setattr(audio, "_run", run)
    audio.synthesize("Test", audio_dir / "native.wav", voice="af_heart", rate=1.1)
    assert received == [1.1]
    assert not any("atempo" in " ".join(command) for command in commands)
    assert any("highpass=f=70,acompressor=threshold=-24dB:ratio=3:attack=5:release=120" in command
               for command in commands)


def test_finish_take_trims_levels_and_changes_tempo(audio_dir):
    tone = 0.02 * np.sin(2 * np.pi * 220 * np.arange(48000) / 48000)
    raw = audio_dir / "raw.wav"
    audio._write_wav(raw, np.concatenate([np.zeros(24000), tone, np.zeros(24000)]), sample_rate=48000)
    seconds = audio.finish_take(raw, audio_dir / "line.wav")
    assert seconds == pytest.approx(1.08, abs=0.03)                      # silence trimmed to 40 ms each side
    data = audio._read_wav(audio_dir / "line.wav")
    level = 20 * np.log10(np.sqrt(np.mean(data[np.abs(data) > 0.003] ** 2)))
    assert level == pytest.approx(audio.LINE_RMS_DB, abs=1.0)            # quiet take brought up to the line level
    assert audio.finish_take(raw, audio_dir / "fast.wav", rate=1.25) == pytest.approx(seconds / 1.25, abs=0.06)
    assert audio.finish_take(raw, audio_dir / "high.wav", pitch=3) == pytest.approx(seconds, abs=0.03)


def test_expected_seconds_grows_with_text_pace_and_events():
    short, long = audio.expected_seconds("Hello, friend."), audio.expected_seconds("We can try a longer sentence with several more words.")
    assert 1.8 <= short < long
    assert audio.expected_seconds("Hello, friend.", "slow", "sigh") > short
