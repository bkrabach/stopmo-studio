"""Procedural material recipes. Every recipe is `fn(name, color, **opts) -> Material`.

All textures are procedural (no image files), driven by rest-pose coordinates
in metres, so one recipe works on any part at any size.
"""
from __future__ import annotations

import math

from ..util import hex_rgb
from .nodes import boil_w, new_material, surface_coords


def _scale(g, coords, scale):
    n = g.node("ShaderNodeVectorMath", {"operation": "SCALE"})
    g.set(n, 0, coords)
    n.inputs["Scale"].default_value = scale
    return n.outputs[0]


FROZEN_W = 7.31  # any constant: the 4D-noise slice used for the part of the sculpt that never changes


def clay(
    name,
    color,
    *,
    roughness=0.52,
    sss=0.5,
    dents=1.0,
    prints=1.0,
    grain=1.0,
    mottle=0.06,
    boil=1.0,
    dent_size=0.012,
    print_size=0.0016,
):
    """Plasticine: waxy sheen, soft subsurface, thumb dents, tool marks and fingerprints.

    dents / prints / grain scale the bump layers.

    `boil` (0..1) is how much of the hand-worked texture is re-sculpted on every exposure:
    0 = the surface never changes, 1 = a completely new set of dents and prints each exposure,
    0.3 = a persistent sculpt with 30% of its relief changing. The total amount of texture is
    the same at every level, so the dial changes the flicker and not how worked the clay looks.
    """
    mat, g, bsdf, out = new_material(name)
    base = hex_rgb(color)
    co = surface_coords(g)

    def sculpt(w):
        """One complete worked surface for a 4D-noise W -> (dent factor, print height, smear height)."""

        def times(k):
            return w * k if isinstance(w, float) else g.math("MULTIPLY", w, k)

        # 1) thumb dents: broad soft noise
        dent = g.node(
            "ShaderNodeTexNoise",
            {"noise_dimensions": "4D"},
            Vector=_scale(g, co, 1.0 / dent_size),
            W=w,
            Scale=1.0,
            Detail=2.0,
            Roughness=0.45,
        )
        # 2) fingerprints: curved ridges inside scattered patches
        cells = g.node(
            "ShaderNodeTexVoronoi",
            {"voronoi_dimensions": "4D", "feature": "F1"},
            Vector=_scale(g, co, 1.0 / (print_size * 14)),
            W=times(0.31),
            Scale=1.0,
        )
        # each patch gets its own swirl direction from the cell colour
        swirl = g.vmath("ADD", _scale(g, co, 1.0 / print_size), _scale(g, cells.outputs["Color"], 40.0))
        ridges = g.node(
            "ShaderNodeTexWave",
            {"wave_type": "RINGS", "rings_direction": "SPHERICAL", "wave_profile": "SIN"},
            Vector=_scale(g, swirl, 0.02),
            Scale=6.0,
            Distortion=2.2,
            Detail=1.0,
            Detail_Scale=1.5,
        )
        # patch mask: only near cell centres, and only where a slow noise allows
        patch = g.ramp(cells.outputs["Distance"], [(0.25, 1.0), (0.55, 0.0)])
        allow = g.node(
            "ShaderNodeTexNoise",
            {"noise_dimensions": "4D"},
            Vector=_scale(g, co, 1.0 / (print_size * 40)),
            W=times(0.17),
            Scale=1.0,
            Detail=0.0,
        )
        allow_mask = g.ramp(allow.outputs[0], [(0.45, 0.0), (0.6, 1.0)])
        print_h = g.math("MULTIPLY", g.math("MULTIPLY", ridges.outputs[0], patch), allow_mask)
        # 2b) tool marks / smears: shallow curved grooves a few mm apart, where there are no prints
        smear = g.node(
            "ShaderNodeTexWave",
            {"wave_type": "BANDS", "bands_direction": "DIAGONAL", "wave_profile": "SIN"},
            Vector=_scale(g, co, 1.0 / 0.02),
            Scale=3.2,
            Distortion=5.5,
            Detail=2.0,
            Detail_Scale=1.2,
        )
        smear_mask = g.ramp(allow.outputs[0], [(0.3, 1.0), (0.55, 0.0)])
        smear_h = g.math("MULTIPLY", smear.outputs[0], smear_mask)
        return dent.outputs[0], print_h, smear_h

    strength = min(max(float(boil), 0.0), 1.0)
    if strength <= 0.0:
        dent_fac, print_h, smear_h = sculpt(FROZEN_W)
    elif strength >= 1.0:
        dent_fac, print_h, smear_h = sculpt(boil_w(g))
    else:
        still, moving = sculpt(FROZEN_W), sculpt(boil_w(g))
        keep = math.sqrt(1.0 - strength * strength)  # keep^2 + strength^2 = 1: constant total relief

        def blend(a, b, centre):
            fixed = g.math("MULTIPLY", g.math("SUBTRACT", a, centre), keep)
            fresh = g.math("MULTIPLY", g.math("SUBTRACT", b, centre), strength)
            return g.math("ADD", g.math("ADD", fixed, fresh), centre)

        dent_fac = blend(still[0], moving[0], 0.5)
        print_h = blend(still[1], moving[1], 0.0)
        smear_h = blend(still[2], moving[2], 0.0)
    dent_h = g.math("SUBTRACT", dent_fac, 0.5)

    # 3) fine grain so highlights break up (never boils)
    fine = g.node(
        "ShaderNodeTexNoise",
        {"noise_dimensions": "3D"},
        Vector=_scale(g, co, 1.0 / 0.0009),
        Scale=1.0,
        Detail=3.0,
        Roughness=0.6,
    )

    bump1 = g.node("ShaderNodeBump", Height=dent_h, Strength=1.0 * dents, Distance=0.006)
    bump1 = g.node("ShaderNodeBump", Height=smear_h, Strength=0.3 * dents, Distance=0.002, Normal=bump1.outputs[0])
    bump2 = g.node(
        "ShaderNodeBump", Height=print_h, Strength=0.55 * prints, Distance=0.0009, Normal=bump1.outputs[0]
    )
    bump3 = g.node(
        "ShaderNodeBump", Height=fine.outputs[0], Strength=0.10 * grain, Distance=0.0004, Normal=bump2.outputs[0]
    )

    # colour: slight mottling, a touch darker in the dents
    dark = tuple(c * 0.72 for c in base[:3]) + (1.0,)
    light = tuple(min(c * 1.12 + 0.01, 1.0) for c in base[:3]) + (1.0,)
    mottled = g.mix_color(dent_fac, dark, light)
    col = g.mix_color(mottle * 4.0, base, mottled)
    g.set(bsdf, "Base Color", col)
    # handled patches are shinier: break the highlight up with the dent pattern
    rough = g.math("ADD", roughness - 0.16, g.math("MULTIPLY", fine.outputs[0], 0.12))
    rough = g.math("ADD", rough, g.math("MULTIPLY", dent_fac, 0.22))
    g.set(bsdf, "Roughness", rough)
    g.set(bsdf, "Specular IOR Level", 0.38)
    g.set(bsdf, "Subsurface Weight", sss)
    g.set(bsdf, "Subsurface Radius", (1.0, 0.45, 0.25))
    g.set(bsdf, "Subsurface Scale", 0.009)
    g.set(bsdf, "Normal", bump3.outputs[0])
    return mat


def glossy(name, color, *, roughness=0.12, coat=0.6):
    """Hard shiny plastic/bead: pupils, buttons, painted props."""
    mat, g, bsdf, out = new_material(name)
    g.set(bsdf, "Base Color", hex_rgb(color))
    g.set(bsdf, "Roughness", roughness)
    g.set(bsdf, "Coat Weight", coat)
    g.set(bsdf, "Coat Roughness", 0.05)
    return mat


def eye_white(name="eye_white", color="#F4F1E8"):
    """Polished clay bead for eyeballs: glossy with a little subsurface."""
    mat, g, bsdf, out = new_material(name)
    g.set(bsdf, "Base Color", hex_rgb(color))
    g.set(bsdf, "Roughness", 0.18)
    g.set(bsdf, "Subsurface Weight", 0.25)
    g.set(bsdf, "Subsurface Radius", (1.0, 0.8, 0.7))
    g.set(bsdf, "Subsurface Scale", 0.004)
    g.set(bsdf, "Coat Weight", 0.5)
    g.set(bsdf, "Coat Roughness", 0.06)
    return mat


def matte(name, color, *, roughness=0.85, grain=1.0, grain_size=0.002):
    """Painted card / matte poster paint, with a faint brushed grain."""
    mat, g, bsdf, out = new_material(name)
    co = surface_coords(g)
    tex = g.node("ShaderNodeTexNoise", Vector=_scale(g, co, 1.0 / grain_size), Scale=1.0, Detail=4.0)
    base = hex_rgb(color)
    dark = tuple(c * 0.85 for c in base[:3]) + (1.0,)
    g.set(bsdf, "Base Color", g.mix_color(tex.outputs[0], dark, base))
    g.set(bsdf, "Roughness", roughness)
    bump = g.node("ShaderNodeBump", Height=tex.outputs[0], Strength=0.15 * grain, Distance=0.0005)
    g.set(bsdf, "Normal", bump.outputs[0])
    return mat


def wood(name, color, *, ring_scale=0.006, roughness=0.6, axis="X"):
    """Model-shop wood: stretched grain bands with fine pores."""
    mat, g, bsdf, out = new_material(name)
    co = surface_coords(g, per_object_shift=3.0)
    stretch = {"X": (0.08, 1.0, 1.0), "Y": (1.0, 0.08, 1.0), "Z": (1.0, 1.0, 0.08)}[axis]
    stretched = g.vmath("MULTIPLY", co, stretch)
    bands = g.node(
        "ShaderNodeTexNoise", Vector=_scale(g, stretched, 1.0 / ring_scale), Scale=1.0, Detail=5.0, Roughness=0.65
    )
    base = hex_rgb(color)
    dark = tuple(c * 0.55 for c in base[:3]) + (1.0,)
    g.set(bsdf, "Base Color", g.mix_color(g.ramp(bands.outputs[0], [(0.35, 0.0), (0.7, 1.0)]), dark, base))
    g.set(bsdf, "Roughness", roughness)
    bump = g.node("ShaderNodeBump", Height=bands.outputs[0], Strength=0.25, Distance=0.0008)
    g.set(bsdf, "Normal", bump.outputs[0])
    return mat


def felt(name, color, *, fuzz=1.0):
    """Needle-felted wool: dead matte, heathered fibres, lumpy 'pills', a soft glowing fuzz at the edges."""
    mat, g, bsdf, out = new_material(name)
    co = surface_coords(g)
    # long fibres lying in two crossed directions
    f1 = g.node("ShaderNodeTexNoise", Vector=_scale(g, g.vmath("MULTIPLY", co, (1.0, 0.12, 0.5)), 1.0 / 0.0005),
                Scale=1.0, Detail=5.0, Roughness=0.7)
    f2 = g.node("ShaderNodeTexNoise", Vector=_scale(g, g.vmath("MULTIPLY", co, (0.15, 1.0, 0.6)), 1.0 / 0.0005),
                Scale=1.0, Detail=5.0, Roughness=0.7)
    fibres = g.math("MAXIMUM", f1.outputs[0], f2.outputs[0])
    # needle dimples and matted clumps a few mm across
    clumps = g.node("ShaderNodeTexNoise", Vector=_scale(g, co, 1.0 / 0.007), Scale=1.0, Detail=3.0, Roughness=0.6)
    pits = g.node("ShaderNodeTexVoronoi", {"feature": "F1"}, Vector=_scale(g, co, 1.0 / 0.0035), Scale=1.0)
    base = hex_rgb(color)
    dark = tuple(c * 0.5 for c in base[:3]) + (1.0,)
    light = tuple(min(c * 1.35 + 0.03, 1.0) for c in base[:3]) + (1.0,)
    heather = g.mix_color(g.ramp(fibres, [(0.45, 0.0), (0.8, 1.0)]), dark, light)
    mottled = g.mix_color(clumps.outputs[0], dark, light)
    g.set(bsdf, "Base Color", g.mix_color(0.45, g.mix_color(0.55, base, heather), mottled))
    g.set(bsdf, "Roughness", 1.0)
    g.set(bsdf, "Specular IOR Level", 0.0)  # wool has no highlight at all
    g.set(bsdf, "Sheen Weight", min(1.0, 0.9 * fuzz))
    g.set(bsdf, "Sheen Roughness", 0.35)
    g.set(bsdf, "Sheen Tint", light)
    g.set(bsdf, "Subsurface Weight", 0.12)
    g.set(bsdf, "Subsurface Scale", 0.004)
    h = g.math("ADD", g.math("MULTIPLY", fibres, 0.5), g.math("MULTIPLY", clumps.outputs[0], 0.9))
    h = g.math("ADD", h, g.math("MULTIPLY", pits.outputs["Distance"], 0.6))
    bump = g.node("ShaderNodeBump", Height=h, Strength=1.0 * fuzz, Distance=0.004)
    g.set(bsdf, "Normal", bump.outputs[0])
    return mat


def knit(name, color, *, stitch=0.0022):
    """Chunky knitwear: rows of stitches from two crossed wave textures."""
    mat, g, bsdf, out = new_material(name)
    co = surface_coords(g, per_object_shift=0.0)
    rows = g.node(
        "ShaderNodeTexWave",
        {"wave_type": "BANDS", "bands_direction": "Z", "wave_profile": "SIN"},
        Vector=co,
        Scale=1.0 / stitch / 6.283 * 1.0,
        Distortion=0.0,
    )
    cols = g.node(
        "ShaderNodeTexWave",
        {"wave_type": "BANDS", "bands_direction": "X", "wave_profile": "SIN"},
        Vector=co,
        Scale=1.0 / stitch / 6.283 * 1.6,
        Distortion=0.6,
        Detail=1.0,
    )
    h = g.math("ADD", g.math("MULTIPLY", rows.outputs[0], 0.6), g.math("MULTIPLY", cols.outputs[0], 0.4))
    base = hex_rgb(color)
    dark = tuple(c * 0.6 for c in base[:3]) + (1.0,)
    g.set(bsdf, "Base Color", g.mix_color(h, dark, base))
    g.set(bsdf, "Roughness", 0.9)
    g.set(bsdf, "Sheen Weight", 0.4)
    g.set(bsdf, "Subsurface Weight", 0.1)
    g.set(bsdf, "Subsurface Scale", 0.003)
    bump = g.node("ShaderNodeBump", Height=h, Strength=0.8, Distance=0.0012)
    g.set(bsdf, "Normal", bump.outputs[0])
    return mat


def metal(name, color="#B8B8B8", *, roughness=0.35):
    """Brushed tin / aluminium foil for gadgets."""
    mat, g, bsdf, out = new_material(name)
    co = surface_coords(g)
    tex = g.node("ShaderNodeTexNoise", Vector=_scale(g, co, 1.0 / 0.003), Scale=1.0, Detail=3.0)
    g.set(bsdf, "Base Color", hex_rgb(color))
    g.set(bsdf, "Metallic", 1.0)
    g.set(bsdf, "Roughness", g.math("ADD", roughness - 0.1, g.math("MULTIPLY", tex.outputs[0], 0.2)))
    bump = g.node("ShaderNodeBump", Height=tex.outputs[0], Strength=0.08, Distance=0.0005)
    g.set(bsdf, "Normal", bump.outputs[0])
    return mat


def ceramic(name, color, *, roughness=0.08):
    """Glazed crockery."""
    mat, g, bsdf, out = new_material(name)
    g.set(bsdf, "Base Color", hex_rgb(color))
    g.set(bsdf, "Roughness", roughness)
    g.set(bsdf, "Coat Weight", 1.0)
    g.set(bsdf, "Coat Roughness", 0.03)
    g.set(bsdf, "Subsurface Weight", 0.15)
    g.set(bsdf, "Subsurface Scale", 0.003)
    return mat


def emission(name, color, strength=2.2):
    """Practical lights: bulbs, windows, screens."""
    mat, g, bsdf, out = new_material(name)
    g.set(bsdf, "Base Color", hex_rgb(color))
    g.set(bsdf, "Emission Color", hex_rgb(color))
    g.set(bsdf, "Emission Strength", strength)
    return mat


def vinyl(name, color, *, roughness=0.42, coat=0.1, sss=0.3, speckle=0.12):
    """Soft moulded vinyl, like a designer toy: smooth and satin, a little light soaking in, and the
    faintest orange-peel from the mould (speckle 0 = perfectly smooth)."""
    mat, g, bsdf, out = new_material(name)
    g.set(bsdf, "Base Color", hex_rgb(color))
    g.set(bsdf, "Roughness", roughness)
    g.set(bsdf, "Subsurface Weight", sss)
    g.set(bsdf, "Subsurface Radius", (1.0, 0.7, 0.5))
    g.set(bsdf, "Subsurface Scale", 0.006)
    g.set(bsdf, "Coat Weight", coat)
    g.set(bsdf, "Coat Roughness", 0.3)
    if speckle > 0:
        tex = g.node("ShaderNodeTexNoise", Vector=_scale(g, surface_coords(g), 1.0 / 0.0009), Scale=1.0, Detail=2.0)
        bump = g.node("ShaderNodeBump", Height=tex.outputs[0], Strength=0.1 * speckle, Distance=0.0003)
        g.set(bsdf, "Normal", bump.outputs[0])
    return mat


def clear(name, color="#FFFFFF", *, roughness=0.03, tint=0.05):
    """Clear moulded plastic or glass for domes and lenses: light passes straight through (so what is
    inside is lit and casts its own shadow), with reflections that strengthen toward the edges."""
    mat, g, bsdf, out = new_material(name)
    base = hex_rgb(color)
    through = g.node("ShaderNodeBsdfTransparent", Color=tuple(1 - tint * (1 - c) for c in base[:3]) + (1.0,))
    shine = g.node("ShaderNodeBsdfGlossy", Color=(1.0, 1.0, 1.0, 1.0), Roughness=roughness)
    facing = g.node("ShaderNodeLayerWeight", Blend=0.35)
    amount = g.ramp(facing.outputs["Facing"], [(0.0, 0.05), (1.0, 0.85)])
    mix = g.node("ShaderNodeMixShader")
    g.set(mix, 0, amount)
    g.tree.links.new(through.outputs[0], mix.inputs[1])
    g.tree.links.new(shine.outputs[0], mix.inputs[2])
    g.tree.links.new(mix.outputs[0], out.inputs["Surface"])
    return mat


RECIPES = {
    "vinyl": vinyl,
    "clear": clear,
    "clay": clay,
    "glossy": glossy,
    "matte": matte,
    "wood": wood,
    "felt": felt,
    "knit": knit,
    "metal": metal,
    "ceramic": ceramic,
    "emission": emission,
}


def make(recipe: str, name: str, color, **opts):
    """Build a material by recipe name - the entry point used by style packs."""
    return RECIPES[recipe](name, color, **opts)
