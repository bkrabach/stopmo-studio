"""Character archetypes: each module exposes build(name, spec) -> Puppet."""
from . import biped, figure, toy

REGISTRY = {"biped": biped.build, "toy": toy.build, "figure": figure.build}


def build(name: str, spec: dict):
    kind = spec.get("archetype", "biped")
    if kind not in REGISTRY:
        raise KeyError(f"unknown archetype {kind!r}; have {sorted(REGISTRY)}")
    return REGISTRY[kind](name, spec)
