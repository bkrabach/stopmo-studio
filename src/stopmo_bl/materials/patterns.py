"""Metre-scaled painted/craft patterns; importing registers the five recipes."""
from __future__ import annotations

from ..util import hex_rgb
from . import library
from .nodes import new_material, surface_coords


def _coords(g):
    return surface_coords(g, per_object_shift=0.0)


def _finish(g, shader, fac, color, color2, bump=0.0):
    g.set(shader, "Base Color", g.mix_color(fac, hex_rgb(color), hex_rgb(color2)))
    g.set(shader, "Roughness", 0.86)
    if bump:
        n = g.node("ShaderNodeBump", Height=fac, Strength=0.22, Distance=bump)
        g.set(shader, "Normal", n.outputs[0])


def stripes(name, color, color2="#F5E8BE", *, width=0.012, axis="X"):
    """Alternating painted bands; width is one stripe's width in metres."""
    if width <= 0 or axis not in ("X", "Y", "Z"):
        raise ValueError("positive stripe width and X/Y/Z axis required")
    mat, g, bsdf, _ = new_material(name)
    xyz = g.node("ShaderNodeSeparateXYZ", Vector=_coords(g))
    phase = g.math("FRACT", g.math("DIVIDE", xyz.outputs[axis], width * 2))
    fac = g.math("GREATER_THAN", phase, 0.5)
    _finish(g, bsdf, fac, color, color2)
    return mat


def checker(name, color, color2="#F2DFB5", *, size=0.025):
    """Two-dimensional XY checks; size is each square's side in metres."""
    if size <= 0:
        raise ValueError("checker size must be positive")
    mat, g, bsdf, _ = new_material(name)
    xyz = g.node("ShaderNodeSeparateXYZ", Vector=_coords(g))
    x = g.math("FLOOR", g.math("DIVIDE", xyz.outputs["X"], size))
    y = g.math("FLOOR", g.math("DIVIDE", xyz.outputs["Y"], size))
    fac = g.math("PINGPONG", g.math("ADD", x, y), 1.0)
    _finish(g, bsdf, fac, color, color2, 0.00012)
    return mat


def grass(name, color="#649247"):
    """Short craft-felt lawn: millimetre blades and centimetre dye mottling."""
    mat, g, bsdf, _ = new_material(name)
    co = _coords(g)
    fine = g.node("ShaderNodeTexNoise", Vector=g.vmath("MULTIPLY", co, (1200, 1200, 160)), Scale=1.0, Detail=3.0)
    broad = g.node("ShaderNodeTexNoise", Vector=co, Scale=55.0, Detail=2.0)
    base = hex_rgb(color)
    dark = tuple(c * 0.6 for c in base[:3]) + (1.0,)
    light = tuple(min(1.0, c * 1.2 + 0.015) for c in base[:3]) + (1.0,)
    g.set(bsdf, "Base Color", g.mix_color(broad.outputs[0], dark, light))
    g.set(bsdf, "Roughness", 0.98)
    g.set(bsdf, "Sheen Weight", 0.65)
    bump = g.node("ShaderNodeBump", Height=fine.outputs[0], Strength=0.55, Distance=0.0011)
    g.set(bsdf, "Normal", bump.outputs[0])
    return mat


def sky(name, top="#79B9D3", bottom="#E2EACD", *, height=0.65):
    """Matte painted Z gradient, bottom at z=0 and top at height metres."""
    if height <= 0:
        raise ValueError("sky height must be positive")
    mat, g, bsdf, _ = new_material(name)
    xyz = g.node("ShaderNodeSeparateXYZ", Vector=_coords(g))
    fac = g.math("DIVIDE", xyz.outputs["Z"], height, clamp=True)
    _finish(g, bsdf, fac, bottom, top)
    return mat


def brick(name, color="#A96548", mortar="#D8C49F", *, width=0.045, height=0.022):
    """Staggered model bricks mapped in XZ (use on a back wall)."""
    mat, g, bsdf, _ = new_material(name)
    xyz = g.node("ShaderNodeSeparateXYZ", Vector=_coords(g))
    co = g.node("ShaderNodeCombineXYZ", X=xyz.outputs["X"], Y=xyz.outputs["Z"], Z=xyz.outputs["Y"])
    tex = g.node("ShaderNodeTexBrick", Vector=co.outputs[0], Scale=1.0,
                 Color1=hex_rgb(color), Color2=hex_rgb(color), Mortar=hex_rgb(mortar),
                 Mortar_Size=0.0014, Mortar_Smooth=0.0004, Brick_Width=width, Row_Height=height)
    g.set(bsdf, "Base Color", tex.outputs["Color"])
    g.set(bsdf, "Roughness", 0.9)
    bump = g.node("ShaderNodeBump", Height=tex.outputs["Fac"], Strength=0.45, Distance=0.0015)
    bump.invert = True
    g.set(bsdf, "Normal", bump.outputs[0])
    return mat


library.RECIPES.update(stripes=stripes, checker=checker, grass=grass, sky=sky, brick=brick)
