"""Low-level Blender helpers shared by every stopmo_bl module.

Scale convention: 1 Blender unit = 1 metre, and puppets are built at real
miniature scale (a humanoid is ~0.25 m tall). That makes depth of field and
subsurface scattering behave like a real tabletop set without any faking.
"""
from __future__ import annotations

import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector


# ---------------------------------------------------------------- scene ----
def reset_scene() -> bpy.types.Scene:
    """Start from an empty file with one empty scene."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    return scene


def collection(name: str, parent: bpy.types.Collection | None = None) -> bpy.types.Collection:
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
        (parent or bpy.context.scene.collection).children.link(col)
    return col


def link(obj: bpy.types.Object, col: bpy.types.Collection | None = None) -> bpy.types.Object:
    (col or bpy.context.scene.collection).objects.link(obj)
    return obj


def hex_rgb(value) -> tuple[float, float, float, float]:
    """'#RRGGBB' (sRGB) or an (r, g, b) tuple -> linear RGBA."""
    if isinstance(value, (tuple, list)):
        r, g, b = value[:3]
        return (r, g, b, 1.0)
    value = value.lstrip("#")
    srgb = [int(value[i : i + 2], 16) / 255.0 for i in (0, 2, 4)]

    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    return (lin(srgb[0]), lin(srgb[1]), lin(srgb[2]), 1.0)


def rng(seed) -> random.Random:
    return random.Random(str(seed))


# ----------------------------------------------------------------- mesh ----
def new_mesh_object(name: str, bm: bmesh.types.BMesh, col=None) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    link(obj, col)
    return obj


def shade_smooth(obj: bpy.types.Object) -> None:
    for poly in obj.data.polygons:
        poly.use_smooth = True


def ellipsoid(name, radii=(1, 1, 1), location=(0, 0, 0), subdiv=3, col=None) -> bpy.types.Object:
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=subdiv, radius=1.0)
    bmesh.ops.scale(bm, vec=Vector(radii), verts=bm.verts)
    bmesh.ops.translate(bm, vec=Vector(location), verts=bm.verts)
    obj = new_mesh_object(name, bm, col)
    shade_smooth(obj)
    return obj


def rounded_box(name, size=(1, 1, 1), location=(0, 0, 0), bevel=0.2, segments=4, col=None):
    """Box with bevelled edges. `bevel` is a fraction of the smallest side."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=Vector(size), verts=bm.verts)
    width = min(size) * bevel
    if width > 0:
        bmesh.ops.bevel(
            bm, geom=list(bm.edges), offset=width, segments=segments, profile=0.5, affect="EDGES"
        )
    bmesh.ops.translate(bm, vec=Vector(location), verts=bm.verts)
    obj = new_mesh_object(name, bm, col)
    shade_smooth(obj)
    return obj


def cylinder(name, radius=1.0, depth=1.0, location=(0, 0, 0), segments=24, radius_top=None, col=None):
    bm = bmesh.new()
    bmesh.ops.create_cone(
        bm,
        cap_ends=True,
        cap_tris=False,
        segments=segments,
        radius1=radius,
        radius2=radius if radius_top is None else radius_top,
        depth=depth,
    )
    bmesh.ops.translate(bm, vec=Vector(location), verts=bm.verts)
    obj = new_mesh_object(name, bm, col)
    return obj


def tube(name, points, radii, segments=14, cap=True, col=None) -> bpy.types.Object:
    """Swept tube through `points` with a radius per point (a clay 'sausage').

    Rings are oriented with a parallel-transport frame so the tube does not
    twist. Ends are closed with rounded caps so it reads as rolled clay.
    """
    pts = [Vector(p) for p in points]
    n = len(pts)
    tangents = []
    for i in range(n):
        a = pts[max(i - 1, 0)]
        b = pts[min(i + 1, n - 1)]
        tangents.append((b - a).normalized())
    # initial frame
    t0 = tangents[0]
    ref = Vector((0, 0, 1)) if abs(t0.z) < 0.9 else Vector((1, 0, 0))
    u = t0.cross(ref).normalized()
    frames = []
    for i in range(n):
        t = tangents[i]
        if i > 0:
            # parallel transport
            prev_t = tangents[i - 1]
            axis = prev_t.cross(t)
            if axis.length > 1e-8:
                angle = prev_t.angle(t)
                u = Matrix.Rotation(angle, 3, axis.normalized()) @ u
        u = (u - t * u.dot(t)).normalized()
        v = t.cross(u).normalized()
        frames.append((u.copy(), v))

    bm = bmesh.new()
    rings = []

    def add_ring(center, u_, v_, r):
        ring = []
        for s in range(segments):
            a = 2 * math.pi * s / segments
            ring.append(bm.verts.new(center + (u_ * math.cos(a) + v_ * math.sin(a)) * r))
        return ring

    cap_steps = 4 if cap else 0
    # start cap (hemisphere going backwards along the tangent)
    for k in range(cap_steps, 0, -1):
        phi = (math.pi / 2) * k / cap_steps
        r = radii[0] * math.cos(phi)
        off = -tangents[0] * radii[0] * math.sin(phi)
        rings.append(add_ring(pts[0] + off, frames[0][0], frames[0][1], max(r, radii[0] * 0.05)))
    for i in range(n):
        rings.append(add_ring(pts[i], frames[i][0], frames[i][1], radii[i]))
    for k in range(1, cap_steps + 1):
        phi = (math.pi / 2) * k / cap_steps
        r = radii[-1] * math.cos(phi)
        off = tangents[-1] * radii[-1] * math.sin(phi)
        rings.append(add_ring(pts[-1] + off, frames[-1][0], frames[-1][1], max(r, radii[-1] * 0.05)))

    for a, b in zip(rings[:-1], rings[1:]):
        for s in range(segments):
            s2 = (s + 1) % segments
            bm.faces.new((a[s], a[s2], b[s2], b[s]))
    if cap:
        bm.faces.new(list(reversed(rings[0])))
        bm.faces.new(rings[-1])
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    obj = new_mesh_object(name, bm, col)
    shade_smooth(obj)
    return obj


# ------------------------------------------------------------ operators ----
def _activate(obj: bpy.types.Object) -> None:
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def apply_transforms(obj: bpy.types.Object) -> None:
    """Bake the object's matrix into its mesh data (no operator needed)."""
    obj.data.transform(obj.matrix_basis)
    obj.matrix_basis = Matrix.Identity(4)


def apply_modifiers(obj: bpy.types.Object) -> None:
    """Bake every modifier into the mesh data."""
    deps = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(deps)
    mesh = bpy.data.meshes.new_from_object(evaluated, depsgraph=deps)
    old = obj.data
    obj.modifiers.clear()
    obj.data = mesh
    mesh.name = old.name
    if old.users == 0:
        bpy.data.meshes.remove(old)


def join(objects: list[bpy.types.Object], name: str | None = None) -> bpy.types.Object:
    """Join meshes into the first object (transforms are baked first)."""
    base = objects[0]
    bm = bmesh.new()
    for obj in objects:
        tmp = bmesh.new()
        tmp.from_mesh(obj.data)
        tmp.transform(obj.matrix_world)
        mesh = bpy.data.meshes.new("_tmp")
        tmp.to_mesh(mesh)
        tmp.free()
        bm.from_mesh(mesh)
        bpy.data.meshes.remove(mesh)
    for obj in objects[1:]:
        data = obj.data
        bpy.data.objects.remove(obj)
        if data.users == 0:
            bpy.data.meshes.remove(data)
    bm.to_mesh(base.data)
    bm.free()
    base.matrix_world = Matrix.Identity(4)
    if name:
        base.name = name
        base.data.name = name
    shade_smooth(base)
    return base


def remesh(obj: bpy.types.Object, voxel: float, smooth_iters: int = 6, smooth_factor: float = 0.6):
    """Fuse overlapping volumes into one skin, like pressing clay lumps together."""
    mod = obj.modifiers.new("fuse", "REMESH")
    mod.mode = "VOXEL"
    mod.voxel_size = voxel
    mod.use_smooth_shade = True
    if smooth_iters:
        sm = obj.modifiers.new("soften", "SMOOTH")
        sm.iterations = smooth_iters
        sm.factor = smooth_factor
    apply_modifiers(obj)
    shade_smooth(obj)
    return obj


def lumpify(obj: bpy.types.Object, strength: float, scale: float, seed=0) -> None:
    """Hand-made irregularity: push vertices along normals by smooth noise."""
    from mathutils import noise

    r = rng(seed)
    offset = Vector((r.uniform(-50, 50), r.uniform(-50, 50), r.uniform(-50, 50)))
    mesh = obj.data
    count = len(mesh.vertices)
    co = [0.0] * (count * 3)
    nrm = [0.0] * (count * 3)
    # read everything first: touching v.normal after moving a vertex recomputes ALL normals
    mesh.vertices.foreach_get("co", co)
    mesh.vertices.foreach_get("normal", nrm)
    for i in range(0, count * 3, 3):
        n = noise.noise(Vector((co[i] / scale, co[i + 1] / scale, co[i + 2] / scale)) + offset) * strength
        co[i] += nrm[i] * n
        co[i + 1] += nrm[i + 1] * n
        co[i + 2] += nrm[i + 2] * n
    mesh.vertices.foreach_set("co", co)
    mesh.update()


def subdivide_smooth(obj: bpy.types.Object, levels: int = 1) -> None:
    mod = obj.modifiers.new("subd", "SUBSURF")
    mod.levels = levels
    mod.render_levels = levels
    apply_modifiers(obj)
    shade_smooth(obj)


def parent_keep(child: bpy.types.Object, parent: bpy.types.Object, bone: str | None = None) -> None:
    """Parent `child` to `parent` (optionally to a bone) without moving it."""
    bpy.context.view_layer.update()
    world = child.matrix_world.copy()
    child.parent = parent
    if bone:
        child.parent_type = "BONE"
        child.parent_bone = bone
    bpy.context.view_layer.update()
    child.matrix_world = world
    # matrix_world assignment resolves parent inverse on next update
    bpy.context.view_layer.update()


def set_material(obj: bpy.types.Object, material: bpy.types.Material) -> None:
    obj.data.materials.clear()
    obj.data.materials.append(material)
