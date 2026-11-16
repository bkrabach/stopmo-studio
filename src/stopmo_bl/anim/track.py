"""Pose tracks: per-channel keys sampled once per exposure. No bpy in here.

A pose is a flat dict (see archetypes/biped.py). Every channel is keyed
independently, so actions can overlap freely: legs can walk while an arm
points and the mouth talks.

Numbers and tuples interpolate with an ease; strings/None switch on their key.
"""
from __future__ import annotations

import bisect
import math
import random


def _back_out(t: float, s: float = 1.9) -> float:
    t -= 1.0
    return t * t * ((s + 1) * t + s) + 1.0


EASES = {
    "linear": lambda t: t,
    "in": lambda t: t * t,
    "accel": lambda t: t ** 1.7,  # gathering speed, gentler than "in": a camera move that is cut while still speeding up
    "out": lambda t: 1 - (1 - t) * (1 - t),
    "inout": lambda t: t * t * (3 - 2 * t),
    "snap": _back_out,  # fast, overshoots, settles: the classic clay 'pop' into a pose
    "step": lambda t: 0.0 if t < 1.0 else 1.0,
}


def lerp(a, b, t: float):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a + (b - a) * t
    if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
        return tuple(x + (y - x) * t for x, y in zip(a, b))
    return b if t >= 1.0 else a


class Track:
    def __init__(self, defaults: dict | None = None):
        self.defaults = dict(defaults or {})
        self.channels: dict[str, list[tuple[int, object, str]]] = {}

    def key(self, frame: int, pose: dict, ease: str = "inout") -> None:
        """Set channels at `frame`; each eases in from whatever came before."""
        for name, value in pose.items():
            keys = self.channels.setdefault(name, [])
            i = bisect.bisect_left([k[0] for k in keys], frame)
            if i < len(keys) and keys[i][0] == frame:
                keys[i] = (frame, value, ease)
            else:
                keys.insert(i, (frame, value, ease))

    def value(self, name: str, frame: float):
        keys = self.channels.get(name)
        if not keys:
            return self.defaults.get(name)
        frames = [k[0] for k in keys]
        i = bisect.bisect_right(frames, frame)
        if i == 0:
            first = keys[0]
            base = self.defaults.get(name, first[1])
            # ease from the default into the first key over the 4 exposures before it
            if isinstance(first[1], (int, float, tuple, list)) and base is not None:
                t = 1.0 - min(max((first[0] - frame) / 4.0, 0.0), 1.0)
                return lerp(base, first[1], EASES["inout"](t))
            return base
        if i == len(keys):
            return keys[-1][1]
        f0, v0, _ = keys[i - 1]
        f1, v1, ease = keys[i]
        t = (frame - f0) / (f1 - f0)
        if not isinstance(v1, (int, float, tuple, list)) or not isinstance(v0, (int, float, tuple, list)):
            return v0
        return lerp(v0, v1, EASES[ease](t))

    def hold(self, frame: int, names=None) -> None:
        """Pin channels at their current value so the next key starts moving from here."""
        for name in names if names is not None else sorted(set(self.defaults) | set(self.channels)):
            value = self.value(name, frame)
            if value is not None or name in self.channels:
                self.key(frame, {name: value}, "linear")

    def sample(self, frame: float) -> dict:
        names = set(self.defaults) | set(self.channels)
        return {n: self.value(n, frame) for n in names}

    def last_frame(self) -> int:
        return max((keys[-1][0] for keys in self.channels.values() if keys), default=0)


def add_poses(base: dict, extra: dict) -> dict:
    """base + additive offsets (numeric channels only)."""
    out = dict(base)
    for name, off in extra.items():
        cur = out.get(name)
        if off is None or cur is None:
            continue
        if isinstance(cur, (int, float)) and isinstance(off, (int, float)):
            out[name] = cur + off
        elif isinstance(cur, (tuple, list)) and isinstance(off, (tuple, list)):
            out[name] = tuple(c + o for c, o in zip(cur, off))
    return out


# Animator's-hand error per channel at pose_jitter 1.0 (degrees, or fractions of arm length / body height).
JITTER = {
    "head.pitch": 0.5,
    "head.yaw": 0.5,
    "head.roll": 0.35,
    "spine.pitch": 0.3,
    "spine.roll": 0.25,
    "arm_l.at": 0.007,
    "arm_r.at": 0.007,
    "hips.at": 0.0012,
    "brows.raise": 0.04,
    "brows.cock": 0.015,
}


def _moved(a, b, eps: float = 1e-6) -> bool:
    if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
        return any(abs(x - y) > eps for x, y in zip(a, b))
    return abs(a - b) > eps


def jitter(pose: dict, seed: str, amount: float, state: dict | None = None) -> dict:
    """Animator's-hand error: a small random offset on the channels in JITTER.

    A real animator only disturbs the parts that are touched. With `state` (a dict kept by the
    caller across exposures, in order), a channel gets a fresh offset only on exposures where its
    posed value changed; while the pose is held, the last offset is kept, so a still puppet is still.
    Without `state`, every channel is re-randomised on every call.
    """
    if amount <= 0:
        return pose
    r = random.Random(seed)
    out = dict(pose)
    for name, size in JITTER.items():
        cur = out.get(name)
        if not isinstance(cur, (int, float, tuple, list)):
            continue
        # always draw, so one channel holding does not change the numbers the others get
        draw = tuple(r.gauss(0, size * amount) for _ in cur) if isinstance(cur, (tuple, list)) else r.gauss(0, size * amount)
        if state is not None:
            before = state.get(name)
            if before is not None and not _moved(cur, before[0]):
                draw = before[1]
            state[name] = (cur, draw)
        out[name] = tuple(c + d for c, d in zip(cur, draw)) if isinstance(cur, (tuple, list)) else cur + draw
    if "brows.cock" in out:
        out["brows.cock"] = max(-1.0, min(1.0, out["brows.cock"]))
    return out


def seconds_to_frames(seconds: float, fps: float) -> int:
    return int(math.floor(seconds * fps + 0.5))
