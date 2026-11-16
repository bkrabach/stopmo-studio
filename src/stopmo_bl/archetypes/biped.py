"""Biped puppet: a two-legged clay character driven by a flat, semantic pose.

Pose keys (all optional; anything missing falls back to REST). Directions are
always (left, forward, up); angles are degrees.

    hips.at      offset of the pelvis in body heights          (0, 0, -0.05) = slight squat
    hips.pitch / hips.roll / hips.yaw
    spine.pitch / spine.roll / spine.yaw     lean, tip, twist of the torso
    head.pitch / head.roll / head.yaw        nod (+ = down), tilt, turn (+ = puppet's left)
    arm_l.at / arm_r.at     hand position from the shoulder in arm lengths,
                            as (out from the body, forward, up) - mirrored automatically
    arm_l.world / arm_r.world   hand position as a world-space point (reach for a prop);
                            blended with `.at` by arm_l.reach (0..1)
    arm_l.elbow / arm_r.elbow   where the elbow points (out, forward, up)
    leg_l.at / leg_r.at     foot offset from its rest spot in body heights (out, forward, up)
    leg_l.yaw / leg_l.toe   foot turn-out and toe pitch
    gaze         (yaw, pitch) of the pupils
    lids         "open" | "half" | "closed" | "wide"
    brows.raise / brows.tilt     (+tilt = angry, -tilt = worried)
    brows.cock                  -1..1; +1 raises LEFT brow and lowers RIGHT
    mouth        any mouth name, or None to leave the mouth to lip-sync
"""
from __future__ import annotations

import math

from mathutils import Matrix, Vector

from .. import util
from ..parts import face as face_parts
from ..puppet import Puppet
from ..rig import BoneDef, Skeleton, rot_xyz, two_bone_ik

REST = {
    "hips.at": (0.0, 0.0, 0.0),
    "hips.pitch": 0.0,
    "hips.roll": 0.0,
    "hips.yaw": 0.0,
    "spine.pitch": 0.0,
    "spine.roll": 0.0,
    "spine.yaw": 0.0,
    "head.pitch": 0.0,
    "head.roll": 0.0,
    "head.yaw": 0.0,
    "arm_l.at": (0.22, 0.06, -0.94),
    "arm_r.at": (0.22, 0.06, -0.94),
    "arm_l.elbow": (0.5, -0.7, -0.4),
    "arm_r.elbow": (0.5, -0.7, -0.4),
    "arm_l.reach": 0.0,
    "arm_r.reach": 0.0,
    "arm_l.world": (0.0, 0.0, 0.0),
    "arm_r.world": (0.0, 0.0, 0.0),
    "arm_l.hand": 0.0,
    "arm_r.hand": 0.0,
    "leg_l.at": (0.0, 0.0, 0.0),
    "leg_r.at": (0.0, 0.0, 0.0),
    "leg_l.yaw": 10.0,
    "leg_r.yaw": 10.0,
    "leg_l.toe": 0.0,
    "leg_r.toe": 0.0,
    "gaze": (0.0, 0.0),
    "lids": "open",
    "brows.raise": 0.0,
    "brows.tilt": 0.0,
    "brows.cock": 0.0,
    "mouth": None,
}

PROPORTIONS = {
    # all in body heights
    "hip_z": 0.40,
    "hip_x": 0.058,
    "ankle_z": 0.055,
    "foot": 0.11,
    "waist": 0.09,  # hips bone length
    "spine": 0.09,
    "chest": 0.10,
    "neck": 0.035,
    "head": 0.26,
    "shoulder_x": 0.115,
    "shoulder_drop": 0.025,
    "upper_arm": 0.135,
    "forearm": 0.125,
    "hand": 0.085,
    "arm_r": 0.03,
    "leg_r": 0.04,
    "chest_size": (0.115, 0.085, 0.105),
    "belly_size": (0.118, 0.098, 0.10),
    "pelvis_size": (0.108, 0.086, 0.075),
}


def bv(left, forward, up) -> Vector:
    """(left, forward, up) -> body-space vector."""
    return Vector((left, -forward, up))


class Biped(Puppet):
    archetype = "biped"

    def __init__(self, name: str, spec: dict):
        self.prop = {**PROPORTIONS, **spec.get("proportions", {})}
        H = float(spec.get("height", 0.25))
        P = self.prop
        z_hip = P["hip_z"] * H
        z_waist = z_hip + P["waist"] * H
        z_spine = z_waist + P["spine"] * H
        z_chest = z_spine + P["chest"] * H
        z_neck = z_chest + P["neck"] * H
        z_top = z_neck + P["head"] * H
        back = Vector((0, 1, 0))
        bones = [
            BoneDef("hips", Vector((0, 0, z_hip)), Vector((0, 0, z_waist)), None, back),
            BoneDef("spine", Vector((0, 0, z_waist)), Vector((0, 0, z_spine)), "hips", back),
            BoneDef("chest", Vector((0, 0, z_spine)), Vector((0, 0, z_chest)), "spine", back),
            BoneDef("neck", Vector((0, 0, z_chest)), Vector((0, 0, z_neck)), "chest", back),
            BoneDef("head", Vector((0, 0, z_neck)), Vector((0, 0, z_top)), "neck", back),
        ]
        self.arm_len = (P["upper_arm"] + P["forearm"]) * H
        for side, s in (("l", 1), ("r", -1)):
            sh = Vector((s * P["shoulder_x"] * H, 0, z_chest - P["shoulder_drop"] * H))
            d = Vector((s * 0.3, 0, -0.954)).normalized()
            el = sh + d * P["upper_arm"] * H
            wr = el + d * P["forearm"] * H
            tip = wr + d * P["hand"] * H
            fwd = Vector((0, -1, 0))
            bones += [
                BoneDef(f"upper_arm_{side}", sh, el, "chest", fwd),
                BoneDef(f"forearm_{side}", el, wr, f"upper_arm_{side}", fwd),
                BoneDef(f"hand_{side}", wr, tip, f"forearm_{side}", fwd),
            ]
            hip = Vector((s * P["hip_x"] * H, 0, z_hip))
            ankle = Vector((s * P["hip_x"] * H, 0, P["ankle_z"] * H))
            knee = (hip + ankle) / 2 + Vector((0, -0.004 * H, 0))
            toe = ankle + Vector((0, -P["foot"] * H, -P["ankle_z"] * H * 0.45))
            bones += [
                BoneDef(f"thigh_{side}", hip, knee, "hips", fwd),
                BoneDef(f"shin_{side}", knee, ankle, f"thigh_{side}", fwd),
                BoneDef(f"foot_{side}", ankle, toe, f"shin_{side}", Vector((0, 0, 1))),
            ]
        super().__init__(name, spec, Skeleton(name, bones))
        self.H = H
        self.face = None
        self._build_body()
        self._build_head()
        self.pose({})

    # ------------------------------------------------------------- build ----
    def _build_body(self):
        H, P, sk = self.H, self.prop, self.skel
        spec = self.spec
        top = spec.get("top", "#4F7A46")
        sleeves = spec.get("sleeves", top)
        trousers = spec.get("trousers", "#5B4636")
        shoes = spec.get("shoes", "#3B2A20")
        skin = spec.get("skin", "#E8B08A")
        top_role = spec.get("top_role", "cloth")

        z_waist = sk.rest_head["spine"].z
        z_chest_mid = (sk.rest_head["chest"].z + sk.rest_head["neck"].z) / 2
        chest = util.ellipsoid("chest", Vector(P["chest_size"]) * H, (0, 0, z_chest_mid), subdiv=3)
        belly = util.ellipsoid("belly", Vector(P["belly_size"]) * H, (0, -0.008 * H, z_waist + 0.02 * H), subdiv=3)
        parts = [chest, belly]
        for s in (1, -1):  # shoulder caps so sleeves blend into the torso
            sh = sk.rest_head["upper_arm_l" if s > 0 else "upper_arm_r"]
            parts.append(util.ellipsoid("cap", (P["arm_r"] * H * 1.35,) * 3, sh, subdiv=2))
        torso = util.join(parts, f"{self.name}_torso")
        util.remesh(torso, voxel=H / 110, smooth_iters=10, smooth_factor=0.7)
        self.finish(torso, top_role, top, bones=["hips", "spine", "chest"], blend=0.35)

        pelvis = util.ellipsoid(
            f"{self.name}_pelvis", Vector(P["pelvis_size"]) * H, (0, 0, sk.rest_head["hips"].z + 0.015 * H), subdiv=3
        )
        self.finish(pelvis, "cloth", trousers, bones=["hips", "thigh_l", "thigh_r"], blend=0.25)

        neck = util.tube(
            f"{self.name}_neck",
            [sk.rest_head["chest"] + Vector((0, 0, 0.06 * H)), sk.rest_head["head"] + Vector((0, 0, 0.03 * H))],
            [0.034 * H, 0.03 * H],
            segments=14,
        )
        self.finish(neck, "skin", skin, bones=["chest", "neck", "head"], blend=0.6, lumpy=0.3)

        for side in ("l", "r"):
            # --- arm (sleeve) -------------------------------------------------
            a, b, c = sk.rest_head[f"upper_arm_{side}"], sk.rest_head[f"forearm_{side}"], sk.rest_head[f"hand_{side}"]
            n = 12
            pts = [a.lerp(b, i / (n // 2)) for i in range(n // 2)] + [b.lerp(c, i / (n // 2)) for i in range(n // 2 + 1)]
            r0 = P["arm_r"] * H
            radii = [r0 * (1.08 - 0.3 * i / (len(pts) - 1)) for i in range(len(pts))]
            arm = util.tube(f"{self.name}_arm_{side}", pts, radii, segments=14)
            self.finish(arm, top_role if sleeves == top else "cloth", sleeves, bones=[f"upper_arm_{side}", f"forearm_{side}"], blend=0.9, lumpy=0.5)
            # cuff
            d = (c - b).normalized()
            cuff = util.tube(f"{self.name}_cuff_{side}", [c - d * 0.012 * H, c + d * 0.004 * H], [r0 * 0.9, r0 * 0.9], segments=14)
            self.finish(cuff, top_role if sleeves == top else "cloth", sleeves, bone=f"forearm_{side}", lumpy=0.2)
            # --- hand: mitt + three fingers + thumb, fused ---------------------
            self._build_hand(side, skin)
            # --- leg ----------------------------------------------------------
            a, b, c = sk.rest_head[f"thigh_{side}"], sk.rest_head[f"shin_{side}"], sk.rest_head[f"foot_{side}"]
            pts = [a.lerp(b, i / 5) for i in range(5)] + [b.lerp(c, i / 5) for i in range(6)]
            lr = P["leg_r"] * H
            radii = [lr * (1.12 - 0.18 * i / (len(pts) - 1)) for i in range(len(pts))]
            leg = util.tube(f"{self.name}_leg_{side}", pts, radii, segments=14)
            self.finish(leg, "cloth", trousers, bones=[f"thigh_{side}", f"shin_{side}"], blend=0.9, lumpy=0.5)
            # --- shoe ---------------------------------------------------------
            ankle = c
            heel = util.ellipsoid("heel", (lr * 1.15, lr * 1.2, P["ankle_z"] * H * 0.95), (ankle.x, ankle.y + 0.004 * H, P["ankle_z"] * H * 0.95), subdiv=3)
            toe = util.ellipsoid("toe", (lr * 1.25, P["foot"] * H * 0.62, P["ankle_z"] * H * 0.72), (ankle.x, ankle.y - P["foot"] * H * 0.55, P["ankle_z"] * H * 0.72), subdiv=3)
            shoe = util.join([heel, toe], f"{self.name}_shoe_{side}")
            util.remesh(shoe, voxel=H / 140, smooth_iters=6)
            # flatten the sole
            for v in shoe.data.vertices:
                if v.co.z < 0.004 * H:
                    v.co.z = 0.0015 * H
            self.finish(shoe, "shoe", shoes, bone=f"foot_{side}", lumpy=0.3)

    def _build_hand(self, side, skin):
        H, P, sk = self.H, self.prop, self.skel
        s = 1 if side == "l" else -1
        wrist = sk.rest_head[f"hand_{side}"]
        d = (sk.rest_head[f"hand_{side}"] - sk.rest_head[f"forearm_{side}"]).normalized()
        fwd = Vector((0, -1, 0))
        out = d.cross(fwd).normalized() * s  # across the palm, away from the body
        hl = P["hand"] * H
        lumps = [util.ellipsoid("palm", (hl * 0.5,) * 3, wrist + d * hl * 0.5, subdiv=3)]
        palm = lumps[0]
        # squash the palm flat along the 'out' axis (hands hang with palms inward)
        for v in palm.data.vertices:
            rel = v.co - (wrist + d * hl * 0.5)
            v.co -= out * rel.dot(out) * 0.35
        for i, t in enumerate((-0.4, 0.0, 0.4)):
            base = wrist + d * hl * 0.75 + fwd * (t * hl)
            tip = base + d * hl * 0.62 + fwd * (t * hl * 0.3)
            lumps.append(util.tube(f"f{i}", [base, (base + tip) / 2, tip], [hl * 0.145, hl * 0.14, hl * 0.125], segments=10))
        tb = wrist + d * hl * 0.35 + fwd * (hl * 0.42)
        lumps.append(util.tube("thumb", [tb, tb + fwd * hl * 0.34 + d * hl * 0.2, tb + fwd * hl * 0.5 + d * hl * 0.5], [hl * 0.16, hl * 0.15, hl * 0.13], segments=10))
        hand = util.join(lumps, f"{self.name}_hand_{side}")
        util.remesh(hand, voxel=hl / 34, smooth_iters=2, smooth_factor=0.5)
        self.finish(hand, "skin", skin, bone=f"hand_{side}", lumpy=0.3)

    def _build_head(self):
        spec = self.spec
        head_spec = spec.get("head", {})
        head, face = face_parts.build_head(self, head_spec, "head")
        face_parts.build_eyes(self, face, spec.get("eyes", {"brows": {}}))
        face_parts.build_mouths(self, face, spec.get("mouth", {}))
        hair = spec.get("hair_lumps")
        if hair:
            lumps = []
            for lump in hair:
                u, v, w = lump["at"]
                pos = face.center + Vector((u * face.radii.x, w * face.radii.y, v * face.radii.z))
                lumps.append(util.ellipsoid("hair", Vector(lump["size"]) * face.radii.x, pos, subdiv=3))
            obj = util.join(lumps, f"{self.name}_hair")
            util.remesh(obj, voxel=face.radii.x / 26, smooth_iters=5)
            self.finish(obj, "hair", spec.get("hair", "#5A3A22"), bone="head", lumpy=1.2)
        self._build_decor()

    def _build_decor(self):
        """Stuck-on extras from spec["decor"]: noses, floppy ears, hats, buttons, ties...

        Each item: {bone: name, shape: ball|box|cone|tube, color, role?, lumpy?} plus
          ball/box: size, at        cone: radius, radius_top, depth, at        tube: points, radius
        On the head, positions are in head radii from the head centre as (across, up, depth)
        with depth -1 = front of the face. Elsewhere they are body-space (left, forward, up)
        in body heights.
        """
        H, face = self.H, self.face
        for i, item in enumerate(self.spec.get("decor", [])):
            bone = item.get("bone", "head")
            on_head = bone == "head"

            def pt(p):
                if on_head:
                    return face.center + Vector((p[0] * face.radii.x, p[2] * face.radii.y, p[1] * face.radii.z))
                return bv(*p) * H

            unit = face.radii.x if on_head else H
            shape = item.get("shape", "ball")
            name = f"{self.name}_decor{i}_{item.get('name', shape)}"
            if shape == "ball":
                obj = util.ellipsoid(name, Vector(item["size"]) * unit, pt(item["at"]), subdiv=3)
            elif shape == "box":
                obj = util.rounded_box(name, Vector(item["size"]) * unit, pt(item["at"]), bevel=item.get("bevel", 0.25))
            elif shape == "cone":
                obj = util.cylinder(name, item["radius"] * unit, item["depth"] * unit, pt(item["at"]),
                                    radius_top=item.get("radius_top", 0.0) * unit, segments=28)
                util.shade_smooth(obj)
            elif shape == "tube":
                pts = [pt(p) for p in item["points"]]
                radius = item["radius"]
                radii = [r * unit for r in radius] if isinstance(radius, list) else [radius * unit] * len(pts)
                obj = util.tube(name, pts, radii, segments=14)
            else:
                raise KeyError(f"unknown decor shape {shape!r}")
            role, color, lumpy = item.get("role", "cloth"), item.get("color", "#888888"), item.get("lumpy", 0.4)
            if on_head:
                self.stick(obj, "face", role, color, lumpy=lumpy)
            else:
                self.finish(obj, role, color, bone=bone, lumpy=lumpy)

    # -------------------------------------------------------------- pose ----
    def pose(self, pose: dict, frame: int | None = None) -> None:
        p = {**REST, **pose}
        H, sk = self.H, self.skel
        controls = {
            "hips": {"rel": rot_xyz(p["hips.pitch"], p["hips.roll"], p["hips.yaw"]), "offset": bv(*p["hips.at"]) * H},
            "spine": {"rel": rot_xyz(p["spine.pitch"] * 0.45, p["spine.roll"] * 0.45, p["spine.yaw"] * 0.45)},
            "chest": {"rel": rot_xyz(p["spine.pitch"] * 0.55, p["spine.roll"] * 0.55, p["spine.yaw"] * 0.55)},
            "neck": {"rel": rot_xyz(p["head.pitch"] * 0.3, p["head.roll"] * 0.3, p["head.yaw"] * 0.3)},
            "head": {"rel": rot_xyz(p["head.pitch"] * 0.7, p["head.roll"] * 0.7, p["head.yaw"] * 0.7)},
        }
        solved = sk.solve(controls)
        total = sk._total
        chest_t, chest_p = total["chest"], solved["chest"][1]
        hips_t, hips_p = total["hips"], solved["hips"][1]
        # built from the placement itself: matrix_world is stale until the depsgraph updates
        arm = self.armature
        world_inv = (Matrix.Translation(arm.location) @ arm.rotation_euler.to_matrix().to_4x4()).inverted()

        for side, s in (("l", 1), ("r", -1)):
            # ---- arm: two-bone IK from the shoulder --------------------------
            sh = chest_p + chest_t @ (sk.rest_head[f"upper_arm_{side}"] - sk.rest_head["chest"])
            out, fwd, up = p[f"arm_{side}.at"]
            target = sh + chest_t @ (Vector((s * out, -fwd, up)) * self.arm_len)
            reach = p[f"arm_{side}.reach"]
            if reach > 0:
                target = target.lerp(world_inv @ Vector(p[f"arm_{side}.world"]), min(reach, 1.0))
            eo, ef, eu = p[f"arm_{side}.elbow"]
            pole = chest_t @ Vector((s * eo, -ef, eu))
            l1, l2 = sk.length[f"upper_arm_{side}"], sk.length[f"forearm_{side}"]
            mid, end = two_bone_ik(sh, target, l1, l2, pole)
            fore_dir = (end - mid).normalized()
            palm_ref = chest_t @ Vector((0, -1, 0))
            hand_dir = Matrix.Rotation(math.radians(p[f"arm_{side}.hand"]), 3, fore_dir.cross(palm_ref).normalized() if fore_dir.cross(palm_ref).length > 1e-4 else Vector((1, 0, 0))) @ fore_dir
            controls[f"upper_arm_{side}"] = {"aim": mid - sh, "ref": palm_ref}
            controls[f"forearm_{side}"] = {"aim": end - mid, "ref": palm_ref}
            controls[f"hand_{side}"] = {"aim": hand_dir, "ref": palm_ref}

            # ---- leg: foot stays where the pose puts it on the floor ---------
            hip = hips_p + hips_t @ (sk.rest_head[f"thigh_{side}"] - sk.rest_head["hips"])
            fo, ff, fu = p[f"leg_{side}.at"]
            ankle = sk.rest_head[f"foot_{side}"] + Vector((s * fo, -ff, fu)) * H
            yaw = Matrix.Rotation(math.radians(s * p[f"leg_{side}.yaw"]), 3, "Z")
            knee_pole = yaw @ Vector((0, -1, 0.15))
            l1, l2 = sk.length[f"thigh_{side}"], sk.length[f"shin_{side}"]
            knee, ankle = two_bone_ik(hip, ankle, l1, l2, knee_pole)
            rest_foot = sk.defs[f"foot_{side}"]
            foot_dir = (rest_foot.tail - rest_foot.head).normalized()
            toe = Matrix.Rotation(math.radians(-p[f"leg_{side}.toe"]), 3, "X")
            controls[f"thigh_{side}"] = {"aim": knee - hip, "ref": knee_pole}
            controls[f"shin_{side}"] = {"aim": ankle - knee, "ref": knee_pole}
            controls[f"foot_{side}"] = {"aim": yaw @ (toe @ foot_dir), "ref": Vector((0, 0, 1))}

        sk.apply(sk.solve(controls), frame)
        self._pose_face(p, frame)

    def _pose_face(self, p: dict, frame: int | None) -> None:
        yaw, pitch = p["gaze"]
        yaw = max(-38.0, min(38.0, yaw))
        pitch = max(-28.0, min(28.0, pitch))
        for eye in self.eyes:
            pivot = eye["pivot"]
            pivot.rotation_euler = (math.radians(-pitch), 0.0, math.radians(yaw))
            if frame is not None:
                pivot.keyframe_insert("rotation_euler", frame=frame)
        for side in ("l", "r"):
            if self.swap_state.get(f"lid_{side}") != p["lids"] or frame is not None:
                self.swap(f"lid_{side}", p["lids"], frame)
        for brow in self.brows:
            holder = brow["holder"]
            cock = max(-1.0, min(1.0, p["brows.cock"]))
            dz = (p["brows.raise"]*.5 + abs(cock)*.20 + brow["sign"]*cock*.55)*brow["r"]
            # A brow translated only in Z sinks into the curved forehead when
            # lowered. Follow the actual head surface to keep asymmetry readable.
            x = self.face.center.x+brow["rest"].x
            z = self.face.center.z+brow["rest"].z
            dz = min(dz,self.face.radii.z*.89+self.face.center.z-z)
            y = self.face.surface_at(x,z+dz).y-brow["r"]*.22
            eye = brow["eye_center"]
            above = z+dz-eye.z
            if abs(above)<brow["r"]*1.15:
                y = min(y,eye.y-math.sqrt((brow["r"]*1.15)**2-above**2)-brow["r"]*.20)
            holder.location = Vector((brow["rest"].x,y-self.face.center.y,z+dz-self.face.center.z))
            holder.rotation_euler = (0.0, math.radians(-brow["sign"] * p["brows.tilt"]), 0.0)
            if frame is not None:
                holder.keyframe_insert("location", frame=frame)
                holder.keyframe_insert("rotation_euler", frame=frame)
        if p.get("mouth"):
            self.set_mouth(p["mouth"], frame)

    def set_mouth(self, shape: str, frame: int | None = None) -> None:
        """Show a mouth. 'X' (rest) shows the current expression mouth."""
        if shape == "X":
            shape = self.face.expression
        elif shape in face_parts.EXPRESSIONS:
            self.face.expression = shape
        elif shape in face_parts.VISEMES:
            mood = face_parts.MOOD_OF.get(self.face.expression, "flat")
            if mood != "flat":
                shape = f"{shape}_{mood}"
        self.swap("mouth", shape, frame)


def build(name: str, spec: dict) -> Biped:
    return Biped(name, spec)
