"""Style packs: one switch that changes what everything is 'made of'.

Characters, props and sets never name a shader. They ask the active style for
a material by ROLE ("skin", "cloth", "wood", ...) and a colour. Swapping the
style pack re-skins a whole show - clay, felt, painted wooden toys - without
touching a character or episode file.
"""
from __future__ import annotations

import inspect

import bpy

from .materials import library, patterns  # noqa: F401  (patterns registers extra recipes)
from .materials.nodes import set_boil_rate

DEFAULT_STYLE = {
    "name": "clay",
    # role -> recipe + options. "default" is used for any unknown role.
    "materials": {
        "default": {"recipe": "clay"},
        "skin": {"recipe": "clay", "sss": 0.55},
        "cloth": {"recipe": "clay", "prints": 0.8},
        "knit": {"recipe": "knit"},
        "hair": {"recipe": "clay", "dents": 1.4},
        "eye": {"recipe": "eye"},
        "pupil": {"recipe": "glossy"},
        "teeth": {"recipe": "clay", "sss": 0.6, "roughness": 0.35, "prints": 0.3},
        "mouth": {"recipe": "clay", "sss": 0.2, "prints": 0.2},
        "shoe": {"recipe": "clay", "roughness": 0.4},
        "wood": {"recipe": "wood"},
        "wall": {"recipe": "matte"},
        "floor": {"recipe": "wood"},
        "paper": {"recipe": "matte", "roughness": 0.9},
        "metal": {"recipe": "metal"},
        "ceramic": {"recipe": "ceramic"},
        "glass": {"recipe": "glossy", "roughness": 0.03},
        "glow": {"recipe": "emission"},
        "fabric": {"recipe": "felt"},
    },
    "lumpiness": 1.0,  # how hand-made shapes are (0 = machine perfect)
    "boil": 0.15,  # share of the surface texture re-sculpted each exposure (0 = frozen .. 1 = all of it)
    "pose_jitter": 0.5,  # animator's-hand error on the parts that move in an exposure (held parts stay still)
    "camera_drift": 0.0,  # tripod nudged between exposures (1.0 = 0.4 mm); 0 = locked off
    "light_rig": "cosy",
    "light_flicker": 0.006,  # exposure-to-exposure brightness wobble (0.03 is plainly visible)
    "fps": 12,  # exposures per second; 12 = shot 'on twos' for 24 fps playback
    "lens": 50,
    "fstop": 4.0,
    "grade": {"grain": 0.02, "vignette": 0.35, "saturation": 1.08, "contrast": 1.04},
}


class Style:
    def __init__(self, spec: dict | None = None):
        merged = {**DEFAULT_STYLE, **(spec or {})}
        merged["materials"] = {**DEFAULT_STYLE["materials"], **(spec or {}).get("materials", {})}
        merged["grade"] = {**DEFAULT_STYLE["grade"], **(spec or {}).get("grade", {})}
        self.spec = merged
        self._cache: dict[tuple, bpy.types.Material] = {}

    def __getitem__(self, key):
        return self.spec[key]

    @property
    def lumpiness(self) -> float:
        return float(self.spec["lumpiness"])

    def apply_globals(self) -> None:
        set_boil_rate(1.0)  # the clock always ticks once per exposure; recipes decide how much it shows

    def material(self, role: str, color: str, **overrides) -> bpy.types.Material:
        """Material for a role in this style, cached per (role, colour)."""
        key = (role, str(color), tuple(sorted(overrides.items())))
        if key in self._cache:
            return self._cache[key]
        entry = dict(self.spec["materials"].get(role) or self.spec["materials"]["default"])
        recipe = entry.pop("recipe")
        entry.update(overrides)
        name = f"{self.spec['name']}_{role}_{str(color).lstrip('#')}_{len(self._cache)}"
        if recipe == "eye":
            mat = library.eye_white(name, color)
        else:
            # parts ask for clay-ish tweaks (sss, prints...); other recipes just ignore them
            accepted = inspect.signature(library.RECIPES[recipe]).parameters
            if "boil" in accepted:  # style-wide strength; a material role may set its own
                entry.setdefault("boil", float(self.spec["boil"]))
            entry = {k: v for k, v in entry.items() if k in accepted}
            mat = library.make(recipe, name, color, **entry)
        self._cache[key] = mat
        return mat


_active: Style | None = None


def use(spec: dict | None = None) -> Style:
    """Activate a style pack for everything built afterwards."""
    global _active
    _active = Style(spec)
    _active.apply_globals()
    return _active


def active() -> Style:
    global _active
    if _active is None:
        _active = Style()
        _active.apply_globals()
    return _active
