import math
from pathlib import Path

import numpy as np
import pytest

from stopmo import audio, lipsync


@pytest.fixture
def audio_dir(tmp_path):
    return tmp_path


def check_cues(cues, duration):
    assert cues
    assert cues[0]["start"] == 0
    assert cues[-1]["end"] == pytest.approx(duration, abs=1e-9)
    for index, cue in enumerate(cues):
        assert cue["end"] > cue["start"]
        assert cue["shape"] in lipsync.SHAPES
        if index:
            assert cue["start"] == cues[index - 1]["end"]
            assert cue["shape"] != cues[index - 1]["shape"]


def test_energy_covers_audio_and_silence(audio_dir):
    # Deliberately non-window-aligned duration exercises final-sample coverage.
    count = 48017
    t = np.arange(count) / 48000
    samples = np.sin(2 * np.pi * 180 * t) * np.linspace(0.01, 0.8, count)
    samples[:4800] = samples[-4800:] = 0
    path = audio_dir / "envelope.wav"
    audio._write_wav(path, samples)
    for text in (None, "Oh, a beautiful cup of tea!"):
        cues = lipsync.mouth_cues(path, text, backend="energy")
        check_cues(cues, count / 48000)
        assert cues[0]["shape"] == cues[-1]["shape"] == "X"
        assert any(c["shape"] in "CDEF" for c in cues)
    audio._write_wav(path, np.zeros(1000))
    assert lipsync.mouth_cues(path, backend="energy") == [{"start": 0, "end": 1000 / 48000, "shape": "X"}]
    audio._write_wav(path, np.zeros(0))
    assert lipsync.mouth_cues(path, backend="energy") == []


@pytest.mark.skipif("rhubarb" not in lipsync.available_backends(), reason="optional Rhubarb binary not installed")
@pytest.mark.skipif(not audio.kokoro_available(), reason="Kokoro required for the integration speech fixture")
def test_rhubarb_real_speech(audio_dir):
    path = audio_dir / "speech.wav"
    text = "Hello there! Time to begin."
    seconds = audio.synthesize(text, path)
    cues = lipsync.mouth_cues(path, text, backend="rhubarb")
    check_cues(cues, seconds)
    assert any(c["shape"] != "X" for c in cues)


def test_unavailable_rhubarb_and_auto_fallback(audio_dir, monkeypatch):
    path = audio_dir / "silent.wav"
    audio._write_wav(path, np.zeros(4800))
    monkeypatch.setattr(lipsync, "_rhubarb", lambda: None)
    assert lipsync.available_backends() == ["energy"]
    with pytest.raises(RuntimeError, match="install_voice_tools"):
        lipsync.mouth_cues(path, backend="rhubarb")
    check_cues(lipsync.mouth_cues(path), 0.1)
    with pytest.raises(ValueError):
        lipsync.mouth_cues(path, backend="missing")


def test_contiguous_normalizer_fills_gaps():
    cues = lipsync._contiguous([{"start": 0.1, "end": 0.3, "shape": "A"},
                               {"start": 0.3, "end": 0.4, "shape": "A"},
                               {"start": 0.6, "end": 1.1, "shape": "C"}], 1)
    check_cues(cues, 1)
    assert [c["shape"] for c in cues] == ["X", "A", "X", "C"]


def test_quantize_basic_and_tie_priority():
    assert lipsync.quantize([], 12) == [(0, "X")]
    cues = [{"start": 0, "end": 0.5, "shape": "A"}, {"start": 0.5, "end": 1, "shape": "C"}]
    assert lipsync.quantize(cues, 12) == [(0, "A"), (6, "C")]
    tied = [{"start": 0, "end": 0.05, "shape": "B"}, {"start": 0.05, "end": 0.1, "shape": "A"}]
    assert lipsync.quantize(tied, 10) == [(0, "A")]


@pytest.mark.parametrize("important", list("ACDEF"))
def test_min_hold_keeps_important_over_b(important):
    cues = [{"start": 0, "end": 0.1, "shape": "B"},
            {"start": 0.1, "end": 0.2, "shape": important},
            {"start": 0.2, "end": 0.5, "shape": "B"}]
    result = lipsync.quantize(cues, 10, min_hold=2)
    assert result[0] == (0, important)
    assert all(b[0] - a[0] >= 2 for a, b in zip(result, result[1:]))
    assert 5 - result[-1][0] >= 2


@pytest.mark.parametrize("fps", [8, 12, 23.976, 24])
def test_quantize_randomized_invariants(fps):
    rng = np.random.default_rng(72)
    for _ in range(30):
        cursor = 0
        cues = []
        for _ in range(35):
            end = cursor + rng.uniform(0.005, 0.3)
            cues.append({"start": cursor, "end": end, "shape": str(rng.choice(list(lipsync.SHAPES)))})
            cursor = end
        hold = int(rng.integers(1, 5))
        result = lipsync.quantize(cues, fps, min_hold=hold)
        count = math.ceil(cursor * fps - 1e-9)
        assert result[0][0] == 0
        assert all(isinstance(frame, int) and 0 <= frame < count and shape in lipsync.SHAPES for frame, shape in result)
        assert all(b[0] - a[0] >= hold and b[1] != a[1] for a, b in zip(result, result[1:]))
        assert count - result[-1][0] >= hold


@pytest.mark.parametrize("fps,hold", [(0, 1), (float("nan"), 1), (12, 0), (12, 1.5)])
def test_quantize_invalid(fps, hold):
    with pytest.raises(ValueError):
        lipsync.quantize([], fps, min_hold=hold)
