"""Figure: a finished, rigid toy model (a figurine) animated the way a solid toy is in stop motion:
it is hopped, turned, tilted and squashed as a whole, and its face is changed by replacement parts.

The model comes from a module under `models/` that has `build() -> root` (an Empty at the centre of
the flat base, facing -Y, with eyes, mouth and brows as separate objects named eye_*, mouth*, brow_*).
Model modules and their imports are trusted executable Python, not passive assets. Inspect them
before use: restricting the selected path is not a sandbox and does not limit what their code can do.
Sibling imports (`import common` or `from . import common`) are supported while building the model.

Spec keys:
    model     "my_cast/hero": a trusted Python module relative to the repository's models/ folder
    height    metres; the model is scaled to it (default: as built)
    mouth     {rest: smile}

It takes the biped's pose keys and uses what a rigid figure can show:
    hips.at                 (left, forward, up) in body heights; down (negative up) squashes it instead
    spine.* and head.*      pitch, roll and yaw tilt and turn the whole figure about its base
    lids                    "closed" / "happy" swap the eyes for closed-eye arcs (blinks)
    brows.raise             lifts the brows a little
    mouth                   expression or lip-sync shape: the built smile, or an open-mouth replacement
Arms, legs and gaze are ignored. It travels with `hop_to`.
"""
from __future__ import annotations

import hashlib
import importlib.util
import math
from pathlib import Path
import re
import sys
from types import ModuleType, SimpleNamespace

import bpy
from mathutils import Euler, Matrix, Vector

from .. import util
from ..puppet import HIDDEN_SCALE, _hold_key
from .biped import REST

MODELS = Path(__file__).resolve().parents[3] / "models"
OPEN = {"B": "open_s", "C": "open", "D": "wide", "E": "open", "F": "oh", "G": "open_s", "H": "open",
        "grin": "grin", "oh": "oh", "gasp": "wide"}
DARK = "#2B1A14"


def _build_model(model: str):
    """Execute a trusted models-relative module without reusing another folder's import cache."""
    if not isinstance(model, str) or not all(part.isidentifier() for part in model.split("/")):
        raise ValueError("model must be a slash-separated Python module path relative to models/")
    root = MODELS.resolve()
    path = (root / (model + ".py")).resolve()
    if not path.is_relative_to(root):
        raise ValueError("model must stay inside models/, including symlink targets")
    if not path.is_file():
        raise FileNotFoundError(f"model not found under models/: {model}")
    folder = path.parent
    # A distinct package per folder supports relative imports and repeated module basenames.
    namespace = "_stopmo_model_" + hashlib.sha256(str(folder).encode()).hexdigest()
    local_names = {p.stem for p in folder.glob("*.py")}
    local_names.update(p.name for p in folder.iterdir() if p.is_dir())
    local_names.add(namespace)

    def local(name):
        return name.partition(".")[0] in local_names

    # Older model modules use bare sibling imports. Scope both the search path and their
    # module-cache entries to build(), restoring unrelated pre-existing imports even on failure.
    saved_modules = {name: module for name, module in sys.modules.copy().items() if local(name)}
    saved_path = sys.path[:]
    try:
        for name in saved_modules:
            del sys.modules[name]
        sys.path.insert(0, str(folder))
        package = ModuleType(namespace)
        package.__path__ = [str(folder)]
        sys.modules[namespace] = package
        name = namespace + "." + path.stem
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module.build()
    finally:
        sys.path[:] = saved_path
        for name in list(sys.modules):
            if local(name):
                del sys.modules[name]
        sys.modules.update(saved_modules)


def _flat(name, color):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = util.hex_rgb(color)
    bsdf.inputs["Roughness"].default_value = 0.5
    return mat


class Figure:
    archetype = "toy"   # lands with a tap, travels by hopping

    def __init__(self, name: str, spec: dict):
        self.name, self.spec = name, spec
        self.root = root = _build_model(spec["model"])
        root.name = name
        bpy.context.view_layer.update()
        parts = [o for o in root.children_recursive if o.type == "MESH"]
        pts = [o.matrix_world @ Vector(c) for o in parts for c in o.bound_box]
        built = max(p.z for p in pts)
        self.scale = float(spec.get("height", built)) / built
        self.H = built * self.scale
        self._base = {}   # object -> its own scale when shown
        self._shown = {}
        # ---- face parts, found by name
        low = lambda o: o.name.lower()  # noqa: E731
        self.eyes = [o for o in parts if re.match(r"(eye|glint)", low(o))]
        mains = [o for o in parts if re.match(r"eye_[lr](\.\d+)?$", low(o))]
        self.mouth = next(o for o in parts if re.match(r"mouth", low(o)))
        self.brows = [(o, o.location.copy()) for o in parts if re.match(r"brow", low(o))]
        head = next((o for o in parts if re.match(r"head(\.\d+)?$", low(o))), None)
        lo, hi = self._box([head] if head else parts)
        if not head:
            lo.z = hi.z - (hi.z - lo.z) * 0.5
        self.face = SimpleNamespace(center=(lo + hi) / 2 * self.scale, radii=(hi - lo) / 2 * self.scale,
                                    expression=spec.get("mouth", {}).get("rest", "smile"))
        ink = _flat(f"{name}_ink", DARK)
        self.closed = []
        for eye in mains:   # a closed eye: a short arc where the eye was
            lo, hi = self._box([eye])
            c, w = (lo + hi) / 2, (hi.x - lo.x) / 2 * 0.95
            arc = [Vector((c.x + w * math.cos(a), lo.y - 0.0003, c.z - w * 0.3 * math.sin(a) + w * 0.1)) for a in
                   [math.pi * i / 10 for i in range(11)]]
            self.closed.append(self._add(util.tube(f"{name}_closed_eye", arc, [w * 0.12] * len(arc), segments=8), ink))
        lo, hi = self._box([self.mouth])
        c, w = (lo + hi) / 2, hi.x - lo.x
        self.mouths = {}
        for key, (rx, rz) in {"open_s": (.30, .11), "open": (.34, .19), "wide": (.40, .28), "oh": (.19, .19), "grin": (.5, .26)}.items():
            obj = util.ellipsoid(f"{name}_mouth_{key}", (w * rx, 0.0012, w * rz), (c.x, lo.y - 0.0002, c.z - w * rz * 0.35), subdiv=3)
            if key == "grin":   # flat on top: a laughing mouth
                top = c.z + w * 0.02
                for v in obj.data.vertices:
                    v.co.z = min(v.co.z, top)
            self.mouths[key] = self._add(obj, ink)
        for obj in self.closed + list(self.mouths.values()):
            self._show(obj, False)
        self._mouth_shape = None
        self._pos, self._heading, self._pose = Vector((0, 0, 0)), 0.0, dict(REST)
        self._apply(None)

    # ------------------------------------------------------------ helpers ----
    def _box(self, objs):
        bpy.context.view_layer.update()
        pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
        return (Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts))),
                Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts))))

    def _add(self, obj, material):
        """A new replacement part, built in the model's own space, parented to the figure."""
        util.shade_smooth(obj)
        obj.data.materials.append(material)
        obj.parent = self.root
        return obj

    def _show(self, obj, visible: bool, frame=None) -> None:
        """Replacement parts are swapped by scale (see puppet.show_part for why), keeping their own size."""
        if obj not in self._base:
            self._base[obj] = tuple(obj.scale)
        if self._shown.get(obj) == visible and frame is None:
            return
        if frame is not None and visible and obj not in self._shown:
            self._show(obj, False, frame - 1)   # first appearance: pinned 'off' on the exposure before
        self._shown[obj] = visible
        obj.scale = self._base[obj] if visible else (HIDDEN_SCALE,) * 3
        if frame is not None:
            obj.keyframe_insert("scale", frame=frame)
            _hold_key(obj, "scale", frame)

    # ------------------------------------------------------------- moving ----
    def place(self, position, heading: float = 0.0, frame: int | None = None) -> None:
        self._pos = Vector((position[0], position[1], position[2] if len(position) > 2 else 0.0))
        self._heading = float(heading)
        self._apply(frame)

    def pose(self, pose: dict, frame: int | None = None) -> None:
        self._pose = {**REST, **pose}
        self._apply(frame)
        self._face(frame)

    def _apply(self, frame) -> None:
        p, root = self._pose, self.root
        left, forward, up = p["hips.at"]
        squash = 1.0 + min(0.0, up) * 2.2            # a crouch: the toy is pressed down a little
        offset = Matrix.Rotation(math.radians(self._heading), 3, "Z") @ Vector((left, -forward, max(0.0, up))) * self.H
        yaw = self._heading + p["spine.yaw"] + p["head.yaw"] * 0.7
        pitch = p["spine.pitch"] + p["hips.pitch"] + p["head.pitch"] * 0.6
        roll = p["spine.roll"] + p["hips.roll"] + p["head.roll"] * 0.8
        turn = Matrix.Rotation(math.radians(yaw), 3, "Z") @ Matrix.Rotation(math.radians(pitch), 3, "X") @ Matrix.Rotation(math.radians(roll), 3, "Y")
        root.location = self._pos + offset
        root.rotation_euler = turn.to_euler("XYZ")
        wide = self.scale / math.sqrt(squash)
        root.scale = (wide, wide, self.scale * squash)
        if frame is not None:
            for channel in ("location", "rotation_euler", "scale"):
                root.keyframe_insert(channel, frame=frame)

    def _face(self, frame) -> None:
        p = self._pose
        shut = p["lids"] in ("closed", "happy")
        for obj in self.eyes:
            self._show(obj, not shut, frame)
        for obj in self.closed:
            self._show(obj, shut, frame)
        for obj, home in self.brows:
            obj.location = home + Vector((0, 0, 0.0022 * max(-1.0, min(1.5, p["brows.raise"]))))
            if frame is not None:
                obj.keyframe_insert("location", frame=frame)
        if p.get("mouth"):
            self.set_mouth(p["mouth"], frame)

    def set_mouth(self, shape: str, frame: int | None = None) -> None:
        """Expression or lip-sync shape. Closed shapes show the smile the model was built with."""
        if len(shape) > 1 and shape != "X":
            self.face.expression = shape
        if shape in ("X", "A"):
            shape = self.face.expression
        key = OPEN.get(shape)   # None = the built smile
        if key == self._mouth_shape and frame is None:
            return
        self._mouth_shape = key
        self._show(self.mouth, key is None, frame)
        for name, obj in self.mouths.items():
            self._show(obj, name == key, frame)


def build(name: str, spec: dict) -> Figure:
    return Figure(name, spec)
