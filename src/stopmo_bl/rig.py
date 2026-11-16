"""Skeleton + pose solver.

Poses are described semantically in BODY SPACE (the armature's own axes):

    forward = -Y      left = +X      up = +Z

Two kinds of joint control cover everything a puppet needs:

* "rel"  - a small rotation relative to the parent (spine, neck, head, tail)
* "aim"  - point the bone along a direction, with a reference direction that
           fixes its twist (limbs, hands, feet). Limb chains are aimed by an
           analytic two-bone IK solve, so a pose just says where the hand is.

The solver is plain maths (no depsgraph evaluation), which keeps keyframing
thousands of exposures fast, and it never depends on bone roll conventions.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import bpy
from mathutils import Matrix, Quaternion, Vector

from .util import link

FORWARD = Vector((0, -1, 0))
LEFT = Vector((1, 0, 0))
UP = Vector((0, 0, 1))


@dataclass
class BoneDef:
    name: str
    head: Vector
    tail: Vector
    parent: str | None = None
    ref: Vector = field(default_factory=lambda: Vector((0, 1, 0)))  # where local Z points at rest
    deform: bool = True


def frame(direction: Vector, ref: Vector) -> Matrix:
    """Rotation whose Y axis is `direction` and whose Z axis is as close to `ref` as possible."""
    y = direction.normalized()
    z = ref - y * ref.dot(y)
    if z.length < 1e-5:
        # ref parallel to direction: pick any stable perpendicular
        alt = Vector((0, 0, 1)) if abs(y.z) < 0.9 else Vector((0, 1, 0))
        z = alt - y * alt.dot(y)
    z.normalize()
    x = y.cross(z)
    m = Matrix((x, y, z)).transposed()
    return m


def rot_xyz(pitch=0.0, roll=0.0, yaw=0.0) -> Matrix:
    """Body-space rotation from degrees: pitch = lean forward, roll = tip to the left, yaw = turn left."""
    rx = Matrix.Rotation(math.radians(pitch), 3, "X")
    ry = Matrix.Rotation(math.radians(roll), 3, "Y")
    rz = Matrix.Rotation(math.radians(yaw), 3, "Z")
    return rz @ rx @ ry


def two_bone_ik(origin: Vector, target: Vector, l1: float, l2: float, pole: Vector):
    """-> (mid joint position, clamped end position). `pole` is where the middle joint points."""
    v = target - origin
    dist = v.length
    lo, hi = abs(l1 - l2) * 1.05 + 1e-5, (l1 + l2) * 0.999
    d = min(max(dist, lo), hi)
    vhat = v.normalized() if dist > 1e-8 else Vector((0, 0, -1))
    a = (l1 * l1 - l2 * l2 + d * d) / (2 * d)
    h = math.sqrt(max(l1 * l1 - a * a, 0.0))
    perp = pole - vhat * pole.dot(vhat)
    if perp.length < 1e-5:
        alt = Vector((0, 1, 0)) if abs(vhat.y) < 0.9 else Vector((0, 0, 1))
        perp = alt - vhat * alt.dot(vhat)
    perp.normalize()
    mid = origin + vhat * a + perp * h
    end = origin + vhat * d
    return mid, end


class Skeleton:
    """Rest skeleton, the Blender armature built from it, and the FK solver."""

    def __init__(self, name: str, bones: list[BoneDef]):
        self.name = name
        self.defs = {b.name: b for b in bones}
        self.order = [b.name for b in bones]  # parents listed before children
        self.rest_rot = {b.name: frame(b.tail - b.head, b.ref) for b in bones}
        self.rest_head = {b.name: b.head.copy() for b in bones}
        self.length = {b.name: (b.tail - b.head).length for b in bones}
        self.armature: bpy.types.Object | None = None
        self._last_quat: dict[str, Quaternion] = {}

    # ----------------------------------------------------------- build ----
    def build(self, col=None) -> bpy.types.Object:
        data = bpy.data.armatures.new(self.name + "_rig")
        obj = bpy.data.objects.new(self.name + "_rig", data)
        link(obj, col)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode="EDIT")
        for name in self.order:
            d = self.defs[name]
            eb = data.edit_bones.new(name)
            eb.head, eb.tail = d.head, d.tail
            eb.align_roll(d.ref)
            eb.use_deform = d.deform
            if d.parent:
                eb.parent = data.edit_bones[d.parent]
                eb.use_connect = False
        bpy.ops.object.mode_set(mode="OBJECT")
        # Use Blender's actual rest matrices as ground truth for the solver.
        for name in self.order:
            m = data.bones[name].matrix_local
            self.rest_rot[name] = m.to_3x3()
            self.rest_head[name] = m.to_translation()
        for pb in obj.pose.bones:
            pb.rotation_mode = "QUATERNION"
        data.display_type = "STICK"
        obj.show_in_front = False
        obj.hide_render = True
        self.armature = obj
        return obj

    # ----------------------------------------------------------- solve ----
    def solve(self, controls: dict) -> dict:
        """controls: bone -> {"rel": Matrix3} | {"aim": Vector, "ref": Vector} [+ "offset": Vector]

        Returns bone -> (armature-space 3x3 rotation, armature-space head position).
        Bones without a control inherit their parent's motion.
        """
        total: dict[str, Matrix] = {}  # accumulated delta rotation (applied to rest)
        rot: dict[str, Matrix] = {}
        pos: dict[str, Vector] = {}
        for name in self.order:
            d = self.defs[name]
            ctl = controls.get(name, {})
            parent_total = total[d.parent] if d.parent else Matrix.Identity(3)
            if d.parent:
                head = pos[d.parent] + parent_total @ (self.rest_head[name] - self.rest_head[d.parent])
            else:
                head = self.rest_head[name].copy()
            if "offset" in ctl:
                head = head + ctl["offset"]
            if "aim" in ctl:
                r = frame(ctl["aim"], ctl.get("ref", parent_total @ self.rest_rot[name].col[2]))
                t = r @ self.rest_rot[name].inverted()
            else:
                t = parent_total @ ctl.get("rel", Matrix.Identity(3))
                r = t @ self.rest_rot[name]
            total[name], rot[name], pos[name] = t, r, head
        self._total = total
        self.last_solved = {n: (rot[n], pos[n]) for n in self.order}
        return self.last_solved

    def tail_position(self, solved: dict, name: str) -> Vector:
        r, p = solved[name]
        return p + r.col[1] * self.length[name]

    # ------------------------------------------------------------ apply ----
    def apply(self, solved: dict, frame_no: int | None = None, bones: list[str] | None = None) -> None:
        """Write a solved pose onto the armature; keyframe it when frame_no is given."""
        arm = self.armature
        mats: dict[str, Matrix] = {}
        for name in self.order:
            r, p = solved[name]
            mats[name] = Matrix.Translation(p) @ r.to_4x4()
        for name in bones or self.order:
            d = self.defs[name]
            rest = Matrix.Translation(self.rest_head[name]) @ self.rest_rot[name].to_4x4()
            if d.parent:
                rest_parent = (
                    Matrix.Translation(self.rest_head[d.parent]) @ self.rest_rot[d.parent].to_4x4()
                )
                basis = (mats[d.parent] @ rest_parent.inverted() @ rest).inverted() @ mats[name]
            else:
                basis = rest.inverted() @ mats[name]
            pb = arm.pose.bones[name]
            q = basis.to_quaternion()
            last = self._last_quat.get(name)
            if last is not None and last.dot(q) < 0:
                q.negate()  # keep keys on the short path
            self._last_quat[name] = q.copy()
            pb.rotation_quaternion = q
            loc = basis.to_translation()
            moved = loc.length > 1e-6 or name in getattr(self, "_loc_keyed", set())
            pb.location = loc
            if frame_no is not None:
                pb.keyframe_insert("rotation_quaternion", frame=frame_no)
                if moved:
                    self._loc_keyed = getattr(self, "_loc_keyed", set()) | {name}
                    pb.keyframe_insert("location", frame=frame_no)


# -------------------------------------------------------------- skinning ----
def _segment_distance(p: Vector, a: Vector, b: Vector) -> tuple[float, float]:
    ab = b - a
    t = max(0.0, min(1.0, (p - a).dot(ab) / max(ab.length_squared, 1e-12)))
    return (p - (a + ab * t)).length, t


def skin(obj: bpy.types.Object, skel: Skeleton, bones: list[str], *, blend: float = 0.5) -> None:
    """Bind a mesh to a set of bones with smooth distance-based weights.

    Each vertex is weighted to its nearest bones among `bones`; `blend`
    (in bone-radius-ish units of the mesh size) controls how soft joints are.
    Restricting the candidate bones per part is what keeps an arm from
    sticking to the torso.
    """
    mesh = obj.data
    inv = obj.matrix_world.inverted()
    arm_to_obj = inv @ skel.armature.matrix_world
    segs = []
    for name in bones:
        d = skel.defs[name]
        segs.append((name, arm_to_obj @ d.head, arm_to_obj @ d.tail))
    groups = {name: obj.vertex_groups.get(name) or obj.vertex_groups.new(name=name) for name in bones}
    # softness scale from the part's own thickness
    size = max(min(obj.dimensions) * blend, 1e-5)
    for v in mesh.vertices:
        dists = [(_segment_distance(v.co, a, b)[0], name) for name, a, b in segs]
        dmin = min(d for d, _ in dists)
        weights = {}
        for dist, name in dists:
            w = math.exp(-((dist - dmin) / size) ** 2 * 4.0)
            if w > 0.01:
                weights[name] = w
        norm = sum(weights.values())
        for name, w in weights.items():
            groups[name].add([v.index], w / norm, "REPLACE")
    mod = obj.modifiers.new("armature", "ARMATURE")
    mod.object = skel.armature
    obj.parent = skel.armature


def attach(obj: bpy.types.Object, skel: Skeleton, bone: str) -> None:
    """Rigidly attach a part to one bone (weights of 1), keeping it in place."""
    group = obj.vertex_groups.new(name=bone)
    group.add(list(range(len(obj.data.vertices))), 1.0, "REPLACE")
    mod = obj.modifiers.new("armature", "ARMATURE")
    mod.object = skel.armature
    obj.parent = skel.armature
