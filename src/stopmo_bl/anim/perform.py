"""Performers and the action library.

A Performer owns a puppet plus its tracks. Actions are small functions that
write keys onto those tracks; `Stage.bake` then samples every exposure, adds
the idle layer and the animator's-hand jitter, and keys the puppet.

All times are in EXPOSURES (frames at the show's fps, normally 12).
"""
from __future__ import annotations

import math
import random

from mathutils import Matrix, Vector

from ..archetypes.biped import REST
from .track import Track, add_poses, jitter

# ---------------------------------------------------------------- presets ----
# arm targets are (out, forward, up) in arm lengths from the shoulder
GESTURES = {
    "point": {"arm.at": (0.2, 0.92, 0.12), "arm.elbow": (0.6, -0.3, -0.6), "spine.pitch": 4},
    "present": {"arm.at": (0.9, 0.4, -0.1), "arm.elbow": (0.4, -0.6, -0.6), "head.roll": 4},
    "think": {"arm.at": (-0.26, 0.86, 0.06), "arm.elbow": (0.5, 0.1, -1.0), "arm.hand": 40, "head.roll": 7, "gaze": (12, 14), "brows.raise": 0.5},
    "wave": {"arm.at": (0.7, 0.25, 0.82), "arm.elbow": (1.0, -0.2, -0.3), "head.roll": 6},
    "facepalm": {"arm.at": (-0.12, 0.74, 0.68), "arm.elbow": (1.0, -0.4, -0.3), "arm.hand": 55, "head.pitch": 30, "spine.pitch": 8, "lids": "closed"},
    "raise": {"arm.at": (0.35, 0.3, 0.95), "arm.elbow": (0.8, -0.3, 0.0)},
    "beat": {"arm.at": (0.35, 0.6, -0.15), "arm.elbow": (0.6, -0.5, -0.6)},
    # two-handed (both arms take the same target)
    "hips": {"arms.at": (0.48, 0.02, -0.52), "arms.elbow": (1.0, -0.5, 0.1)},
    "shrug": {"arms.at": (0.78, 0.3, -0.22), "arms.elbow": (0.6, -0.6, -0.7), "head.roll": 8, "brows.raise": 0.8},
    "cheer": {"arms.at": (0.45, 0.15, 1.0), "arms.elbow": (1.0, -0.2, 0.0), "lids": "wide"},
    "clasp": {"arms.at": (-0.05, 0.55, -0.1), "arms.elbow": (0.9, -0.2, -0.5)},
    "rest": {},
}
EMOTES = {
    "neutral": {"brows.raise": 0.0, "brows.tilt": 0.0, "lids": "open", "mouth": "neutral"},
    "happy": {"brows.raise": 0.35, "brows.tilt": 0.0, "lids": "open", "mouth": "smile"},
    "delighted": {"brows.raise": 0.55, "brows.tilt": 0.0, "lids": "open", "mouth": "grin"},
    "sad": {"brows.raise": 0.2, "brows.tilt": -18.0, "lids": "half", "mouth": "frown"},
    "angry": {"brows.raise": -0.35, "brows.tilt": 20.0, "lids": "open", "mouth": "frown"},
    "surprised": {"brows.raise": 1.0, "brows.tilt": 0.0, "lids": "wide", "mouth": "oh"},
    "shocked": {"brows.raise": 1.1, "brows.tilt": -6.0, "lids": "wide", "mouth": "gasp"},
    "worried": {"brows.raise": 0.45, "brows.tilt": -14.0, "lids": "open", "mouth": "neutral"},
    "sleepy": {"brows.raise": -0.2, "brows.tilt": 0.0, "lids": "half", "mouth": "neutral"},
    "smug": {"brows.raise": 0.2, "brows.tilt": 8.0, "lids": "half", "mouth": "smile"},
    "skeptical": {"brows.raise": .0, "brows.tilt": 0., "brows.cock": 1., "lids": "half", "mouth": "flat", "gaze": (0.,0.)},
    "deadpan": {"brows.raise": -.35, "brows.tilt": 0., "brows.cock": 0., "lids": "half", "mouth": "flat", "gaze": (0.,0.)},
    "sheepish": {"brows.raise": .30, "brows.tilt": -18., "brows.cock": .0, "lids": "open", "mouth": "small_smile", "gaze": (0.,0.)},
    "guilty": {"brows.raise": .25, "brows.tilt": -20., "brows.cock": .0, "lids": "half", "mouth": "flat", "gaze": (0.,-25.)},
    "proud": {"brows.raise": .65, "brows.tilt": 0., "brows.cock": 0., "lids": "closed", "mouth": "smile", "gaze": (0.,0.)},
}
OPEN_SHAPES = set("CDE")


def _sided(pose: dict, side: str) -> dict:
    """Expand 'arm.*' to one side and 'arms.*' to both."""
    out = {}
    for key, val in pose.items():
        if key.startswith("arm."):
            out[f"arm_{side}." + key[4:]] = val
        elif key.startswith("arms."):
            out["arm_l." + key[5:]] = val
            out["arm_r." + key[5:]] = val
        else:
            out[key] = val
    return out


class Performer:
    def __init__(self, name: str, puppet, *, seed=0, at=(0.0, 0.0), heading=0.0):
        self.name = name
        self.puppet = puppet
        self.track = Track(REST)
        # `at` may carry a height: a small character standing on a table top
        self.place = Track({"pos": (at[0], at[1], at[2] if len(at) > 2 else 0.0), "heading": float(heading)})
        self.speech: list[tuple[int, str]] = []  # absolute (frame, mouth shape)
        self.look: list[tuple[int, object]] = []  # (frame, target or None)
        self.held: list[tuple[int, object, str]] = []  # (frame, prop or None, side)
        self.rng = random.Random(f"{name}/{seed}")
        self.seed = seed
        self._mouth = None
        self._blinks: set[int] = set()
        self._jitter_state: dict = {}

    # ------------------------------------------------------------ helpers ----
    @property
    def H(self) -> float:
        return self.puppet.H

    def matrix(self, frame: float) -> Matrix:
        pos = self.place.value("pos", frame)
        heading = self.place.value("heading", frame)
        return Matrix.Translation(Vector(pos)) @ Matrix.Rotation(math.radians(heading), 4, "Z")

    def head_point(self, frame: float) -> Vector:
        """World position of the middle of the face (eye line) on an exposure."""
        hips = self.track.value("hips.at", frame) or (0, 0, 0)
        face = self.puppet.face
        local = Vector((face.center.x, face.center.y - face.radii.y * 0.5, face.center.z + face.radii.z * 0.15))
        return self.matrix(frame) @ (local + Vector((hips[0], -hips[1], hips[2])) * self.H)

    # ------------------------------------------------------------ actions ----
    def gesture(self, start: int, name: str, *, side="r", hold=10, into=3, out=5, ease="snap") -> int:
        """Pop into a named gesture, hold it, relax back to rest. Returns the end frame."""
        pose = _sided(GESTURES[name], side)
        names = list(pose)
        self.track.hold(start, names)
        self.track.key(start + into, pose, ease)
        self.track.key(start + into + hold, pose, "linear")
        if out:
            self.track.key(start + into + hold + out, {n: REST[n] for n in names}, "inout")
        return start + into + hold + out

    def pose(self, start: int, pose: dict, *, into=4, ease="inout") -> int:
        """Move to an explicit pose and stay there."""
        self.track.hold(start, list(pose))
        self.track.key(start + into, pose, ease)
        return start + into

    def emote(self, start: int, name: str, *, into=2) -> int:
        # Every mood resets asymmetry/gaze; skeptical must not leak into neutral.
        pose = {"brows.cock": 0., "gaze": (0.,0.), **EMOTES[name]}
        self.track.hold(start, [k for k in pose if k not in ("lids", "mouth")])
        self.track.key(start + into, pose, "snap")
        return start + into

    def wave(self, start: int, *, side="r", waves=3) -> int:
        base = _sided(GESTURES["wave"], side)
        key = f"arm_{side}.at"
        self.track.hold(start, list(base))
        self.track.key(start + 3, base, "snap")
        f = start + 3
        for i in range(waves * 2):
            f += 2
            out = 0.5 if i % 2 == 0 else 0.88
            self.track.key(f, {key: (out, 0.25, 0.84)}, "inout")
        self.track.key(f + 2, base, "inout")
        self.track.key(f + 7, {n: REST[n] for n in base}, "inout")
        return f + 7

    def nod(self, start: int, *, times=2, amount=14.0) -> int:
        self.track.hold(start, ["head.pitch"])
        f = start
        for _ in range(times):
            self.track.key(f + 2, {"head.pitch": amount}, "out")
            self.track.key(f + 4, {"head.pitch": -3.0}, "inout")
            f += 4
        self.track.key(f + 2, {"head.pitch": 0.0}, "inout")
        return f + 2

    def shake(self, start: int, *, times=2, amount=22.0) -> int:
        self.track.hold(start, ["head.yaw"])
        f = start
        for _ in range(times):
            self.track.key(f + 2, {"head.yaw": amount}, "inout")
            self.track.key(f + 4, {"head.yaw": -amount}, "inout")
            f += 4
        self.track.key(f + 2, {"head.yaw": 0.0}, "inout")
        return f + 2

    def hop(self, start: int, *, height=0.14) -> int:
        """Anticipate, jump, land with a squash."""
        names = ["hips.at", "leg_l.at", "leg_r.at", "spine.pitch"]
        self.track.hold(start, names)
        self.track.key(start + 2, {"hips.at": (0, 0, -0.06), "spine.pitch": 10}, "out")
        up = {"hips.at": (0, 0, height), "leg_l.at": (0, 0, height * 0.8), "leg_r.at": (0, 0, height * 0.8), "spine.pitch": -4}
        self.track.key(start + 4, up, "out")
        self.track.key(start + 6, {"hips.at": (0, 0, -0.05), "leg_l.at": (0, 0, 0), "leg_r.at": (0, 0, 0), "spine.pitch": 8}, "in")
        self.track.key(start + 9, {"hips.at": (0, 0, 0), "spine.pitch": 0}, "snap")
        return start + 9

    def lean(self, start: int, *, pitch=12.0, into=4) -> int:
        self.track.hold(start, ["spine.pitch"])
        self.track.key(start + into, {"spine.pitch": pitch}, "inout")
        return start + into

    def _accent(self, start: int, poses: list[tuple[int, dict]], end: int) -> int:
        """Temporary action with exposure offsets; restore only channels it touched."""
        names = {key for _, pose in poses for key in pose}
        before = {key: self.track.value(key, start) for key in names}
        if "mouth" in before and not before["mouth"]:
            before["mouth"] = self.puppet.spec.get("mouth",{}).get("rest","neutral")
        self.track.hold(start, list(names))
        for offset, pose in poses:
            self.track.key(start + offset, pose, "inout")
        self.track.key(start + end, before, "inout")
        return start + end

    def startle(self, start: int) -> int:
        """Snap back on planted heels, fling arms and widen lids, then recover."""
        recoil = _sided({"arms.at": (.85,.10,.35), "arms.elbow": (.9,-.1,-.3),
                         "hips.at": (0,-.025,-.025), "spine.pitch": -16.,
                         "head.pitch": -10., "lids": "wide", "brows.raise": 1.}, "r")
        return self._accent(start, [(1,recoil),(3,recoil),(6,{"spine.pitch": 5.,"head.pitch": 4.})], 10)

    def double_take(self, start: int, target, *, stage) -> int:
        """Look away first; snap back at target with a two-exposure overshoot."""
        self.look_at(start, None)
        d = self.matrix(start).inverted() @ stage.point(target, start) - self.matrix(start).inverted() @ self.head_point(start)
        yaw = max(-60., min(60., math.degrees(math.atan2(d.x,-d.y))))
        away = -30. if yaw >= 0 else 30.
        self.track.hold(start, ["head.yaw","gaze"])
        self.track.key(start+2, {"head.yaw": away, "gaze": (away*.3,0.)}, "out")
        self.track.key(start+4, {"head.yaw": away, "gaze": (away*.3,0.)}, "linear")
        self.track.key(start+5, {"head.yaw": yaw*.72 + math.copysign(7,yaw or 1),
                                "gaze": (yaw*.28,0.)}, "linear")
        self.track.key(start+7, {"head.yaw": yaw*.62, "gaze": (yaw*.38,0.)}, "inout")
        # Hand over to the normal three-exposure look blend without an extra
        # dip away from the target on that first following exposure.
        for offset,remaining in ((8,2/3),(9,1/3),(10,0.)):
            self.track.key(start+offset,{"head.yaw":yaw*.62*remaining,
                                        "gaze":(yaw*.38*remaining,0.)},"linear")
        self.look_at(start+8, target)
        return start+10

    def shifty(self, start: int, *, times=3) -> int:
        """Dart only the eyes left/right, finishing at their prior gaze."""
        poses = [(2*i+1, {"gaze": (30. if i%2 == 0 else -30.,-3.)})
                 for i in range(max(1,int(times))*2)]
        return self._accent(start,poses,max(1,int(times))*4+2)

    def slump(self, start: int) -> int:
        """Droop from the spine with hanging arms; persists until another pose."""
        return self.pose(start,_sided({"spine.pitch": 23.,"head.pitch": 25.,
                                       "arms.at": (.12,.05,-.97), "arms.reach": 0.}, "r"),into=6)

    def tremble(self, start: int, *, frames=12) -> int:
        """Deterministic alternating little shudders; feet remain planted."""
        frames = max(2,int(frames))
        poses = [(i,{"head.roll": 2.5*(-1)**i,"spine.roll": 1.5*(-1)**i,
                     "arm_l.at": (.28+.025*(-1)**i,.08,-.90),
                     "arm_r.at": (.28-.025*(-1)**i,.08,-.90)}) for i in range(1,frames)]
        return self._accent(start,poses,frames)

    def chew(self, start: int, *, frames=12) -> int:
        """Closed-mouth replacement chewing plus a slight cheek/head bob."""
        frames = max(2,int(frames))
        pitch = self.track.value("head.pitch",start)
        poses = [(i,{"mouth": "chew_l" if (i//2)%2 == 0 else "chew_r",
                     "head.pitch": pitch + (2. if (i//2)%2 == 0 else -1.),
                     "head.roll": 1.2*(-1)**(i//2)}) for i in range(1,frames)]
        return self._accent(start,poses,frames)

    def sip(self, start: int, *, frames=12, side="r") -> int:
        """Raise holding hand to the lips, tip head back, hold frames, lower."""
        face = self.puppet.face
        mouth = face.surface_at(face.mouth_anchor.x,face.mouth_anchor.z)
        # Wrist is behind the grip; keep cup just in front of the closed mouth.
        target = self.matrix(start) @ (mouth + Vector((0,-.018,-.010)))
        pose = {f"arm_{side}.reach": 1., f"arm_{side}.world": tuple(target),
                "head.pitch": -9., "mouth": "flat"}
        frames = max(1,int(frames))
        return self._accent(start,[(5,pose),(5+frames,pose)],10+frames)

    def peer(self, start: int, target=None) -> int:
        """Lean toward a target from the waist; hold the inquisitive pose."""
        if target is not None:
            self.look_at(start,target)
        return self.pose(start,{"spine.pitch": 18.,"head.pitch": -8.,"hips.at": (0,.015,-.015)},into=4)

    def look_at(self, start: int, target) -> None:
        """Turn head and eyes toward a target (performer, prop, point) or None to release."""
        self.look.append((start, target))
        self.look.sort(key=lambda item: item[0])

    def turn(self, start: int, heading: float, *, frames=5) -> int:
        self.place.hold(start, ["heading"])
        self.place.key(start + frames, {"heading": float(heading)}, "inout")
        return start + frames

    def face(self, start: int, point, *, frames=5) -> int:
        pos = Vector(self.place.value("pos", start))
        d = Vector(point[:2]) - pos.xy
        heading = math.degrees(math.atan2(d.x, -d.y))
        return self.turn(start, heading, frames=frames)

    def walk_to(self, start: int, target, *, step=0.085, step_frames=4, turn=True) -> int:
        """Walk in a straight line to (x, y). Feet plant without sliding; body bobs; arms swing."""
        pos = Vector(self.place.value("pos", start))
        goal = Vector((target[0], target[1], pos.z))  # stay on the surface it is standing on
        delta = goal - pos
        dist = delta.length
        if dist < 1e-4:
            return start
        f = start
        if turn:
            cur = self.place.value("heading", start)
            heading = math.degrees(math.atan2(delta.x, -delta.y))
            heading = cur + ((heading - cur + 180) % 360 - 180)  # shortest way round
            if abs(heading - cur) > 2:
                f = self.turn(f, heading, frames=max(3, int(abs(heading - cur) / 25)))
        steps = max(1, round(dist / step))
        stride = dist / steps / self.H  # body heights per step
        total = steps * step_frames
        self.place.hold(f, ["pos"])
        self.place.key(f + total, {"pos": tuple(goal)}, "linear")
        names = ["leg_l.at", "leg_r.at", "hips.at", "arm_l.at", "arm_r.at", "spine.yaw", "spine.pitch"]
        self.track.hold(f, names)
        rest_arm = REST["arm_l.at"]
        for i in range(total + 1):
            cyc = i / step_frames  # one unit per step
            pose = {}
            for side, lead in (("l", 0), ("r", 1)):
                ph = (cyc + lead) % 2.0  # 0..1 stance, 1..2 swing
                if ph < 1.0:
                    fwd, lift = stride * (0.5 - ph), 0.0
                else:
                    s = ph - 1.0
                    fwd, lift = stride * (-0.5 + s), 0.05 * math.sin(math.pi * s)
                ramp = min(1.0, i / step_frames, (total - i) / step_frames)  # start and stop feet together
                pose[f"leg_{side}.at"] = (0.0, fwd * ramp, lift * ramp)
                swing = -fwd * ramp * 1.6  # arms counter the legs
                pose[f"arm_{side}.at"] = (rest_arm[0], rest_arm[1] + swing, rest_arm[2] + abs(swing) * 0.15)
            bob = abs(math.sin(math.pi * cyc))
            ramp = min(1.0, i / step_frames, (total - i) / step_frames)
            pose["hips.at"] = (0.0, 0.0, (-0.022 + 0.02 * bob) * ramp)
            pose["spine.yaw"] = 6.0 * math.sin(math.pi * cyc) * ramp
            pose["spine.pitch"] = 5.0 * ramp
            self.track.key(f + i, pose, "linear")
        return f + total

    def reach(self, start: int, target, *, side="r", into=5, hold=6, release=True) -> int:
        """Reach a hand to a world point (or anything with a world position)."""
        point = tuple(_point(target, start + into))
        keys = [f"arm_{side}.reach", f"arm_{side}.world", "spine.pitch"]
        self.track.hold(start, keys)
        self.track.key(start, {f"arm_{side}.world": point}, "step")
        self.track.key(start + into, {f"arm_{side}.reach": 1.0, f"arm_{side}.world": point, "spine.pitch": 10.0}, "inout")
        self.track.key(start + into + hold, {f"arm_{side}.reach": 1.0, "spine.pitch": 10.0}, "linear")
        if release:
            self.track.key(start + into + hold + 5, {f"arm_{side}.reach": 0.0, "spine.pitch": 0.0}, "inout")
            return start + into + hold + 5
        return start + into + hold

    def hold_prop(self, frame: int, prop, side="r") -> None:
        """From `frame`, `prop` rides in the hand; pass None to let go (it stays where it is)."""
        self.held.append((frame, prop, side))
        self.held.sort(key=lambda item: item[0])

    def say(self, start: int, cues, *, accents=True) -> int:
        """Lip-sync from quantized cues [(frame, shape), ...] relative to `start`, plus head accents."""
        if not cues:
            return start
        end = start + cues[-1][0]
        self.speech = [c for c in self.speech if c[0] < start] + [(start + f, s) for f, s in cues]
        self.speech.sort(key=lambda item: item[0])
        if accents:
            self.track.hold(start, ["head.pitch", "brows.raise"])
            last = -10
            for f, shape in cues:
                if shape in OPEN_SHAPES and f - last >= 5 and start + f + 3 < end:
                    amt = self.rng.uniform(3.0, 7.0)
                    self.track.key(start + f, {"head.pitch": -amt * 0.5, "brows.raise": self.rng.uniform(0.2, 0.6)}, "out")
                    self.track.key(start + f + 2, {"head.pitch": amt, "brows.raise": 0.1}, "inout")
                    last = f
            self.track.key(end + 2, {"head.pitch": 0.0, "brows.raise": 0.0}, "inout")
        return end

    # --------------------------------------------------------------- bake ----
    def hop_to(self, start: int, target, *, hops=None, hop=0.5, height=0.3, frames=4, turn=True) -> int:
        """Travel in little hops, the way a toy figure is walked across a table. `hop` is the length of
        one hop and `height` its rise, both in body heights; a target with a z hops up or down to it."""
        pos = Vector(self.place.value("pos", start))
        goal = Vector((target[0], target[1], target[2] if len(target) > 2 else pos.z))
        flat = Vector((goal.x - pos.x, goal.y - pos.y))
        if (goal - pos).length < 1e-4:
            return start
        f = start
        if turn and flat.length > 1e-3:
            cur = self.place.value("heading", start)
            heading = math.degrees(math.atan2(flat.x, -flat.y))
            heading = cur + ((heading - cur + 180) % 360 - 180)
            if abs(heading - cur) > 2:
                f = self.turn(f, heading, frames=max(2, int(abs(heading - cur) / 30)))
        n = hops or max(1, round(flat.length / (hop * self.H)))
        self.place.hold(f, ["pos"])
        self.track.hold(f, ["hips.at", "spine.pitch"])
        for i in range(n):
            a, b = pos.lerp(goal, i / n), pos.lerp(goal, (i + 1) / n)
            self.track.key(f + 1, {"hips.at": (0, 0, -0.035), "spine.pitch": 7}, "out")  # crouch
            self.place.key(f + 1, {"pos": tuple(a)}, "linear")  # planted until it leaves the ground
            for k in range(1, frames + 1):
                t = k / frames
                p = a.lerp(b, t)
                p.z += height * self.H * 4 * t * (1 - t)
                self.place.key(f + 1 + k, {"pos": tuple(p)}, "linear")
            self.track.key(f + 2, {"hips.at": (0, 0, 0.0), "spine.pitch": -5}, "out")
            self.track.key(f + 1 + frames, {"hips.at": (0, 0, -0.04), "spine.pitch": 6}, "in")  # land
            self.track.key(f + 2 + frames, {"hips.at": (0, 0, 0), "spine.pitch": 0}, "snap")
            f += 2 + frames
        return f

    def plan_blinks(self, first: int, last: int, fps: float) -> None:
        f = first + self.rng.randint(int(fps * 0.8), int(fps * 2.5))
        while f < last:
            self._blinks.update((f, f + 1))
            if self.rng.random() < 0.15:  # the odd double blink
                self._blinks.update((f + 3, f + 4))
            f += self.rng.randint(int(fps * 1.8), int(fps * 4.5))

    def _idle(self, frame: int, fps: float) -> dict:
        ph = self.rng_phase
        t = frame / fps
        breathe = math.sin(t * 2 * math.pi / 3.4 + ph)
        sway = math.sin(t * 2 * math.pi / 7.3 + ph * 2)
        return {
            "spine.pitch": 0.9 * breathe,
            "hips.at": (0.004 * sway, 0.0, 0.0025 * breathe),
            "spine.roll": 0.8 * sway,
            "head.roll": -0.6 * sway,
            "arm_l.at": (0.01 * breathe, 0.0, 0.0),
            "arm_r.at": (0.01 * breathe, 0.0, 0.0),
        }

    def mouth_at(self, frame: int):
        shape = None
        for f, s in self.speech:
            if f <= frame:
                shape = s
            else:
                break
        return shape

    def bake_frame(self, frame: int, fps: float, stage, wobble: float) -> None:
        if not hasattr(self, "rng_phase"):
            self.rng_phase = self.rng.uniform(0, 6.28)
        pose = self.track.sample(frame)
        # look-at: split between head turn and eye gaze
        target = None
        since = 0
        for f, tgt in self.look:
            if f <= frame:
                target, since = tgt, f
        if target is not None:
            blend = min(1.0, (frame - since + 1) / 3.0)
            inv = self.matrix(frame).inverted()
            d = inv @ _point(stage.resolve(target), frame) - inv @ self.head_point(frame)
            yaw = math.degrees(math.atan2(d.x, -d.y)) - pose["spine.yaw"]
            pitch = math.degrees(math.atan2(d.z, max(Vector((d.x, d.y)).length, 1e-4)))
            yaw = max(-75.0, min(75.0, yaw)) * blend
            pitch = max(-35.0, min(35.0, pitch)) * blend
            pose["head.yaw"] += yaw * 0.62
            pose["head.pitch"] += -pitch * 0.55
            gy, gp = pose["gaze"]
            pose["gaze"] = (gy + yaw * 0.38, gp + pitch * 0.45)
        # hand error only where the pose changed this exposure; then the smooth idle layer on top
        pose = jitter(pose, f"{self.name}/{self.seed}/{frame}", wobble, self._jitter_state)
        amount = getattr(self, "idle_amount", 1.0)
        if amount:
            idle = self._idle(frame, fps)
            pose = add_poses(pose, {k: tuple(c * amount for c in v) if isinstance(v, tuple) else v * amount for k, v in idle.items()})
        if frame in self._blinks and pose.get("lids") == "open":
            pose["lids"] = "closed"
        spoken = self.mouth_at(frame)
        expression = pose.get("mouth")
        if expression and expression != self.puppet.face.expression:
            self.puppet.face.expression = expression  # mood for the speech shapes
            self._mouth = None
        mouth = spoken if spoken and spoken != "X" else (expression or "X")
        pose["mouth"] = mouth if mouth != self._mouth else None
        if pose["mouth"]:
            self._mouth = mouth
        pos = self.place.value("pos", frame)
        self.puppet.place(pos, self.place.value("heading", frame), frame)
        self.puppet.pose(pose, frame)
        self._carry(frame, pose)

    def _carry(self, frame: int, pose: dict) -> None:
        holding = {}
        for f, prop, side in self.held:
            if f <= frame:
                holding[side] = (prop, f)
        for side, (prop, since) in holding.items():
            if prop is None:
                continue
            sk = self.puppet.skel
            solved = sk.last_solved
            rot, head = solved[f"hand_{side}"]
            grip = head + rot.col[1] * sk.length[f"hand_{side}"] * 0.75
            world = self.matrix(frame) @ grip
            offset = prop.rotation_euler.to_matrix() @ Vector(prop.get("grip", (0.0, 0.0, 0.0)))
            prop.location = world - offset
            prop.keyframe_insert("location", frame=frame)


def _point(target, frame) -> Vector:
    if hasattr(target, "at_frame"):
        return target.at_frame(frame)
    if isinstance(target, Performer):
        return target.head_point(frame)
    if hasattr(target, "matrix_world"):
        return target.matrix_world.translation.copy()
    return Vector(target)
