"""Render settings, camera and lighting rigs for a tabletop miniature set."""
from __future__ import annotations

import math

import bpy
from mathutils import Vector

from .util import hex_rgb, link

QUALITY = {
    # name: (cycles samples, resolution scale %)
    # Measure representative exposures locally before estimating a full render.
    "draft": (24, 50),
    "preview": (32, 100),
    "final": (96, 100),
}


def setup_render(
    scene,
    *,
    engine="CYCLES",
    quality="preview",
    resolution=(1920, 1080),
    fps=12,
    samples=None,
    film_look=True,
):
    """Configure the renderer. `fps` is exposures per second (12 = 'on twos')."""
    preset_samples, scale = QUALITY[quality]
    samples = samples or preset_samples
    r = scene.render
    r.resolution_x, r.resolution_y = resolution
    r.resolution_percentage = scale
    r.fps = fps
    r.image_settings.file_format = "PNG"
    r.image_settings.color_mode = "RGB"
    r.use_motion_blur = False  # stop motion has none: every exposure is a still
    r.film_transparent = False

    if engine == "CYCLES":
        r.engine = "CYCLES"
        prefs = bpy.context.preferences.addons["cycles"].preferences
        try:
            prefs.compute_device_type = "METAL"
            prefs.get_devices()
            for dev in prefs.devices:
                dev.use = dev.type == "METAL"
            scene.cycles.device = "GPU" if any(dev.use for dev in prefs.devices) else "CPU"
        except Exception:  # no GPU backend: fall back to CPU
            scene.cycles.device = "CPU"
        c = scene.cycles
        c.samples = samples
        c.use_adaptive_sampling = True
        c.adaptive_threshold = 0.03
        c.use_denoising = True
        try:
            c.denoising_use_gpu = scene.cycles.device == "GPU"
        except AttributeError:
            pass
        c.max_bounces = 6
        c.diffuse_bounces = 3
        c.glossy_bounces = 3
        c.transmission_bounces = 4
        c.caustics_reflective = False
        c.caustics_refractive = False
        scene.render.use_persistent_data = True  # keep BVH/shaders between frames
    else:
        r.engine = "BLENDER_EEVEE"
        scene.eevee.taa_render_samples = max(16, samples // 2)
        scene.eevee.use_raytracing = True
        scene.eevee.use_shadows = True

    if film_look:
        from . import style  # the active style picks the film response: "agx" (filmic) or "standard" (true colours)

        vs = scene.view_settings
        if style.active().spec.get("view", "agx") == "standard":
            vs.view_transform = "Standard"
            vs.look = "None"
        else:
            vs.view_transform = "AgX"
            try:
                vs.look = "AgX - Medium High Contrast"
            except TypeError:
                pass
        vs.exposure = 0.0
    return scene


def look_at(obj, target, roll=0.0):
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    obj.rotation_euler.rotate_axis("Z", roll)


def add_camera(scene, location, target, *, lens=50.0, fstop=4.0, focus=None, name="camera"):
    """Camera with real depth of field. `focus` is a point (defaults to target)."""
    cam = bpy.data.cameras.new(name)
    cam.lens = lens
    cam.sensor_width = 36.0
    cam.clip_start = 0.01
    cam.clip_end = 50.0
    obj = bpy.data.objects.new(name, cam)
    link(obj)
    obj.location = location
    look_at(obj, target)
    focus_obj = bpy.data.objects.new(name + "_focus", None)
    focus_obj.empty_display_size = 0.01
    link(focus_obj)
    focus_obj.location = focus if focus is not None else target
    cam.dof.use_dof = True
    cam.dof.focus_object = focus_obj
    cam.dof.aperture_fstop = fstop
    scene.camera = obj
    return obj, focus_obj


def area_light(name, location, target, *, power=20.0, size=0.3, color="#FFFFFF", size_y=None):
    light = bpy.data.lights.new(name, "AREA")
    light.energy = power
    light.color = hex_rgb(color)[:3]
    light.size = size
    if size_y:
        light.shape = "RECTANGLE"
        light.size_y = size_y
    obj = bpy.data.objects.new(name, light)
    link(obj)
    obj.location = location
    look_at(obj, target)
    return obj


def spot_light(name, location, target, *, power=30.0, angle=50.0, blend=0.4, color="#FFFFFF", radius=0.02):
    light = bpy.data.lights.new(name, "SPOT")
    light.energy = power
    light.color = hex_rgb(color)[:3]
    light.spot_size = math.radians(angle)
    light.spot_blend = blend
    light.shadow_soft_size = radius
    obj = bpy.data.objects.new(name, light)
    link(obj)
    obj.location = location
    look_at(obj, target)
    return obj


def set_world(scene, color="#20242B", strength=0.3):
    world = bpy.data.worlds.new("world")
    scene.world = world
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg is None:
        world.node_tree.nodes.clear()
        bg = world.node_tree.nodes.new("ShaderNodeBackground")
        out = world.node_tree.nodes.new("ShaderNodeOutputWorld")
        world.node_tree.links.new(bg.outputs[0], out.inputs[0])
    bg.inputs["Color"].default_value = hex_rgb(color)
    bg.inputs["Strength"].default_value = strength
    return world


LIGHT_RIGS = {
    "interrogation": dict(
        world=("#09090D", .025),
        # `spread` (degrees) narrows an area lamp into a beam: a pool of light, the room falls dark
        key=dict(offset=(-.05,-.22,.75),power=7,size=.025,color="#FFE0AB",spread=36),
        fill=dict(offset=(.65,-.55,.30),power=.15,size=.65,color="#A1B4D5"),
        rim=dict(offset=(.35,.65,.65),power=4,size=.15,color="#E9E3D2",spread=70),
    ),
    "storm": dict(
        world=("#263A58", .12),
        key=dict(offset=(-.40,-.40,.85),power=10,size=.75,color="#A8BEE5"),
        fill=dict(offset=(.70,-.45,.40),power=1.5,size=.85,color="#708FBF"),
        rim=dict(offset=(.35,.65,.75),power=9,size=.5,color="#C5DBEF"),
    ),
    # Warm practical key, cool soft fill, hot rim: the cosy-kitchen-table look.
    "cosy": dict(
        world=("#2A2F3A", 0.1),
        key=dict(offset=(-0.70, -0.55, 0.70), power=50, size=0.2, color="#FFD9A6"),
        fill=dict(offset=(0.75, -0.60, 0.30), power=4.5, size=0.7, color="#B5CCFF"),
        rim=dict(offset=(0.45, 0.70, 0.70), power=42, size=0.2, color="#FFF1DC"),
    ),
    # Bright even daylight studio: children's-TV craft look.
    "bright": dict(
        world=("#C9D6E6", 0.9),
        key=dict(offset=(-0.5, -0.8, 0.9), power=30, size=0.8, color="#FFF6E8"),
        fill=dict(offset=(0.8, -0.6, 0.4), power=18, size=1.0, color="#EAF2FF"),
        rim=dict(offset=(0.2, 0.9, 0.7), power=16, size=0.5, color="#FFFFFF"),
    ),
    # A big soft light over a pale seamless backdrop: product-shot look, gentle contact shadows.
    "softbox": dict(
        world=("#FFFAF6", 0.64),   # a lot of light from all round: shadows stay pale, but each thing still casts one
        key=dict(offset=(-0.5, -0.5, 1.05), power=6.6, size=1.2, color="#FFFBF7"),
        fill=dict(offset=(0.85, -0.7, 0.45), power=2.0, size=1.6, color="#FFFFFF"),
        rim=dict(offset=(0.1, 0.5, 0.9), power=1.8, size=1.0, color="#FFFFFF"),
    ),
    # Low single source with deep shadows: spooky / noir.
    "moody": dict(
        world=("#0B0E16", 0.15),
        key=dict(offset=(-0.75, -0.35, 0.45), power=34, size=0.18, color="#FFC98A"),
        fill=dict(offset=(0.8, -0.6, 0.3), power=2.5, size=0.8, color="#7FA2FF"),
        rim=dict(offset=(0.4, 0.85, 0.7), power=40, size=0.2, color="#9FC0FF"),
    ),
}


def light_rig(scene, rig="cosy", *, center=(0, 0, 0.12), scale=1.0, power=1.0):
    """Three-point rig placed relative to `center` (where the action is)."""
    spec = LIGHT_RIGS[rig]
    set_world(scene, *spec["world"])
    c = Vector(center)
    lights = {}
    for role in ("key", "fill", "rim"):
        s = spec[role]
        # power scales with distance^2 so `scale` keeps exposure constant
        lights[role] = area_light(
            f"light_{role}",
            c + Vector(s["offset"]) * scale,
            c,
            power=s["power"] * power * scale * scale,
            size=s["size"] * scale,
            color=s["color"],
        )
        lights[role].data.spread = math.radians(s.get("spread", 180.0))
    return lights


def practical_light(name: str, kind: str, at, to, *, power=1., color="#FFFFFF", angle=50., size=.02):
    """Extra point/spot/area light; watts, degrees, and metre emitter size."""
    if kind == "area":
        return area_light(name,at,to,power=power,color=color,size=size)
    if kind == "spot":
        return spot_light(name,at,to,power=power,color=color,angle=angle,radius=size/2)
    if kind != "point":
        raise ValueError("light kind must be point, spot or area")
    data = bpy.data.lights.new(name,"POINT")
    data.energy, data.color, data.shadow_soft_size = power,hex_rgb(color)[:3],size/2
    obj = bpy.data.objects.new(name,data)
    link(obj)
    obj.location = at
    return obj
