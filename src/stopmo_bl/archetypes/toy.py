"""Toy figure: a chunky vinyl-style character, about half of it head. Same pose keys as the biped
(it is one underneath, so every action and gesture works), but it is built from smooth simple solids:
a pear body with no visible legs, stub arms ending in round hands, and a face that is all replacement
decals: tall oval eyes with a highlight, blush spots and a small line mouth. It travels by hopping.

Spec keys (all optional; colours are hex):
    height                     metres
    body, skin, hands          body colour, face/head colour, hand colour (default: skin)
    head: {shape: ball|box, size: [x, y, z] in body heights (half sizes), color, screen: colour}
                               (screen: a dark face panel on the front, as on the helper robots)
    ears: colour               flat round ear pieces on the sides of the head
    helmet: {color, trim, ears, goggles, lens, strap}   a hood with a face opening; goggles on the brow
    eyes: {kind: oval|happy, color, spread, height, size}     (on a screen, give a light colour)
    cheeks: colour, or false
    mouth: {rest: smile, height, color}
    scarf: colour              a thick ring round the neck with a short tail
    antenna: colour            a stalk with a ball on top of the head
    decor: [...]               as for the biped

Extra pose value: lids "happy" (eyes squeezed into arcs). Brow keys are accepted and ignored.
"""
from __future__ import annotations

import math

import bmesh
from mathutils import Matrix, Vector

from .. import util
from ..parts.face import Face
from .biped import Biped

PROPORTIONS = {
    "hip_z": 0.10, "hip_x": 0.07, "ankle_z": 0.03, "foot": 0.06,
    "waist": 0.10, "spine": 0.10, "chest": 0.10, "neck": 0.02, "head": 0.58,
    "shoulder_x": 0.185, "shoulder_drop": 0.04,
    "upper_arm": 0.11, "forearm": 0.10, "hand": 0.05, "arm_r": 0.045,
    "belly_size": (0.19, 0.17, 0.19), "chest_size": (0.15, 0.13, 0.12),
}
# pose / lip-sync mouth name -> replacement mouth
MOUTH_OF = {"neutral": "small_smile", "gasp": "wide", "chew_l": "small_smile", "chew_r": "small_smile",
            "B": "open_s", "C": "open", "D": "wide", "E": "open", "F": "oh", "G": "open_s", "H": "open"}
CLOSED = ("smile", "small_smile", "flat", "frown")
DARK = "#2E2019"


def _cut(obj, drop) -> None:
    """Delete the vertices for which drop(co) is true."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if drop(v.co)], context="VERTS")
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()


def _aim(obj, center: Vector, normal: Vector) -> None:
    """Move a mesh built round the origin with +Z as its axis so that axis points along `normal`."""
    obj.data.transform(Matrix.Translation(center) @ Vector((0, 0, 1)).rotation_difference(normal.normalized()).to_matrix().to_4x4())
    obj.data.update()


def _ring(name, center: Vector, normal: Vector, radius: float, thick: float, count=20):
    turn = Vector((0, 0, 1)).rotation_difference(normal.normalized())
    pts = [center + turn @ Vector((radius * math.cos(a), radius * math.sin(a), 0)) for a in
           [2 * math.pi * i / count for i in range(count + 1)]]
    return util.tube(name, pts, [thick] * len(pts), segments=10)


class Toy(Biped):
    archetype = "toy"

    def __init__(self, name: str, spec: dict):
        super().__init__(name, {**spec, "proportions": {**PROPORTIONS, **spec.get("proportions", {})}})

    # ------------------------------------------------------------- build ----
    def _build_body(self):
        H, P, sk, spec = self.H, self.prop, self.skel, self.spec
        body_color = spec.get("body", "#D97B3F")
        skin = spec.get("skin", "#F9E6CF")
        belly = util.ellipsoid("belly", Vector(P["belly_size"]) * H, (0, 0, P["belly_size"][2] * H * 0.9), subdiv=4)
        chest = util.ellipsoid("chest", Vector(P["chest_size"]) * H, (0, 0, sk.rest_head["chest"].z + 0.03 * H), subdiv=4)
        body = util.join([belly, chest], f"{self.name}_body")
        util.remesh(body, voxel=H / 100, smooth_iters=12, smooth_factor=0.7)
        for v in body.data.vertices:  # a flat base, in contact with whatever it stands on
            v.co.z = max(v.co.z, 0.0)
        self.finish(body, "cloth", body_color, bones=["hips", "spine", "chest"], blend=0.35)
        for side in ("l", "r"):
            a, b, c = sk.rest_head[f"upper_arm_{side}"], sk.rest_head[f"forearm_{side}"], sk.rest_head[f"hand_{side}"]
            pts = [a.lerp(b, i / 4) for i in range(4)] + [b.lerp(c, i / 4) for i in range(5)]
            r0 = P["arm_r"] * H
            arm = util.tube(f"{self.name}_arm_{side}", pts, [r0 * (1.0 - 0.12 * i / (len(pts) - 1)) for i in range(len(pts))], segments=16)
            self.finish(arm, "cloth", spec.get("sleeves", body_color), bones=[f"upper_arm_{side}", f"forearm_{side}"], blend=0.9)
            d = (c - b).normalized()
            hand = util.ellipsoid(f"{self.name}_hand_{side}", (r0 * 1.08,) * 3, c + d * r0 * 0.5, subdiv=3)
            self.finish(hand, "skin", spec.get("hands", skin), bone=f"hand_{side}")
        if spec.get("scarf"):
            z = sk.rest_head["neck"].z + 0.01 * H
            loop = [Vector((0.2 * H * math.cos(t), 0.175 * H * math.sin(t), z + 0.008 * H * math.sin(2 * t))) for t in
                    [2 * math.pi * i / 24 for i in range(25)]]
            ring = util.tube(f"{self.name}_scarf", loop, [0.05 * H] * len(loop), segments=14)
            tail = util.tube(f"{self.name}_scarf_tail", [Vector((0.12 * H, -0.16 * H, z - 0.01 * H)), Vector((0.15 * H, -0.2 * H, z - 0.08 * H)),
                                                         Vector((0.14 * H, -0.2 * H, z - 0.15 * H))], [0.045 * H, 0.042 * H, 0.034 * H], segments=12)
            self.finish(util.join([ring, tail], f"{self.name}_scarf"), "knit", spec["scarf"], bone="chest")

    def _build_head(self):
        H, sk, spec = self.H, self.skel, self.spec
        hs = spec.get("head", {})
        box = hs.get("shape", "ball") == "box"
        radii = Vector(hs.get("size", (0.26, 0.2, 0.2) if box else (0.3, 0.27, 0.27))) * H
        center = Vector(sk.rest_head["head"]) + Vector((0, 0, radii.z * 0.9))
        if box:
            head = util.rounded_box(f"{self.name}_head", radii * 2, center, bevel=0.3, segments=8)
        else:
            head = util.ellipsoid(f"{self.name}_head", radii, center, subdiv=5)
        self.finish(head, "skin", hs.get("color", spec.get("skin", "#F9E6CF")), bone="head")
        surface = head
        if hs.get("screen"):  # the face is drawn on a dark panel set into the front
            surface = util.rounded_box(f"{self.name}_screen", (radii.x * 1.5, radii.y * 0.3, radii.z * 1.2),
                                       center + Vector((0, -radii.y * 0.9, 0)), bevel=0.45, segments=6)
        self.face = face = Face(self, surface, center, radii)
        self.socket("face", "head", center)
        face.expression = spec.get("mouth", {}).get("rest", "smile")
        if surface is not head:
            self.stick(surface, "face", "pupil", hs["screen"])
        if spec.get("ears"):
            for s in (1, -1):
                ear = util.cylinder(f"{self.name}_earpiece_{s}", 0.42 * radii.z, 0.16 * radii.x, (0, 0, 0), segments=28)
                _aim(ear, center + Vector((s * radii.x * 1.02, 0, 0)), Vector((s, 0, 0)))
                util.shade_smooth(ear)
                self.stick(ear, "face", "cloth", spec["ears"])
        rx, ry, rz = radii
        helmet = spec.get("helmet")
        if helmet:
            k, wx, wz, wh = 1.08, 0.78, -0.2, 0.6   # shell size; face opening half-width, centre height, half-height (head radii)
            color, trim = helmet.get("color", "#E08A4F"), helmet.get("trim", "#B8683A")
            shell = util.ellipsoid(f"{self.name}_helmet", radii * k, center, subdiv=5)
            _cut(shell, lambda co: co.y < center.y and ((co.x - center.x) / rx / wx) ** 2 + (((co.z - center.z) / rz - wz) / wh) ** 2 < 1.0)
            self.stick(shell, "face", "cloth", color)

            def on_shell(ax, az, proud=0.0):
                uy = -math.sqrt(max(0.0, 1.0 - (ax / k) ** 2 - (az / k) ** 2)) * (k + proud)
                return center + Vector((ax * rx, uy * ry, az * rz))

            rim = [on_shell(wx * math.cos(t), wz + wh * math.sin(t)) for t in [2 * math.pi * i / 48 for i in range(49)]]
            self.stick(util.tube(f"{self.name}_helmet_rim", rim, [0.045 * rx] * len(rim), segments=10), "face", "cloth", trim)
            if helmet.get("ears", True):
                for s in (1, -1):
                    ear = util.ellipsoid(f"{self.name}_ear_{s}", (0.1 * rx, 0.3 * ry, 0.3 * rz), center + Vector((s * rx * k * 0.99, 0, -0.12 * rz)), subdiv=3)
                    self.stick(ear, "face", "cloth", color)
                    cup = _ring(f"{self.name}_ear_rim_{s}", center + Vector((s * rx * k * 1.03, 0, -0.12 * rz)), Vector((s, 0, 0)), 0.26 * rz, 0.04 * rx)
                    self.stick(cup, "face", "cloth", helmet.get("ear_rim", "#F7EEDD"))
            if helmet.get("goggles", True):
                strap, frame_color, lens = helmet.get("strap", "#7A4E36"), helmet.get("goggles_color", "#5C947F"), helmet.get("lens", "#A9D6CC")
                level = [center + Vector((rx * k * 0.86 * math.cos(t), ry * k * 0.86 * math.sin(t), 0.58 * rz)) for t in
                         [2 * math.pi * i / 32 for i in range(33)]]
                self.stick(util.tube(f"{self.name}_strap", level, [0.04 * rx] * len(level), segments=8), "face", "cloth", strap)
                for s in (1, -1):
                    at = on_shell(s * 0.27, 0.66, proud=0.03)
                    normal = Vector(((at.x - center.x) / rx, (at.y - center.y) / ry, (at.z - center.z) / rz))
                    self.stick(_ring(f"{self.name}_goggle_{s}", at, normal, 0.2 * rx, 0.05 * rx), "face", "cloth", frame_color)
                    glass = util.ellipsoid(f"{self.name}_lens_{s}", (0.185 * rx, 0.185 * rx, 0.05 * rx), (0, 0, 0), subdiv=3)
                    _aim(glass, at, normal)
                    self.stick(glass, "face", "pupil", lens)
        if spec.get("antenna"):
            top = center + Vector((0, 0, radii.z * (1.08 if helmet else 1.0)))
            stalk = util.tube(f"{self.name}_stalk", [top - Vector((0, 0, 0.02 * H)), top + Vector((0, 0, 0.1 * H))], [0.012 * H, 0.012 * H], segments=10)
            self.stick(stalk, "face", "metal", "#B9AFA0")
            self.stick(util.ellipsoid(f"{self.name}_bobble", (0.036 * H,) * 3, top + Vector((0, 0, 0.12 * H)), subdiv=3), "face", "cloth", spec["antenna"])
        self._build_face()
        self._build_decor()

    def _line(self, name, pts, radius, anchor):
        obj = util.tube(name, [Vector((x, -radius * 0.45, z)) for x, z in pts], [radius] * len(pts), segments=8)
        self.face.wrap_object(obj, anchor)
        return obj

    def _blob(self, name, rx, rz, anchor, thick, lift=0.0, flat_top=False):
        obj = util.ellipsoid(name, (rx, thick, rz), (0, -lift, 0), subdiv=3)
        if flat_top:  # a D on its side: the open, smiling mouth
            for v in obj.data.vertices:
                v.co.z = min(v.co.z, rz * 0.12)
        self.face.wrap_object(obj, anchor)
        return obj

    def _build_face(self):
        spec, face = self.spec, self.face
        rx, rz = face.radii.x, face.radii.z
        eyes = spec.get("eyes", {})
        kind, color = eyes.get("kind", "oval"), eyes.get("color", DARK)
        spread, height, size = eyes.get("spread", 0.3), eyes.get("height", -0.1 if spec.get("helmet") else 0.02), eyes.get("size", 1.0)
        ew, eh, thick, line = 0.075 * rx * size, 0.125 * rz * size, 0.012 * rx, 0.017 * rx
        self.eye_parts = []
        on_screen = bool(spec.get("head", {}).get("screen"))
        variants: dict[str, list] = {v: [] for v in ("open", "wide", "half", "closed", "happy")}
        for s in (1, -1):
            anchor = face.center + Vector((s * spread * rx, 0, height * rz))
            arc = [(ew * 1.15 * math.cos(t), eh * 0.55 * math.sin(t) - eh * 0.2) for t in [math.pi * i / 10 for i in range(11)]]
            shut = [(ew * 1.15 * (i / 5 - 1), -eh * 0.15 * (1 - (i / 5 - 1) ** 2)) for i in range(11)]
            variants["happy"].append(self._line(f"{self.name}_eye_happy_{s}", arc, line, anchor))
            variants["closed"].append(self._line(f"{self.name}_eye_closed_{s}", shut, line, anchor))
            if kind == "happy":  # eyes that are always smiling arcs
                for v in ("open", "wide", "half"):
                    variants[v].append(self._line(f"{self.name}_eye_{v}_{s}", arc, line, anchor))
                continue
            for v, (w, h) in {"open": (1.0, 1.0), "wide": (1.15, 1.18), "half": (1.0, 0.6)}.items():
                variants[v].append(self._blob(f"{self.name}_eye_{v}_{s}", ew * w, eh * h, anchor, thick))
                glint = anchor + Vector((ew * 0.3, 0, eh * h * 0.42))
                variants[v].append(self._blob(f"{self.name}_glint_{v}_{s}", ew * 0.36, ew * 0.36, glint, thick * 0.5, lift=thick))
        for v, objs in variants.items():
            for o in objs:
                glint = "glint" in o.name
                # eyes are glossy beads, except when drawn in a light colour on a screen
                self.stick(o, "face", "mouth" if glint or on_screen else "pupil", "#FFFFFF" if glint else color)
            self.eye_parts += objs
            self.add_swap("eyes", v, objs)
        self.swap("eyes", "open")
        cheeks = spec.get("cheeks", "#F2A590")
        if cheeks:
            for s in (1, -1):
                at = face.center + Vector((s * (spread + 0.2) * rx, 0, (height - 0.24) * rz))
                self.stick(self._blob(f"{self.name}_cheek_{s}", 0.095 * rx, 0.06 * rz, at, 0.006 * rx), "face", "skin", cheeks)
        mouth = spec.get("mouth", {})
        anchor = face.center + Vector((0, 0, mouth.get("height", height - 0.33) * rz))
        mcolor, w = mouth.get("color", color if spec.get("head", {}).get("screen") else "#4A2A22"), 0.2 * rx * mouth.get("width", 1.0)

        def curve(width, depth):
            return [(width * (i / 6 - 1), -depth * (1 - (i / 6 - 1) ** 2) + depth * 0.5) for i in range(13)]

        shapes = {
            "smile": self._line("m", curve(w, 0.07 * rz), line, anchor),
            "small_smile": self._line("m", curve(w * 0.65, 0.04 * rz), line, anchor),
            "flat": self._line("m", curve(w * 0.7, 0.0), line, anchor),
            "frown": self._line("m", curve(w * 0.8, -0.05 * rz), line, anchor),
            "grin": self._blob("m", w * 1.05, 0.11 * rz, anchor + Vector((0, 0, 0.03 * rz)), thick, flat_top=True),
            "open_s": self._blob("m", w * 0.55, 0.035 * rz, anchor, thick),
            "open": self._blob("m", w * 0.6, 0.065 * rz, anchor, thick),
            "wide": self._blob("m", w * 0.7, 0.1 * rz, anchor, thick),
            "oh": self._blob("m", w * 0.32, 0.05 * rz, anchor, thick),
        }
        for name, obj in shapes.items():
            obj.name = f"{self.name}_mouth_{name}"
            self.stick(obj, "face", "mouth", mcolor)
            self.add_swap("mouth", name, [obj])
        self.set_mouth("X")

    # -------------------------------------------------------------- pose ----
    def _pose_face(self, p: dict, frame: int | None) -> None:
        yaw, pitch = p["gaze"]
        shift = (max(-1.0, min(1.0, yaw / 38.0)) * 0.035 * self.face.radii.x, 0.0, max(-1.0, min(1.0, pitch / 28.0)) * 0.03 * self.face.radii.z)
        for obj in self.eye_parts:
            obj.location = shift
            if frame is not None:
                obj.keyframe_insert("location", frame=frame)
        lids = p["lids"] if p["lids"] in self.swaps["eyes"] else "open"
        if self.swap_state.get("eyes") != lids or frame is not None:
            self.swap("eyes", lids, frame)
        if p.get("mouth"):
            self.set_mouth(p["mouth"], frame)

    def set_mouth(self, shape: str, frame: int | None = None) -> None:
        """Show a mouth by expression or lip-sync name; 'X' (rest) and closed lips show the expression."""
        if shape in ("X", "A"):
            shape = MOUTH_OF.get(self.face.expression, self.face.expression)
            if shape not in CLOSED:
                shape = "small_smile" if shape != "oh" else "oh"
        elif shape in MOUTH_OF or shape in self.swaps["mouth"]:
            if len(shape) > 1:
                self.face.expression = shape
            shape = MOUTH_OF.get(shape, shape)
        else:
            raise KeyError(f"{self.name}: no mouth {shape!r}")
        self.swap("mouth", shape, frame)


def build(name: str, spec: dict) -> Toy:
    return Toy(name, spec)
