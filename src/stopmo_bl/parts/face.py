"""Face kit: head, stuck-on eyes with sliding pupils, replacement lids, brows and mouths.

Everything is laid out in FACE COORDINATES so one layout works on any head:

    u = across the face, -1 (puppet's right) .. +1 (puppet's left)
    v = up the face,     -1 (chin) .. +1 (crown)

Parts are built flat in (x, z) metres around an anchor and then wrapped onto
the actual head surface, so they follow whatever lumps the head has.
"""
from __future__ import annotations

import math

import bmesh
import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

from .. import util

# Rhubarb mouth shapes -> generator parameters (fractions of mouth width).
#   open: opening height      curve: corner lift (+ smile)     width: scale
#   top/bottom: teeth rows    tongue: show tongue              round: 1 = circle
VISEMES = {
    "A": dict(open=0.0, width=0.82),  # closed lips: P, B, M
    "B": dict(open=0.16, width=1.0, top=True, bottom=True),  # clenched: K, S, T
    "C": dict(open=0.34, width=0.95, top=True),  # open: EH, AE
    "D": dict(open=0.58, width=0.9, top=True, tongue=True),  # wide open: AA
    "E": dict(open=0.36, width=0.68, top=True, round=0.5),  # rounded: AO, ER
    "F": dict(open=0.24, width=0.36, round=1.0),  # pucker: UW, OW, W
    "G": dict(open=0.22, width=0.78, top=True, bite=True, curve=-0.03),  # teeth on lip: F, V
    "H": dict(open=0.40, width=0.85, top=True, tongue=True, tongue_up=True),  # L
}
EXPRESSIONS = {
    "neutral": dict(open=0.0, width=0.8, curve=0.03),
    "smile": dict(open=0.0, width=1.0, curve=0.16),
    "frown": dict(open=0.0, width=0.8, curve=-0.14),
    "grin": dict(open=0.26, width=1.12, curve=0.13, smile=0.7, top=True),
    "oh": dict(open=0.34, width=0.38, round=1.0),
    "gasp": dict(open=0.62, width=0.6, round=0.7, top=True, tongue=True),
    "flat": dict(open=0.0, width=0.8, curve=0.0),
    "small_smile": dict(open=0.0, width=0.70, curve=0.10),
    "chew_l": dict(open=0.0, width=0.68, curve=-0.025),
    "chew_r": dict(open=0.0, width=0.95, curve=0.055),
}


# speech mood -> (corner lift, smile shape)
MOODS = {"up": (0.1, 0.8), "flat": (0.02, 0.2), "down": (-0.08, -0.65)}
MOOD_OF = {"smile": "up", "small_smile": "up", "grin": "up", "frown": "down"}  # expression mouth -> speech mood


class Face:
    def __init__(self, puppet, head_obj, center: Vector, radii: Vector):
        self.puppet = puppet
        self.center = Vector(center)
        self.radii = Vector(radii)
        bm = bmesh.new()
        bm.from_mesh(head_obj.data)
        self.bvh = BVHTree.FromBMesh(bm)
        bm.free()
        self.mouth_width = 0.0
        self.mouth_anchor = Vector()
        self.expression = "neutral"

    # ---------------------------------------------------------- surface ----
    def surface_at(self, x: float, z: float) -> Vector:
        """Front surface point of the head at body-space (x, z)."""
        origin = Vector((x, self.center.y - self.radii.y * 4.0, z))
        hit, _n, _i, _d = self.bvh.ray_cast(origin, Vector((0, 1, 0)))
        if hit is not None:
            return hit
        # off the silhouette: fall back to the head's ellipsoid edge plane
        return Vector((x, self.center.y, z))

    def uv(self, u: float, v: float) -> Vector:
        return self.surface_at(self.center.x + u * self.radii.x, self.center.z + v * self.radii.z)

    def wrap(self, anchor: Vector, x: float, z: float, lift: float = 0.0) -> Vector:
        """Flat (x, z) offset from anchor -> point `lift` metres proud of the surface."""
        p = self.surface_at(anchor.x + x, anchor.z + z)
        return Vector((p.x, p.y - lift, p.z))

    def wrap_object(self, obj, anchor: Vector) -> None:
        """Bend a mesh built around the origin (x across, z up, -y = proud) onto the face."""
        for vert in obj.data.vertices:
            vert.co = self.wrap(anchor, vert.co.x, vert.co.z, -vert.co.y)
        obj.data.update()


# -------------------------------------------------------------- helpers ----
def _loop_tube(name, pts, radius, closed, segments=8):
    """Tube through 3D points whose rings face out of the face (-Y). No twist."""
    n = len(pts)
    bm = bmesh.new()
    rings = []
    out = Vector((0, -1, 0))
    for i in range(n):
        a = pts[(i - 1) % n] if closed else pts[max(i - 1, 0)]
        b = pts[(i + 1) % n] if closed else pts[min(i + 1, n - 1)]
        t = (b - a).normalized()
        side = t.cross(out).normalized()
        nrm = side.cross(t).normalized()
        r = radius
        if not closed:  # taper the ends of a crease line
            edge = min(i, n - 1 - i) / max(n * 0.18, 1)
            r = radius * (0.35 + 0.65 * min(edge, 1.0))
        rings.append(
            [
                bm.verts.new(pts[i] + (nrm * math.cos(2 * math.pi * s / segments) + side * math.sin(2 * math.pi * s / segments)) * r)
                for s in range(segments)
            ]
        )
    pairs = list(zip(rings, rings[1:] + rings[:1])) if closed else list(zip(rings[:-1], rings[1:]))
    for a, b in pairs:
        for s in range(segments):
            s2 = (s + 1) % segments
            bm.faces.new((a[s], a[s2], b[s2], b[s]))
    if not closed:
        bm.faces.new(list(reversed(rings[0])))
        bm.faces.new(rings[-1])
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    obj = util.new_mesh_object(name, bm)
    util.shade_smooth(obj)
    return obj


def _outline(width, open_h, curve, roundness, smile=0.0, count=32):
    """Mouth opening outline as flat (x, z) points, counter-clockwise from the right corner.

    smile  +1: flat top lip and a deep U below, corners highest (cheerful talking mouth)
           -1: flat bottom and an arch above (unhappy);  0: symmetric.
    curve  extra lift of the corners, as a fraction of the width.
    """
    half_w = width / 2
    half_h = max(open_h / 2, 1e-6)
    smile *= 1.0 - roundness  # puckered shapes stay round
    top_h = half_h * (1.0 - 0.72 * smile)
    bot_h = half_h * (1.0 + 0.72 * smile)
    base = 0.7 + 0.3 * roundness  # <1 = squarer; the long side of a smile is a clean ellipse
    pts = []
    for i in range(count):
        a = 2 * math.pi * i / count
        c, s = math.cos(a), math.sin(a)
        if s >= 0:
            exp_x = base if smile >= 0 else 1.0
            z = top_h * (abs(s) ** (base if smile >= 0 else 1.0))
        else:
            exp_x = 1.0 if smile > 0 else base
            z = -bot_h * (abs(s) ** (1.0 if smile > 0 else base))
        x = half_w * math.copysign(abs(c) ** exp_x, c)
        z += curve * width * (x / half_w) ** 2  # lift the corners
        z -= (top_h - bot_h) / 2  # keep the opening centred on the anchor
        pts.append((x, z))
    return pts


# ----------------------------------------------------------------- head ----
def build_head(puppet, spec: dict, bone: str = "head"):
    """Fused clay head (skull + cheeks + nose + ears + chin) -> (head object, Face)."""
    H = puppet.scale
    skel = puppet.skel
    radii = Vector(spec.get("size", (0.17, 0.16, 0.19))) * H
    base = skel.rest_head[bone]
    center = Vector(base) + Vector((0, 0, radii.z * spec.get("neck_overlap", 0.82)))
    lumps = [util.ellipsoid("skull", radii, center, subdiv=4)]

    def add(name, size, uvw):
        """size and position in head-radius units; w = depth (-1 front .. +1 back)."""
        pos = center + Vector((uvw[0] * radii.x, uvw[2] * radii.y, uvw[1] * radii.z))
        lumps.append(util.ellipsoid(name, Vector(size) * radii.x, pos, subdiv=3))

    for feat in spec.get("lumps", []):
        add(feat.get("name", "lump"), feat["size"], feat["at"])
        if feat.get("mirror"):
            u, v, w = feat["at"]
            add(feat.get("name", "lump") + "_m", feat["size"], (-u, v, w))
    nose = spec.get("nose")
    if nose:
        add("nose", nose.get("size", (0.26, 0.3, 0.24)), nose.get("at", (0, -0.02, -0.98)))
    ears = spec.get("ears")
    if ears:
        size = ears.get("size", (0.1, 0.2, 0.32))
        u, v, w = ears.get("at", (1.0, 0.05, 0.1))
        add("ear_l", size, (u, v, w))
        add("ear_r", size, (-u, v, w))

    head = util.join(lumps, f"{puppet.name}_head")
    util.remesh(head, voxel=radii.x / 34, smooth_iters=8, smooth_factor=0.7)
    color = spec.get("color", puppet.spec.get("skin", "#E8B08A"))
    puppet.finish(head, "skin", color, bone=bone, lumpy=spec.get("lumpy", 0.7))
    face = Face(puppet, head, center, radii)
    puppet.face = face
    puppet.socket("face", bone, center)
    return head, face


# ----------------------------------------------------------------- eyes ----
def build_eyes(puppet, face: Face, spec: dict):
    """Bulging bead eyes with sliding pupils and replacement lids."""
    r = spec.get("size", 0.3) * face.radii.x
    spread = spec.get("spread", 0.3)
    v = spec.get("height", 0.3)
    sink = spec.get("sink", 0.3)  # fraction of the radius buried in the head
    skin = puppet.spec.get("skin", "#E8B08A")
    lid_color = spec.get("lid_color", skin)
    for side, sign in (("l", 1), ("r", -1)):
        surf = face.uv(sign * spread, v)
        c = surf + Vector((0, r * sink, 0))
        ball = util.ellipsoid(f"{puppet.name}_eye_{side}", (r, r, r), c, subdiv=4)
        puppet.stick(ball, "face", "eye", spec.get("white", "#F4F1E8"))

        pivot = bpy.data.objects.new(f"{puppet.name}_gaze_{side}", None)
        pivot.empty_display_size = 0.003
        util.link(pivot, puppet.col)
        pivot.parent = puppet.sockets["face"]
        pivot.location = c - face.center
        pr = spec.get("pupil", 0.26) * r
        pupil = util.ellipsoid(f"{puppet.name}_pupil_{side}", (pr, pr * 0.45, pr), (0, -r * 0.985, 0), subdiv=3)
        for col in list(pupil.users_collection):
            col.objects.unlink(pupil)
        puppet.col.objects.link(pupil)
        pupil.parent = pivot
        util.set_material(pupil, puppet.style.material("pupil", spec.get("pupil_color", "#0B0B0D")))

        # replacement lids: skin shells cut at different heights
        for variant, cut in (("open", 0.62), ("half", 0.05), ("closed", None), ("wide", 0.9)):
            # Pupils stand proud of the eye by .45*pupil_radius. A 1.07r
            # closed shell lets their black tips poke through; cover that depth.
            shell = 1.20 if cut is None else 1.07
            lid = util.ellipsoid(f"{puppet.name}_lid_{side}_{variant}", (r * shell,) * 3, (0, 0, 0), subdiv=3)
            if cut is not None:
                bm = bmesh.new()
                bm.from_mesh(lid.data)
                tilt = Matrix.Rotation(math.radians(-18), 3, "X")  # lids hang over the front
                normal = tilt @ Vector((0, 0, 1))
                bmesh.ops.bisect_plane(
                    bm,
                    geom=list(bm.verts) + list(bm.edges) + list(bm.faces),
                    plane_co=normal * (cut * r * 1.07),
                    plane_no=normal,
                    clear_inner=True,
                )
                bm.to_mesh(lid.data)
                bm.free()
            lid.data.transform(Matrix.Translation(c))
            util.shade_smooth(lid)
            puppet.stick(lid, "face", "skin", lid_color, lumpy=0.0, prints=0.4)
            objs = [lid]
            if cut is None:  # closed: a little lash crease so it reads as shut
                arc = [
                    c + Vector((math.sin(a) * r * 1.22, -math.cos(a) * r * 1.22 * math.cos(0.3), -r * 1.22 * math.sin(0.3) * math.cos(a)))
                    for a in [math.radians(d) for d in range(-60, 61, 15)]
                ]
                crease = _loop_tube(f"{puppet.name}_lash_{side}", arc, r * 0.05, closed=False, segments=6)
                puppet.stick(crease, "face", "mouth", spec.get("lash_color", "#3A2A22"))
                objs.append(crease)
            puppet.add_swap(f"lid_{side}", variant, objs)
        puppet.swap(f"lid_{side}", "open")
        puppet.eyes.append({"side": side, "pivot": pivot, "center": c, "radius": r})

    brow = spec.get("brows")
    if brow is not None:
        color = brow.get("color", puppet.spec.get("hair", "#5A3A22"))
        if "color" not in brow:
            rgb = util.hex_rgb(color)
            if max(rgb[:3]) > .3:
                color = tuple(c*.38 for c in rgb[:3])  # readable grey brows on a pale forehead
        for eye in puppet.eyes:
            sign = 1 if eye["side"] == "l" else -1
            c, r = eye["center"], eye["radius"]
            anchor = Vector((c.x, 0, c.z + r * brow.get("lift", .65)))
            half = r * brow.get("length", 1.15) / 2
            pts = [
                face.wrap(anchor, sign * (t * half), -abs(t) * r * 0.12, lift=r * 0.1)
                for t in (-1.0, -0.5, 0.0, 0.5, 1.0)
            ]
            holder = bpy.data.objects.new(f"{puppet.name}_brow_{eye['side']}", None)
            holder.empty_display_size = 0.003
            util.link(holder, puppet.col)
            holder.parent = puppet.sockets["face"]
            mid = pts[2]
            holder.location = mid - face.center
            obj = _loop_tube(f"{puppet.name}_browmesh_{eye['side']}", [p - mid for p in pts], r * brow.get("thick", 0.13), closed=False)
            for col in list(obj.users_collection):
                col.objects.unlink(obj)
            puppet.col.objects.link(obj)
            obj.parent = holder
            from ..materials.nodes import store_rest

            store_rest(obj)
            util.set_material(obj, puppet.style.material("hair", color))
            puppet.brows.append({"side": eye["side"], "holder": holder, "rest": holder.location.copy(),
                                 "r": r, "sign": sign, "eye_center": c.copy()})


# --------------------------------------------------------------- mouths ----
def _mouth(puppet, face: Face, name: str, p: dict, colors: dict):
    """One replacement mouth -> list of objects (lips/crease, cavity, teeth, tongue)."""
    W = face.mouth_width * p.get("width", 1.0)
    anchor = face.mouth_anchor
    open_h = p.get("open", 0.0) * face.mouth_width
    curve = p.get("curve", 0.0)
    lip_r = face.mouth_width * 0.055
    objs = []
    tag = f"{puppet.name}_mouth_{name}"

    if open_h <= 1e-6:  # closed: a pressed crease line
        pts = []
        for i in range(13):
            t = i / 12 * 2 - 1
            pts.append(face.wrap(anchor, t * W / 2, curve * W * t * t, lift=lip_r * 0.25))
        crease = _loop_tube(tag + "_crease", pts, lip_r * 0.62, closed=False)
        puppet.stick(crease, "face", "mouth", colors["crease"])
        return [crease]

    outline = _outline(W, open_h, curve, p.get("round", 0.0), p.get("smile", 0.0))
    ring_pts = [face.wrap(anchor, x, z, lift=lip_r * 0.55) for x, z in outline]
    lips = _loop_tube(tag + "_lips", ring_pts, lip_r, closed=True)
    puppet.stick(lips, "face", "skin", colors["lips"], prints=0.3)
    objs.append(lips)

    # dark cavity: fan just proud of the face so it reads as a hole
    bm = bmesh.new()
    cx = sum(x for x, _ in outline) / len(outline)
    cz = sum(z for _, z in outline) / len(outline)
    # concentric rings, each wrapped, so the patch follows the curve of the face
    lift = lip_r * 0.3
    centre = bm.verts.new(face.wrap(anchor, cx, cz, lift=lift))
    rings_n = 6
    rings = [
        [bm.verts.new(face.wrap(anchor, cx + (x - cx) * k / rings_n, cz + (z - cz) * k / rings_n, lift=lift)) for x, z in outline]
        for k in range(1, rings_n + 1)
    ]
    count = len(outline)
    for i in range(count):
        bm.faces.new((centre, rings[0][i], rings[0][(i + 1) % count]))
    for inner, outer in zip(rings[:-1], rings[1:]):
        for i in range(count):
            j = (i + 1) % count
            bm.faces.new((inner[i], outer[i], outer[j], inner[j]))
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    cavity = util.new_mesh_object(tag + "_cavity", bm)
    if cavity.data.polygons and cavity.data.polygons[0].normal.y > 0:
        cavity.data.flip_normals()
    puppet.stick(cavity, "face", "mouth", colors["cavity"])
    objs.append(cavity)

    def z_edges(x):
        """Top and bottom of the opening at flat x."""
        zs = [z for (ox, z) in outline if abs(ox - x) < W / 9] or [cz]
        return max(zs), min(zs)

    def tooth_row(top: bool, suffix: str):
        count = max(3, int(round(6 * p.get("width", 1.0))))
        span = W * 0.8
        tw = span / count
        th = min(open_h * (0.5 if p.get("bottom") and p.get("top") else 0.5), face.mouth_width * 0.2)
        if p.get("bite") and top:
            th = open_h * 0.8
        teeth = []
        for i in range(count):
            x = -span / 2 + tw * (i + 0.5)
            hi, lo = z_edges(x)
            zc = (hi - th / 2 - lip_r * 0.2) if top else (lo + th / 2 + lip_r * 0.2)
            tooth = util.rounded_box("t", (tw * 0.9, lip_r * 0.5, th), (x, -lip_r * 0.62, zc), bevel=0.3, segments=2)
            face.wrap_object(tooth, anchor)
            teeth.append(tooth)
        row = util.join(teeth, tag + suffix)
        puppet.stick(row, "face", "teeth", colors["teeth"])
        objs.append(row)

    if p.get("top"):
        tooth_row(True, "_teeth_top")
    if p.get("bottom"):
        tooth_row(False, "_teeth_bot")
    if p.get("tongue"):
        hi, lo = z_edges(0.0)
        tz = (hi - open_h * 0.3) if p.get("tongue_up") else (lo + open_h * 0.22)
        tongue = util.ellipsoid("tg", (W * 0.24, lip_r * 0.4, open_h * 0.2), (0, -lip_r * 0.42, tz), subdiv=3)
        face.wrap_object(tongue, anchor)
        tongue.name = tag + "_tongue"
        puppet.stick(tongue, "face", "mouth", colors["tongue"], sss=0.4)
        objs.append(tongue)
    return objs


def build_mouths(puppet, face: Face, spec: dict):
    """Full replacement set: 8 speech shapes + expressions. 'X' (rest) follows the expression."""
    face.mouth_width = spec.get("width", 0.85) * face.radii.x
    face.mouth_anchor = Vector(
        (face.center.x, 0, face.center.z + spec.get("height", -0.42) * face.radii.z)
    )
    skin = puppet.spec.get("skin", "#E8B08A")
    r, g, b, _ = util.hex_rgb(skin)
    colors = {
        "lips": spec.get("lips", skin),
        "crease": spec.get("crease", (r * 0.28, g * 0.2, b * 0.18)),
        "cavity": spec.get("cavity", "#3A0F12"),
        "teeth": spec.get("teeth", "#F3EEDC"),
        "tongue": spec.get("tongue", "#C4505A"),
    }
    shapes = {**VISEMES, **EXPRESSIONS}
    # speech shapes in three moods, so a happy line is spoken through a smile
    for mood, lift in MOODS.items():
        for name, params in VISEMES.items():
            key = name if mood == "flat" else f"{name}_{mood}"
            shapes[key] = {**params, "curve": params.get("curve", 0.0) + lift[0], "smile": lift[1]}
    shapes.update(spec.get("shapes", {}))
    for name, params in shapes.items():
        puppet.add_swap("mouth", name, _mouth(puppet, face, name, params, colors))
    face.expression = spec.get("rest", "neutral")
    puppet.swap("mouth", face.expression)
