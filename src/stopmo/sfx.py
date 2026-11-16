"""Deterministic original cartoon foley and tiny procedural music ensembles."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from .audio import SAMPLE_RATE, _write_wav

_DURATIONS = {"footstep": 0.22, "pop": 0.18, "boing": 0.85, "whoosh": 0.65,
              "clink": 0.75, "thud": 0.4, "squish": 0.5, "click": 0.07,
              "ding": 1.6, "pour": 1.5, "tick": 0.09, "whirr": 1.3,
              "choir": 3.2, "sting": 2.2, "crunch": 0.32, "whistle": 1.3, "slurp": 0.55, "thunder": 2.6,
              "tap": 0.12, "chirp": 0.34, "sparkle": 0.9, "tada": 1.5,
              "blip": 0.42, "twinkle": 1.1}
_KEYS = {"C": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3, "E": 4, "F": 5,
         "F#": 6, "GB": 6, "G": 7, "G#": 8, "AB": 8, "A": 9, "A#": 10, "BB": 10, "B": 11}
_PEAK = 10 ** (-6 / 20)


def _length(duration: float) -> int:
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("duration must be finite and positive")
    return max(1, round(duration * SAMPLE_RATE))


def _edges(samples: np.ndarray, attack: float = 0.004, release: float = 0.012) -> np.ndarray:
    for seconds, reverse in ((attack, False), (release, True)):
        count = min(len(samples), round(seconds * SAMPLE_RATE))
        if count:
            ramp = np.sin(np.linspace(0, np.pi / 2, count)) ** 2
            if reverse:
                samples[-count:] *= ramp[::-1]
            else:
                samples[:count] *= ramp
    return samples


def _normalize(samples: np.ndarray) -> np.ndarray:
    peak = float(np.max(np.abs(samples))) if len(samples) else 0
    return samples * (_PEAK / peak) if peak > 1e-12 else samples


def _noise(rng: np.random.Generator, count: int, cutoff: float) -> np.ndarray:
    noise = rng.standard_normal(count)
    frequencies = np.fft.rfftfreq(count, 1 / SAMPLE_RATE)
    filtered = np.fft.irfft(np.fft.rfft(noise) / np.sqrt(1 + (frequencies / cutoff) ** 6), n=count)
    return filtered / max(float(np.std(filtered)), 1e-8)


def _osc(frequency: float | np.ndarray, time: np.ndarray) -> np.ndarray:
    if np.ndim(frequency):
        return np.sin(2 * np.pi * np.cumsum(frequency) / SAMPLE_RATE)
    return np.sin(2 * np.pi * frequency * time)


def sfx(kind: str, out_wav: Path, *, duration: float | None = None, seed: int = 0, **params) -> float:
    """Create original mono foley at -6 dBFS peak. Optional pitch=semitones.

    Explicit durations set the exact sample count, rather than padding a default
    effect. Seeds make noise components reproducible. No external assets needed.
    """
    if kind not in _DURATIONS:
        raise ValueError(f"Unknown sfx {kind!r}; choose {', '.join(_DURATIONS)}")
    count = _length(_DURATIONS[kind] if duration is None else duration)
    t = np.arange(count) / SAMPLE_RATE
    length = count / SAMPLE_RATE
    x = t / length
    rng = np.random.default_rng(seed)
    pitch = float(params.get("pitch", 0))
    if not math.isfinite(pitch) or abs(pitch) > 24:
        raise ValueError("pitch must be finite and within +/-24 semitones")
    p = 2 ** (pitch / 12)
    noise = _noise(rng, count, 2200)
    if kind == "footstep":
        signal = (0.8 * _osc(p * (48 + 90 * np.exp(-x * 12)), t)
                  + 0.16 * _noise(rng, count, 700)) * np.exp(-x * 7)
    elif kind == "pop":
        signal = (_osc(p * (140 + 1100 * np.exp(-x * 15)), t) + 0.08 * noise) * np.exp(-x * 8)
    elif kind == "boing":
        frequency = p * (120 + 110 * np.exp(-x * 2) + 55 * np.sin(2 * np.pi * 11 * t) * np.exp(-x * 3))
        phase = 2 * np.pi * np.cumsum(frequency) / SAMPLE_RATE
        signal = (np.sin(phase) + 0.22 * np.sin(2 * phase) + 0.06 * np.sin(3 * phase)) * np.exp(-x * 4)
    elif kind == "whoosh":
        signal = (noise + 0.15 * _osc(p * (200 + 1200 * x ** 2), t)) * np.sin(np.pi * x) ** 2
    elif kind == "clink":
        signal = sum(g * _osc(p * 1420 * ratio, t) * np.exp(-x * decay)
                     for g, ratio, decay in ((1, 1, 8), (0.5, 1.49, 11), (0.3, 2.11, 16), (0.16, 2.73, 22)))
    elif kind == "thud":
        signal = (_osc(p * (42 + 55 * np.exp(-x * 10)), t) + 0.22 * _noise(rng, count, 450)) * np.exp(-x * 6)
    elif kind == "squish":
        tremolo = 0.5 + 0.5 * np.sin(2 * np.pi * (25 * t + 14 * t ** 2))
        signal = (0.55 * noise * tremolo + _osc(p * (80 + 110 * np.sin(np.pi * x)), t)) * np.sin(np.pi * x) ** 2
    elif kind == "click":
        signal = (0.5 * noise + _osc(p * 2100, t)) * np.exp(-x * 16)
    elif kind == "ding":
        signal = sum(g * _osc(p * 880 * ratio, t) * np.exp(-x * decay)
                     for g, ratio, decay in ((1, 1, 3), (0.28, 2, 5), (0.14, 2.74, 8), (0.05, 4.1, 12)))
    elif kind == "pour":
        signal = 0.12 * noise * (0.7 + 0.3 * np.sin(2 * np.pi * 17 * t)) * np.sin(np.pi * x) ** 0.6
        for _ in range(max(1, round(length * 26))):
            start = int(rng.uniform(0, max(1, count - 1)))
            n = min(count - start, round(0.06 * SAMPLE_RATE))
            tt = np.arange(n) / SAMPLE_RATE
            drop = _osc(p * rng.uniform(450, 1500) * np.exp(-tt * 9), tt) * np.exp(-tt * 90)
            signal[start:start + n] += _edges(drop, 0.001, 0.003) * rng.uniform(0.08, 0.22)
    elif kind == "tick":
        signal = (_osc(p * 1700, t) + 0.5 * _osc(p * 2900, t) + noise * 0.2) * np.exp(-x * 17)
    elif kind == "choir":  # a held, wordless "aah": the treasure shot
        signal = np.zeros(count)
        for midi, gain in ((60, 1.0), (64, 0.8), (67, 0.8), (72, 0.6), (76, 0.35)):
            f = p * 440 * 2 ** ((midi - 69) / 12)
            for detune in (-0.004, 0.0, 0.005):  # three singers per note
                vib = 1 + 0.006 * np.sin(2 * np.pi * (5.0 + 40 * abs(detune)) * t + rng.uniform(0, 6.28))
                phase = 2 * np.pi * np.cumsum(f * (1 + detune) * vib) / SAMPLE_RATE
                signal += gain * (np.sin(phase) + 0.35 * np.sin(2 * phase) + 0.12 * np.sin(3 * phase))
        signal *= np.minimum(1, x * 5) * np.minimum(1, (1 - x) * 2.2) ** 1.5
    elif kind == "sting":  # dun-DUNN: low brass minor chord over a drum hit
        signal = np.zeros(count)
        for start, notes, gain in ((0.0, (41, 48), 0.6), (0.28, (38, 45, 53, 56), 1.0)):
            n0 = round(start * SAMPLE_RATE)
            tt = t[:count - n0]
            env = np.minimum(1, tt * 40) * np.exp(-tt * (5.0 if start == 0 else 1.6))
            for midi in notes:
                ph = 2 * np.pi * p * 440 * 2 ** ((midi - 69) / 12) * tt
                signal[n0:] += gain * env * (np.sin(ph) + 0.5 * np.sin(2 * ph) + 0.3 * np.sin(3 * ph) + 0.15 * np.sin(4 * ph))
            drum = _osc(p * (50 + 70 * np.exp(-tt * 30)), tt) * np.exp(-tt * 9)
            signal[n0:] += gain * 1.6 * drum
    elif kind == "crunch":  # a dry biscuit: a burst of tiny cracks
        signal = np.zeros(count)
        for _ in range(26):
            start = int(rng.uniform(0, count * 0.75))
            n = min(count - start, round(rng.uniform(0.004, 0.014) * SAMPLE_RATE))
            crack = rng.standard_normal(n) * np.exp(-np.arange(n) / (n * 0.3))
            signal[start:start + n] += crack * rng.uniform(0.3, 1.0)
        signal = signal - np.convolve(signal, np.ones(24) / 24, mode="same")  # keep it bright
        signal *= np.exp(-x * 2.5)
    elif kind == "whistle":  # kettle coming to the boil
        frequency = p * (1500 + 1500 * (1 - np.exp(-x * 4)) + 25 * np.sin(2 * np.pi * 9 * t))
        tone = _osc(frequency, t)
        signal = (tone + 0.25 * _osc(2 * frequency, t) + 0.3 * _noise(rng, count, 6000)) \
            * np.minimum(1, x * 3) ** 2 * np.minimum(1, (1 - x) * 6)
    elif kind == "slurp":  # rising, bubbly
        bubble = 0.5 + 0.5 * np.sin(2 * np.pi * (38 * t + 30 * t ** 2))
        signal = (_noise(rng, count, 900 + 2500 * x.mean()) * bubble * 0.8
                  + 0.5 * _osc(p * (260 + 900 * x ** 2), t) * bubble) * np.sin(np.pi * x) ** 1.5
    elif kind == "thunder":  # a crack, then a long rumble
        rumble = _noise(rng, count, 90) * (np.exp(-x * 3) + 0.4 * np.exp(-((x - 0.35) / 0.12) ** 2))
        crack = _noise(rng, count, 3000) * np.exp(-x * 45)
        signal = rumble + 0.9 * crack
    elif kind == "tap":  # a toy set down on a table: a small woodblock knock
        signal = (_osc(p * 620, t) + 0.5 * _osc(p * 1480, t) + 0.15 * noise) * np.exp(-x * 9)
    elif kind == "chirp":  # a happy little robot: two quick rising blips
        signal = np.zeros(count)
        for start, low, high in ((0.0, 880, 1320), (0.16, 1175, 1760)):
            n = min(count - round(start * SAMPLE_RATE), round(0.13 * SAMPLE_RATE))
            tt = np.arange(n) / SAMPLE_RATE
            frequency = p * (low + (high - low) * (tt / 0.13) ** 0.6)
            blip = np.sin(2 * np.pi * np.cumsum(frequency) / SAMPLE_RATE) * np.sin(np.pi * tt / 0.13) ** 0.7
            signal[round(start * SAMPLE_RATE):round(start * SAMPLE_RATE) + n] += blip
    elif kind == "blip":  # a character's little signature: two soft electric-piano notes, a fifth apart
        signal = np.zeros(count)
        for start, midi in ((0.0, 74), (0.11, 81)):
            note = _note(midi + round(pitch), 0.3, "keys", rng)
            a = round(start * SAMPLE_RATE)
            n = min(len(note), count - a)
            signal[a:a + n] += note[:n]
    elif kind == "twinkle":  # a scatter of tiny high bells, thinning out
        signal = np.zeros(count)
        for i in range(11):
            start = 0.07 * i + rng.uniform(0, 0.03)
            note = _note(96 + int(rng.choice((0, 2, 4, 7, 9, 12))) + round(pitch), 0.45, "bell", rng)
            a = round(start * SAMPLE_RATE)
            n = min(len(note), count - a)
            if n > 0:
                signal[a:a + n] += note[:n] * (1 - i / 14)
    elif kind in ("sparkle", "tada"):  # bell notes running up a major chord; tada ends on a held chord
        signal = np.zeros(count)
        steps = (0, 4, 7, 12, 16, 19) if kind == "sparkle" else (0, 4, 7)
        gap = 0.07 if kind == "sparkle" else 0.11
        notes = [(i * gap, 84 + s, 0.6) for i, s in enumerate(steps)]
        if kind == "tada":
            notes += [(0.36, 72 + s, 1.1) for s in (0, 4, 7, 12)]
        for start, midi, hold in notes:
            note = _note(midi + round(pitch), hold, "bell", rng)
            a = round(start * SAMPLE_RATE)
            n = min(len(note), count - a)
            signal[a:a + n] += note[:n]
    else:  # whirr: a soft motor with spin-up/down, not harsh white noise.
        speed = p * (90 + 100 * (1 - np.exp(-x * 12)))
        phase = 2 * np.pi * np.cumsum(speed) / SAMPLE_RATE
        signal = (np.sin(phase) + 0.3 * np.sin(2 * phase) + 0.1 * np.sin(5 * phase)
                  + 0.07 * noise) * (1 - np.exp(-x * 18)) * np.minimum(1, (1 - x) * 8)
    _write_wav(Path(out_wav), _normalize(_edges(signal)))
    return count / SAMPLE_RATE


def _note(midi: int, duration: float, instrument: str, rng: np.random.Generator) -> np.ndarray:
    count = max(1, round(duration * SAMPLE_RATE))
    t = np.arange(count) / SAMPLE_RATE
    frequency = 440 * 2 ** ((midi - 69) / 12)
    phase = 2 * np.pi * frequency * t
    if instrument == "bell":
        tone = (np.sin(phase + 0.7 * np.exp(-t * 5) * np.sin(2 * phase))
                + 0.12 * np.sin(3 * phase)) * np.exp(-t * 4.5)
        return _edges(tone, 0.003, 0.08)
    if instrument == "keys":  # soft electric piano: a bell-like start over a round sustained tone
        tone = (np.sin(phase + 1.6 * np.exp(-t * 9) * np.sin(phase * 7)) * 0.7 + np.sin(phase) * 0.6
                + 0.15 * np.sin(2 * phase)) * np.exp(-t * 3.2)
        return _edges(tone, 0.004, 0.08)
    if instrument == "pad":  # three slightly detuned voices swelling in: warm and airy
        tone = sum(np.sin(phase * d + i) for i, d in enumerate((0.996, 1.0, 1.004))) / 3 + 0.2 * np.sin(2 * phase)
        return _edges(tone * np.minimum(1, t / 0.25), 0.05, min(0.4, duration * 0.4))
    if instrument == "mallet":  # marimba: a round fundamental with a quick woody knock on top
        tone = (np.sin(phase) + 0.35 * np.sin(4 * phase) * np.exp(-t * 18)
                + 0.1 * np.sin(10 * phase) * np.exp(-t * 45)) * np.exp(-t * 7)
        return _edges(tone, 0.002, 0.05)
    if instrument == "bass":
        tone = (np.sin(phase) + 0.3 * np.sin(2 * phase)) * np.exp(-t * 3.5)
        return _edges(tone, 0.006, 0.06)
    if instrument == "pluck":
        tone = sum(np.sin(h * phase + rng.uniform(-0.04, 0.04)) * np.exp(-t * (4 + h * 1.5)) / h ** 1.6
                   for h in range(1, 7))
        return _edges(tone, 0.002, 0.035)
    # Warm, restrained brass (no sawtooth aliasing); breath and gentle vibrato.
    phase += 0.012 * np.sin(2 * np.pi * 5.1 * t) * np.minimum(1, t * 7)
    tone = (np.sin(phase) + 0.28 * np.sin(2 * phase) + 0.1 * np.sin(3 * phase)
            + 0.035 * np.sin(4 * phase)) * (0.9 + 0.1 * np.exp(-t * 8))
    return _edges(tone, 0.022, min(0.09, duration * 0.3))


def _marimba(signal: np.ndarray, beat: float, root: int, rng: np.random.Generator) -> None:
    """A bright, bouncy toy-shop tune written to fit the length: marimba pattern alone, then bass and
    shaker, then a bell melody with claps, and a last chord that lands 1.6 s before the end and rings."""
    count = len(signal)

    def add(start: float, wave: np.ndarray, gain: float) -> None:
        a = round(start * SAMPLE_RATE)
        if 0 <= a < count:
            n = min(len(wave), count - a)
            signal[a:a + n] += gain * wave[:n]

    def hit(start: float, kind: str) -> None:
        n = round({"shaker": 0.05, "clap": 0.09, "kick": 0.16}[kind] * SAMPLE_RATE)
        t = np.arange(n) / SAMPLE_RATE
        if kind == "kick":
            add(start, np.sin(2 * np.pi * np.cumsum(45 + 70 * np.exp(-t * 40)) / SAMPLE_RATE) * np.exp(-t * 22), 0.2)
        else:
            air = np.diff(rng.standard_normal(n + 1))  # the difference keeps the hiss and drops the rumble
            if kind == "shaker":
                add(start, air * np.exp(-t * 70), 0.012)
            else:
                add(start, air * sum(np.exp(-np.maximum(t - d, 0) * 60) * (t >= d) for d in (0.0, 0.011, 0.023)), 0.014)

    bar = 4 * beat
    bars = max(1, int((count / SAMPLE_RATE - 1.6) // bar))
    chords = ((0, 4), (7, 4), (9, 3), (5, 4))  # I V vi IV: (root offset, third)
    pattern = (0, 7, 12, 7, 4, 7, 12, 7)
    phrases = (((0, 4), (0.5, 7), (1, 9), (2, 7), (2.5, 4), (3, 2)), ((0, 9), (1, 12), (1.5, 9), (2, 7), (3, 4), (3.5, 7)),
               ((0, 12), (0.5, 14), (1, 16), (2, 12), (3, 9)), ((0, 7), (0.5, 9), (1, 7), (1.5, 4), (2, 2), (3, 0)))
    for b in range(bars):
        origin = b * bar
        offset, third = chords[b % 4]
        chord = root + offset - (12 if offset > 6 else 0)
        for eighth, step in enumerate(pattern):
            midi = chord + (third if step == 4 else step)
            add(origin + eighth * beat / 2, _note(midi, beat * 0.9, "mallet", rng), 0.16 if eighth % 2 == 0 else 0.11)
        if b >= 1:
            for eighth in range(8):
                hit(origin + eighth * beat / 2, "shaker")
        if b >= 2:
            for pulse, step in ((0, 0), (1.5, 0), (2, 7), (3.5, 7)):
                add(origin + pulse * beat, _note(chord - 24 + step, beat * 0.8, "bass", rng), 0.2)
            hit(origin, "kick")
            hit(origin + 2 * beat, "kick")
        if b >= 4:
            hit(origin + beat, "clap")
            hit(origin + 3 * beat, "clap")
            for pulse, step in phrases[b % 4]:
                add(origin + pulse * beat, _note(root + 12 + step, beat * 0.9, "bell", rng), 0.12)
    end = bars * bar  # the button: one bright chord, the bells running up it
    hit(end, "kick")
    hit(end, "clap")
    for i, step in enumerate((0, 4, 7, 12)):
        add(end, _note(root + step, 1.5, "mallet", rng), 0.16)
        add(end + 0.05 + i * 0.07, _note(root + 12 + step, 1.4, "bell", rng), 0.12)
    add(end, _note(root - 24, 1.5, "bass", rng), 0.24)


def _starlight(signal: np.ndarray, beat: float, root: int, rng: np.random.Generator) -> None:
    """Dreamy, bouncy electric-piano pop written to fit the length: keys and a pad alone, then bass and
    a soft four-on-the-floor kick with off-beat snaps, then a high bell tune; the last third lifts a
    step for the finish, and a final chord lands 1.8 s before the end and rings out."""
    count = len(signal)

    def add(start: float, wave: np.ndarray, gain: float) -> None:
        a = round(start * SAMPLE_RATE)
        if 0 <= a < count:
            n = min(len(wave), count - a)
            signal[a:a + n] += gain * wave[:n]

    def hit(start: float, kind: str) -> None:
        n = round({"snap": 0.06, "kick": 0.18, "hat": 0.03}[kind] * SAMPLE_RATE)
        t = np.arange(n) / SAMPLE_RATE
        if kind == "kick":
            add(start, np.sin(2 * np.pi * np.cumsum(48 + 60 * np.exp(-t * 35)) / SAMPLE_RATE) * np.exp(-t * 18), 0.17)
        else:
            air = np.diff(rng.standard_normal(n + 1))
            add(start, air * np.exp(-t * (55 if kind == "snap" else 120)), 0.013 if kind == "snap" else 0.006)

    bar = 4 * beat
    bars = max(1, int((count / SAMPLE_RATE - 1.8) // bar))
    chords = ((0, 4, 7, 11), (9, 12, 16, 19), (5, 9, 12, 16), (7, 11, 14, 17))   # Imaj7  vi7  IVmaj7  V7
    tune = (((0, 16), (1.5, 14), (2, 12), (3, 9)), ((0, 12), (1, 16), (2.5, 19), (3, 16)),
            ((0, 21), (1.5, 19), (2, 16), (3, 12)), ((0, 14), (1, 11), (2, 14), (3, 19)))
    for b in range(bars):
        origin = b * bar
        lift = 2 if b >= bars * 2 // 3 and bars >= 6 else 0   # the last third is a tone higher
        notes = [root + lift + n - (12 if n > 14 else 0) for n in chords[b % 4]]
        add(origin, sum(_note(n - 12, bar * 1.05, "pad", rng) for n in notes[:3]), 0.022)
        for eighth in range(8):   # keys: the chord rolled up and down
            n = notes[(0, 1, 2, 3, 2, 1, 2, 3)[eighth]]
            add(origin + eighth * beat / 2, _note(n, beat * 1.4, "keys", rng), 0.12 if eighth % 2 == 0 else 0.085)
        if b >= 1:
            for eighth in range(8):
                hit(origin + eighth * beat / 2, "hat")
        if b >= 2:
            for pulse in range(4):
                hit(origin + pulse * beat, "kick")
            hit(origin + beat, "snap")
            hit(origin + 3 * beat, "snap")
            for pulse, step in ((0, 0), (1.5, 0), (2.5, 7), (3, 12)):
                add(origin + pulse * beat, _note(notes[0] - 24 + step, beat * 0.7, "bass", rng), 0.19)
        if b >= 3:
            for pulse, step in tune[b % 4]:
                add(origin + pulse * beat, _note(root + lift + 12 + step, beat * 1.2, "bell", rng), 0.085)
    end, home = bars * bar, root + (2 if bars >= 6 else 0)
    hit(end, "kick")
    hit(end, "snap")
    for i, step in enumerate((0, 4, 7, 11, 14)):
        add(end + i * 0.045, _note(home + step, 1.7, "keys", rng), 0.13)
        add(end + 0.1 + i * 0.06, _note(home + 12 + step, 1.5, "bell", rng), 0.07)
    add(end, sum(_note(home - 12 + s, 1.7, "pad", rng) for s in (0, 4, 7)), 0.03)
    add(end, _note(home - 24, 1.6, "bass", rng), 0.22)


def music(out_wav: Path, *, duration: float, style: str = "brass_band", tempo: float = 108,
          key: str = "C", seed: int = 0) -> float:
    """Original I-IV-V-I miniature: oom-pah bass, chord stabs, and swung melody.

    Each four-bar phrase repeats with deterministic ornament choices; any positive
    duration is supported and written to the exact sample count with a 0.5 s fade.
    Styles are synth approximations, not sampled real ensembles.
    """
    count = _length(duration)
    if style not in ("brass_band", "music_box", "ukulele", "marimba", "starlight"):
        raise ValueError("style must be brass_band, music_box, ukulele, marimba, or starlight")
    if not math.isfinite(tempo) or not 30 <= tempo <= 300:
        raise ValueError("tempo must be between 30 and 300 BPM")
    if key.upper() not in _KEYS:
        raise ValueError(f"Unknown major key {key!r}")
    rng = np.random.default_rng(seed)
    signal = np.zeros(count, dtype=np.float64)
    beat = 60 / tempo
    root = 60 + _KEYS[key.upper()]
    if style == "starlight":
        _starlight(signal, beat, root, rng)
        _write_wav(Path(out_wav), _normalize(_edges(signal, attack=0.01, release=0.4)))
        return count / SAMPLE_RATE
    if style == "marimba":
        _marimba(signal, beat, root, rng)
        _write_wav(Path(out_wav), _normalize(_edges(signal, attack=0.01, release=0.3)))
        return count / SAMPLE_RATE
    instrument = {"brass_band": "brass", "music_box": "bell", "ukulele": "pluck"}[style]

    def add(start: float, midi: int, length: float, gain: float, timbre: str = instrument) -> None:
        offset = round(start * SAMPLE_RATE)
        if offset >= count:
            return
        note = _note(midi, length, timbre, rng)
        n = min(len(note), count - offset)
        signal[offset:offset + n] += gain * note[:n]

    bars = math.ceil((count / SAMPLE_RATE) / (4 * beat))
    motif = [0, 4, 7, 12, 7, 4, 2, 0]
    for bar in range(bars):
        chord = root + (0, 5, 7, 0)[bar % 4]
        origin = bar * 4 * beat
        # Tuba/bass on 1 and 3, alternating root and fifth; offbeats carry harmony.
        for pulse in range(4):
            start = origin + pulse * beat
            if pulse % 2 == 0:
                add(start, chord - 24 + (7 if pulse == 2 else 0), beat * 0.78, 0.17, "brass" if style == "brass_band" else "pluck")
            else:
                for voice, interval in enumerate((0, 4, 7)):
                    add(start + (voice * 0.012 if style == "ukulele" else 0), chord + interval,
                        beat * (0.45 if style == "brass_band" else 1.15), 0.065)
        for eighth, interval in enumerate(motif):
            # A 60/40 swing: the offbeat is delayed, rather than the whole rhythm jittering.
            start = origin + (eighth // 2 + (0.6 if eighth % 2 else 0)) * beat
            length = beat * (0.32 if eighth % 2 else 0.5)
            if eighth == 7 and bar % 4 == 3:
                length = beat * 0.75
            if eighth == 6 and rng.random() < 0.25:
                continue  # breathing room, not a wall of constant notes
            add(start, chord + 12 + interval, max(0.12, length), 0.15)
        if style == "brass_band":
            # Soft brushed-clock percussion, well below the pitched instruments.
            for pulse in range(4):
                start = round((origin + pulse * beat) * SAMPLE_RATE)
                if start < count:
                    n = min(round(0.055 * SAMPLE_RATE), count - start)
                    tick = rng.standard_normal(n) * np.exp(-np.arange(n) / (SAMPLE_RATE * 0.009))
                    signal[start:start + n] += _edges(tick, 0.001, 0.01) * 0.012
    _write_wav(Path(out_wav), _normalize(_edges(signal, attack=0.02, release=min(0.5, count / SAMPLE_RATE / 3))))
    return count / SAMPLE_RATE
