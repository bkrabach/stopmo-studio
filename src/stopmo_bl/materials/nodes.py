"""Tiny shader-graph builder so material recipes stay readable."""
from __future__ import annotations

import warnings

import bpy

BOIL_GROUP = "StopmoBoil"
REST_ATTR = "rest"


class Graph:
    """Wraps a node tree; `g.node(type, **inputs)` creates and wires a node."""

    def __init__(self, tree: bpy.types.NodeTree):
        self.tree = tree
        self._x = 0

    def node(self, bl_idname: str, _props: dict | None = None, _out=0, **inputs):
        n = self.tree.nodes.new(bl_idname)
        n.location = (self._x, 0)
        self._x += 180
        for key, val in (_props or {}).items():
            setattr(n, key, val)
        for key, val in inputs.items():
            self.set(n, key, val)
        return n

    def set(self, node, key, val) -> None:
        socket = self._input(node, key)
        if isinstance(val, bpy.types.NodeSocket):
            self.tree.links.new(val, socket)
        elif isinstance(val, bpy.types.Node):
            self.tree.links.new(val.outputs[0], socket)
        else:
            socket.default_value = val

    @staticmethod
    def _input(node, key):
        if isinstance(key, int):
            return node.inputs[key]
        # allow "Scale", "Color_1" (second socket named Color), or index strings
        if key.isdigit():
            return node.inputs[int(key)]
        name = key.replace("_", " ")
        if name in node.inputs:
            return node.inputs[name]
        if key in node.inputs:
            return node.inputs[key]
        raise KeyError(f"{node.bl_idname} has no input {key!r}: {[i.name for i in node.inputs]}")

    # -- conveniences ------------------------------------------------------
    def math(self, op: str, a, b=None, clamp=False):
        n = self.node("ShaderNodeMath", {"operation": op, "use_clamp": clamp})
        self.set(n, 0, a)
        if b is not None:
            self.set(n, 1, b)
        return n.outputs[0]

    def vmath(self, op: str, a, b=None):
        n = self.node("ShaderNodeVectorMath", {"operation": op})
        self.set(n, 0, a)
        if b is not None:
            self.set(n, 1, b)
        return n.outputs[0]

    def ramp(self, fac, stops):
        """stops: [(position, value_or_rgba), ...]"""
        n = self.node("ShaderNodeValToRGB", Fac=fac)
        elements = n.color_ramp.elements
        while len(elements) < len(stops):
            elements.new(0.5)
        for el, (pos, val) in zip(elements, stops):
            el.position = pos
            el.color = (val, val, val, 1.0) if isinstance(val, (int, float)) else val
        return n.outputs[0]

    def mix_color(self, fac, a, b, blend="MIX"):
        n = self.node("ShaderNodeMix", {"data_type": "RGBA", "blend_type": blend})
        self.set(n, 0, fac)
        self.tree.links.new(a, n.inputs[6]) if isinstance(a, bpy.types.NodeSocket) else setattr(
            n.inputs[6], "default_value", a
        )
        self.tree.links.new(b, n.inputs[7]) if isinstance(b, bpy.types.NodeSocket) else setattr(
            n.inputs[7], "default_value", b
        )
        return n.outputs[2]


def new_material(name: str) -> tuple[bpy.types.Material, Graph, bpy.types.Node, bpy.types.Node]:
    """Fresh material -> (material, graph, principled, output)."""
    mat = bpy.data.materials.new(name)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        mat.use_nodes = True
    tree = mat.node_tree
    tree.nodes.clear()
    g = Graph(tree)
    out = g.node("ShaderNodeOutputMaterial")
    bsdf = g.node("ShaderNodeBsdfPrincipled")
    tree.links.new(bsdf.outputs[0], out.inputs["Surface"])
    return mat, g, bsdf, out


def boil_group(rate: float = 1.0) -> bpy.types.NodeTree:
    """Shared node group that outputs a value changing once per exposure.

    Feeding it to the W input of 4D noise makes surface texture 're-sculpt'
    every exposure - the 'boil' that gives stop motion away. One driver for
    the whole file keeps it cheap and easy to switch off (set rate to 0).
    """
    grp = bpy.data.node_groups.get(BOIL_GROUP)
    if grp is not None:
        return grp
    grp = bpy.data.node_groups.new(BOIL_GROUP, "ShaderNodeTree")
    grp.interface.new_socket("W", in_out="OUTPUT", socket_type="NodeSocketFloat")
    value = grp.nodes.new("ShaderNodeValue")
    value.name = "boil"
    out = grp.nodes.new("NodeGroupOutput")
    grp.links.new(value.outputs[0], out.inputs[0])
    fcurve = value.outputs[0].driver_add("default_value")
    fcurve.driver.type = "SCRIPTED"
    fcurve.driver.expression = f"frame * {rate * 3.173:.4f}"
    grp["boil_rate"] = rate
    return grp


def set_boil_rate(rate: float) -> None:
    grp = boil_group()
    for fcurve in grp.animation_data.drivers:
        fcurve.driver.expression = f"frame * {rate * 3.173:.4f}"
    grp["boil_rate"] = rate


def surface_coords(g: Graph, per_object_shift: float = 7.0):
    """Texture coordinates in metres that stick to the surface under deformation.

    Uses the 'rest' vertex attribute written by `store_rest`; every object also
    gets a random shift so two parts never show the same thumbprints.
    """
    attr = g.node("ShaderNodeAttribute", {"attribute_type": "GEOMETRY", "attribute_name": REST_ATTR})
    info = g.node("ShaderNodeObjectInfo")
    shift = g.math("MULTIPLY", info.outputs["Random"], per_object_shift)
    return g.vmath("ADD", attr.outputs["Vector"], shift)


def boil_w(g: Graph):
    n = g.node("ShaderNodeGroup")
    n.node_tree = boil_group()
    return n.outputs[0]


def store_rest(obj: bpy.types.Object) -> None:
    """Write rest-pose positions (object space, metres) into a vertex attribute."""
    mesh = obj.data
    attr = mesh.attributes.get(REST_ATTR)
    if attr is None:
        attr = mesh.attributes.new(REST_ATTR, "FLOAT_VECTOR", "POINT")
    flat = [0.0] * (len(mesh.vertices) * 3)
    mesh.vertices.foreach_get("co", flat)
    attr.data.foreach_set("vector", flat)
