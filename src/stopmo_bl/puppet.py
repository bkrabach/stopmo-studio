"""Puppet: a skeleton, its clay parts, sockets for stuck-on pieces and replacement sets.

Real stop-motion puppets swap whole pieces between exposures (mouths, hands,
eyelids). `swap sets` model that directly: a set is a group of alternative
objects of which exactly one is visible on any exposure.
"""
from __future__ import annotations

import bpy
from mathutils import Matrix, Vector

from . import style as style_mod
from .materials.nodes import store_rest
from .rig import Skeleton, attach, skin
from .util import collection, link, lumpify, set_material


HIDDEN_SCALE = 1e-4


def show_part(obj, visible: bool, frame: int | None = None) -> None:
    """Show or put away a replacement part (keyed when frame is given).

    A part that is 'off' is shrunk to a speck at its own origin (for face parts: the middle of the
    solid head) instead of being hidden from the renderer, so every part is an ordinary object that
    is always present. Background: in one 60-exposure render (two Blender processes sharing the
    GPU), teeth were missing on 17 exposures of one clip while the cavity and tongue of the same
    mouths rendered. Twelve single-process and 42 concurrent re-renders of the same plan did not
    reproduce it, so the cause is NOT established; keyed render visibility was the only thing that
    set those parts apart, and removing it is a precaution, not a proven fix.
    """
    size = 1.0 if visible else HIDDEN_SCALE
    obj.scale = (size, size, size)
    if frame is not None:
        obj.keyframe_insert("scale", frame=frame)
        _hold_key(obj, "scale", frame)


def _hold_key(obj, data_path: str, frame: int) -> None:
    """Make the key at `frame` hold its value until the next key (a swap, not a tween)."""
    from bpy_extras import anim_utils

    anim = obj.animation_data
    bag = anim_utils.action_get_channelbag_for_slot(anim.action, anim.action_slot)
    for curve in bag.fcurves:
        if curve.data_path != data_path:
            continue
        for point in reversed(curve.keyframe_points):  # the new key is at or near the end
            if abs(point.co.x - frame) < 0.5:
                point.interpolation = "CONSTANT"
                break


def part_shown(obj) -> bool:
    return obj.scale.x > 0.5


class Puppet:
    archetype = "puppet"

    def __init__(self, name: str, spec: dict, skeleton: Skeleton):
        self.name = name
        self.spec = spec
        self.skel = skeleton
        self.col = collection(name)
        self.armature = skeleton.build(self.col)
        self.style = style_mod.active()
        self.sockets: dict[str, bpy.types.Object] = {}
        self.swaps: dict[str, dict[str, list[bpy.types.Object]]] = {}
        self.swap_state: dict[str, str] = {}
        self._swap_keyed: set[str] = set()
        self.parts: dict[str, bpy.types.Object] = {}
        self.eyes: list[dict] = []
        self.brows: list[dict] = []
        self.scale = float(spec.get("height", 0.25))

    # ------------------------------------------------------------ parts ----
    def finish(self, obj, role: str, color: str, *, bones=None, bone=None, lumpy=1.0, blend=0.5, **mat_opts):
        """Give a freshly built mesh its hand-made wobble, material and binding."""
        if obj.users_collection:
            for c in list(obj.users_collection):
                c.objects.unlink(obj)
        self.col.objects.link(obj)
        amount = self.style.lumpiness * lumpy
        if amount > 0:
            lumpify(obj, 0.0055 * self.scale * amount, 0.11 * self.scale, seed=f"{self.name}/{obj.name}")
        store_rest(obj)
        set_material(obj, self.style.material(role, color, **mat_opts))
        if bones:
            skin(obj, self.skel, bones, blend=blend)
        elif bone:
            attach(obj, self.skel, bone)
        self.parts[obj.name] = obj
        return obj

    def socket(self, name: str, bone: str, location) -> bpy.types.Object:
        """Body-axis-aligned empty that rides on a bone. Children use simple local transforms."""
        empty = bpy.data.objects.new(f"{self.name}_{name}", None)
        empty.empty_display_size = 0.005
        link(empty, self.col)
        arm = self.armature
        b = arm.data.bones[bone]
        empty.parent = arm
        empty.parent_type = "BONE"
        empty.parent_bone = bone
        tail_matrix = b.matrix_local @ Matrix.Translation((0, b.length, 0))
        empty.matrix_parent_inverse = tail_matrix.inverted()
        empty.matrix_basis = Matrix.Translation(Vector(location))
        self.sockets[name] = empty
        return empty

    def stick(self, obj, socket: str, role: str, color: str, *, lumpy=0.0, **mat_opts):
        """Parent a mesh (built in body space) to a socket, keeping it where it is."""
        if obj.users_collection:
            for c in list(obj.users_collection):
                c.objects.unlink(obj)
        self.col.objects.link(obj)
        sock = self.sockets[socket]
        amount = self.style.lumpiness * lumpy
        if amount > 0:
            lumpify(obj, 0.0055 * self.scale * amount, 0.11 * self.scale, seed=f"{self.name}/{obj.name}")
        # move mesh data into socket-local space so the object sits at the socket origin
        offset = Vector(sock.matrix_basis.to_translation())
        obj.data.transform(Matrix.Translation(-offset))
        obj.matrix_basis = Matrix.Identity(4)
        obj.parent = sock
        store_rest(obj)
        set_material(obj, self.style.material(role, color, **mat_opts))
        self.parts[obj.name] = obj
        return obj

    # ------------------------------------------------------------ swaps ----
    def add_swap(self, set_name: str, variant: str, objects: list[bpy.types.Object]) -> None:
        self.swaps.setdefault(set_name, {})[variant] = objects
        for o in objects:
            show_part(o, False)

    def swap(self, set_name: str, variant: str, frame: int | None = None) -> None:
        """Show one variant of a replacement set (keyed when frame is given)."""
        variants = self.swaps[set_name]
        if variant not in variants:
            raise KeyError(f"{self.name}: no '{variant}' in swap set '{set_name}' ({sorted(variants)})")
        previous = self.swap_state.get(set_name)
        for name, objs in variants.items():
            if frame is not None and previous is not None and name not in (variant, previous):
                continue  # untouched variants stay hidden; no need to re-key them
            visible = name == variant
            for o in objs:
                if frame is not None and visible and o.name not in self._swap_keyed:
                    # first appearance: pin it 'off' on the exposure before, otherwise the
                    # curve's first key (on) would extend back to the start of the shot
                    show_part(o, False, frame - 1)
                show_part(o, visible, frame)
                if frame is not None:
                    self._swap_keyed.add(o.name)
        self.swap_state[set_name] = variant

    # ------------------------------------------------------- placement ----
    def place(self, position, heading: float = 0.0, frame: int | None = None) -> None:
        """Put the puppet on the set. heading in degrees: 0 faces -Y (toward a front camera)."""
        import math

        arm = self.armature
        arm.location = Vector((position[0], position[1], position[2] if len(position) > 2 else 0.0))
        arm.rotation_euler = (0.0, 0.0, math.radians(heading))
        if frame is not None:
            arm.keyframe_insert("location", frame=frame)
            arm.keyframe_insert("rotation_euler", frame=frame)

    # subclasses implement: pose(pose_dict, frame=None), rest_pose()
