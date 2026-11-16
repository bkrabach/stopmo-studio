"""Chunky, deterministic tabletop props. All dimensions are metres; front is -Y.

Builders are plain functions taking a root and documented keyword parameters.
Use build_prop, not a builder directly, to finish surfaces and place the asset.
"""
from __future__ import annotations

import math
import random
from collections.abc import Callable

import bmesh
import bpy
from mathutils import Matrix, Vector

from . import style, util
from .materials.nodes import store_rest

PROPS: dict[str, Callable] = {}
WOOD = "#987044"
CREAM = "#E6D7AF"
TEAL = "#4D8C88"
DARK = "#373B35"


def _register(fn):
    PROPS[fn.__name__] = fn
    return fn


def descendants(root):
    """Yield a root and its entire hierarchy (including light objects)."""
    yield root
    for child in root.children:
        yield from descendants(child)


def bounds(root):
    """Evaluated world AABB of every mesh below a prop root."""
    bpy.context.view_layer.update()
    deps = bpy.context.evaluated_depsgraph_get()
    pts = [o.matrix_world @ Vector(p) for raw in descendants(root) if raw.type == "MESH"
           for o in [raw.evaluated_get(deps)] for p in o.bound_box]
    if not pts:
        raise ValueError(f"no mesh in {root.name}")
    return (Vector(tuple(min(p[i] for p in pts) for i in range(3))),
            Vector(tuple(max(p[i] for p in pts) for i in range(3))))


def anchor(root, name: str) -> Vector:
    """Return a named local-space attachment/interaction point in world space."""
    bpy.context.view_layer.update()
    if name in root.get("anchor_parts", {}):
        part = next(o for o in root.children_recursive if o.name == root["anchor_parts"][name])
        return part.matrix_world @ Vector(root["anchors"][name])
    return root.matrix_world @ Vector(root["anchors"][name])


def _anchors(root, **points):
    root["anchors"] = {k: [float(c) for c in v] for k, v in points.items()}  # floats: whole numbers would be stored as ints


def _part(root, obj, role="default", color=CREAM):
    obj.name = root.name + "." + obj.name
    obj.parent = root
    util.set_material(obj, style.active().material(role, color))
    return obj


def _box(r, name, size, at, color=WOOD, role="wood", angle=0):
    o = util.rounded_box(name, size, bevel=0.15, segments=3)
    o.data.transform(Matrix.Translation(at) @ Matrix.Rotation(angle, 4, "Z"))
    return _part(r, o, role, color)


def _ball(r, name, radii, at, color=CREAM, role="default"):
    return _part(r, util.ellipsoid(name, radii, at, subdiv=3), role, color)


def _cyl(r, name, radius, depth, at, color=WOOD, role="wood", axis="Z", top=None):
    o = util.cylinder(name, radius, depth, segments=32, radius_top=top)
    rot = {"Z": Matrix.Identity(4), "Y": Matrix.Rotation(math.pi / 2, 4, "X"),
           "X": Matrix.Rotation(math.pi / 2, 4, "Y")}[axis]
    o.data.transform(Matrix.Translation(at) @ rot)
    # Keep caps flat, shade only the side faces smoothly.
    for face in o.data.polygons:
        face.use_smooth = len(face.vertices) == 4
    return _part(r, o, role, color)


def _tube(r, name, points, radius, color=WOOD, role="wood", cap=True):
    radii = [radius] * len(points) if isinstance(radius, (int, float)) else radius
    return _part(r, util.tube(name, points, radii, segments=16, cap=cap), role, color)


def _text(r, text: str, at, width: float, size: float, *, tilt=90, color=DARK, font=""):
    """Centered mesh lettering; tilt=90 faces -Y, tilt=0 lies on the XY plane. `font` is a .ttf/.otf
    path (relative paths are looked up in assets/fonts); default is Blender's own sans."""
    curve = bpy.data.curves.new("lettering", "FONT")
    if font:
        import os
        path = font if os.path.isabs(font) else os.path.join(os.path.dirname(__file__), "..", "..", "assets", "fonts", font)
        curve.font = bpy.data.fonts.load(os.path.abspath(path), check_existing=True)
    curve.body, curve.align_x, curve.align_y = str(text), "CENTER", "CENTER"
    curve.size, curve.extrude, curve.bevel_depth = size, .00008, .00002
    tmp = bpy.data.objects.new("lettering", curve)
    util.link(tmp)
    bpy.context.view_layer.update()
    mesh = bpy.data.meshes.new_from_object(tmp.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    bpy.data.objects.remove(tmp, do_unlink=True)
    bpy.data.curves.remove(curve)
    obj = bpy.data.objects.new("lettering", mesh)
    util.link(obj)
    actual = max(v.co.x for v in mesh.vertices) - min(v.co.x for v in mesh.vertices) if mesh.vertices else 0
    factor = min(1.0, width / max(actual, 1e-6))
    mesh.transform(Matrix.Translation(at) @ Matrix.Rotation(math.radians(tilt), 4, "X")
                   @ Matrix.Scale(factor, 4))
    obj["text"] = str(text)
    return _part(r, obj, "paper", color)


def _ring(r, name, at, radius, thickness, color=CREAM, role="ceramic", plane="XY"):
    """A genuinely periodic torus: no mismatched end rings or black seam."""
    n, m = 48, 12
    verts = []
    for i in range(n):
        a = i * math.tau / n
        for j in range(m):
            b = j * math.tau / m
            radial = radius + thickness * math.cos(b)
            x, y, z = radial * math.cos(a), radial * math.sin(a), thickness * math.sin(b)
            v = {"XY": (x, y, z), "XZ": (x, -z, y), "YZ": (z, x, y)}[plane]
            verts.append(tuple(at[k] + v[k] for k in range(3)))
    faces = [(i*m+j, ((i+1)%n)*m+j, ((i+1)%n)*m+(j+1)%m, i*m+(j+1)%m)
             for i in range(n) for j in range(m)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    util.link(obj)
    util.shade_smooth(obj)
    return _part(r, obj, role, color)


def _vessel(r, name, profile, at=(0, 0, 0), color=TEAL, role="ceramic"):
    """Revolve a closed radial/Z profile, including its inner wall and bottom."""
    n = 48
    verts = [(at[0] + rad * math.cos(i * math.tau / n),
              at[1] + rad * math.sin(i * math.tau / n), at[2] + z)
             for rad, z in profile for i in range(n)]
    faces = []
    for j in range(len(profile)):
        k = (j + 1) % len(profile)
        for i in range(n):
            q = (i + 1) % n
            faces.append((j*n+i, j*n+q, k*n+q, k*n+i))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    o = bpy.data.objects.new(name, mesh)
    util.link(o)
    util.shade_smooth(o)
    return _part(r, o, role, color)


def _legs(r, width, depth, height, color=WOOD, radius=0.005):
    for x in (-width / 2, width / 2):
        for y in (-depth / 2, depth / 2):
            _cyl(r, "leg", radius, height, (x, y, height/2), color)


@_register
def table(r, *, width=0.19, depth=0.12, height=0.10, color=WOOD, top_color=None):
    """Four-legged kitchen table; width/depth/top height in metres."""
    _legs(r, width-0.025, depth-0.025, height-0.009, color, 0.006)
    _box(r, "apron", (width-0.012, depth-0.012, 0.018), (0, 0, height-0.018), color)
    _box(r, "top", (width, depth, 0.011), (0, 0, height-0.0055), top_color or color)
    _anchors(r, top=(0, 0, height))


@_register
def chair(r, *, width=0.065, seat_height=0.060, color=WOOD, cushion="#B45B3D"):
    """Dining chair with a slatted back; seat_height is the cushion surface."""
    _legs(r, width-0.018, 0.042, seat_height-0.010, color, 0.004)
    _box(r, "seat", (width, 0.062, 0.009), (0, 0, seat_height-0.0045), color)
    _box(r, "cushion", (width-0.009, 0.050, 0.006), (0, -0.002, seat_height), cushion, "fabric")
    for x in (-width/2+0.006, width/2-0.006):
        _box(r, "back_post", (0.008, 0.008, 0.104), (x, 0.025, 0.073), color)
    for z in (0.084, 0.114):
        _box(r, "back_slat", (width, 0.009, 0.015), (0, 0.025, z), color)
    _anchors(r, seat=(0, 0, seat_height+0.003), back=(0, 0.024, 0.12))


@_register
def stool(r, *, height=0.06, radius=0.032, color=WOOD):
    """Round three-legged stool; height is the seat surface."""
    for a in (0, math.tau/3, math.tau*2/3):
        _tube(r, "leg", [(radius*0.76*math.cos(a), radius*0.76*math.sin(a), 0.004),
                          (radius*0.58*math.cos(a), radius*0.58*math.sin(a), height-0.009)], 0.004, color)
    _cyl(r, "seat", radius, 0.011, (0, 0, height-0.0055), color)
    _anchors(r, seat=(0, 0, height))


@_register
def armchair(r, *, color="#9F5649", feet=WOOD):
    """Overstuffed reading chair with four short feet."""
    _legs(r, 0.073, 0.068, 0.018, feet, 0.006)
    _box(r, "base", (0.107, 0.092, 0.046), (0, 0, 0.038), color, "fabric")
    _box(r, "seat_cushion", (0.075, 0.077, 0.020), (0, -0.008, 0.063), color, "fabric")
    _box(r, "back", (0.107, 0.032, 0.10), (0, 0.037, 0.087), color, "fabric")
    for x in (-0.047, 0.047):
        _box(r, "arm", (0.028, 0.09, 0.037), (x, -0.003, 0.077), color, "fabric")
    _anchors(r, seat=(0, -0.008, 0.073))


@_register
def shelf(r, *, width=0.18, depth=0.05, color=WOOD):
    """Wall shelf with two visible brackets; place its root at bracket-bottom."""
    _box(r, "shelf", (width, depth, 0.008), (0, 0, 0.035), color)
    for x in (-width*0.34, width*0.34):
        _box(r, "bracket_back", (0.008, 0.008, 0.036), (x, depth/2-0.006, 0.018), color)
        _tube(r, "bracket", [(x, depth/2-0.006, 0.004), (x, -depth/2+0.006, 0.030)], 0.0035, color)
    _anchors(r, top=(0, 0, 0.039))


@_register
def cupboard(r, *, width=0.14, height=0.18, depth=0.065, color="#849C83", trim=CREAM):
    """Two-door painted cupboard with inset panels, cornice and knob handles."""
    _legs(r, width-0.025, depth-0.019, 0.015, WOOD, 0.005)
    _box(r, "carcase", (width, depth, height-0.022), (0, 0, (height+0.008)/2), color)
    _box(r, "cornice", (width+0.01, depth+0.008, 0.012), (0, 0, height-0.006), trim)
    for x in (-width/4, width/4):
        _box(r, "door", (width/2-0.005, 0.006, height-0.038), (x, -depth/2-0.002, height/2+0.003), trim)
        _box(r, "panel", (width/2-0.018, 0.006, height-0.060), (x, -depth/2-0.0055, height/2+0.005), color)
        _ball(r, "knob", (0.0035, 0.004, 0.0035), (x*0.23, -depth/2-0.011, height*0.50), "#BB9553", "metal")
    _anchors(r, top=(0, 0, height), handle=(0.008, -depth/2-0.014, height*0.5))


@_register
def teapot(r, *, color="#B76642", trim=CREAM):
    """Round teapot with raised spout, loop handle and removable-looking lid."""
    _cyl(r, "foot", 0.012, 0.004, (0, 0, 0.002), color, "ceramic")
    _ball(r, "belly", (0.019, 0.015, 0.016), (0, 0, 0.018), color, "ceramic")
    _cyl(r, "lid", 0.013, 0.003, (0, 0, 0.032), trim, "ceramic", top=0.009)
    _ball(r, "knob", (0.004, 0.004, 0.003), (0, 0, 0.036), color, "ceramic")
    _ring(r, "handle", (-0.021, 0, 0.020), 0.012, 0.003, color, plane="XZ")
    _tube(r, "spout", [(0.013,0,0.014),(0.025,0,0.019),(0.031,0,0.033)], [0.006,0.0045,0.0035], color, "ceramic", cap=False)
    _ball(r, "spout_hole", (0.0028,0.0028,0.001), (0.031,0,0.033), DARK, "default")
    _anchors(r, handle=(-0.031, 0, 0.020), spout=(0.031, 0, 0.034), lid=(0, 0, 0.037))


@_register
def mug(r, *, color=TEAL, tea=True):
    """Hollow glazed mug; tea adds a recessed dark liquid surface."""
    _vessel(r, "cup", [(0.001,0),(0.008,0),(0.010,0.003),(0.0105,0.021),
                        (0.009,0.023),(0.0075,0.021),(0.0074,0.004),(0.001,0.004)], color=color)
    _ring(r, "handle", (0.012,0,0.012), 0.0068, 0.0022, color, plane="XZ")
    if tea:
        _cyl(r,"tea",0.0076,0.001,(0,0,0.0165),"#593323","default")
    _anchors(r, handle=(0.020,0,0.012), rim=(0,0,0.023))


@_register
def plate(r, *, radius=0.025, color=CREAM):
    """Shallow plate with a softly raised outer rim."""
    _vessel(r, "dish", [(0.001,0),(radius*0.6,0),(radius,0.0035),
                         (radius,0.005),(radius*0.62,0.0025),(0.001,0.0025)], color=color)
    _ring(r,"rim",(0,0,0.0045),radius*0.93,0.0012,TEAL)
    _anchors(r, center=(0,0,0.0025))


@_register
def biscuit(r, *, radius=0.012, color="#C78D45", chips=True):
    """Round baked biscuit; chips=False makes a dotted plain tea biscuit."""
    _cyl(r,"biscuit",radius,0.004,(0,0,0.002),color,"default")
    rand = random.Random(int(r["seed"]))
    for i in range(11):
        a = rand.random()*math.tau
        d = rand.uniform(0.15,0.78)*radius
        _ball(r,"chip" if chips else "dimple",(0.0012,0.001,0.00045),
              (d*math.cos(a),d*math.sin(a),0.004),"#543827" if chips else "#9D6D36")
    _anchors(r, center=(0,0,0.004))


@_register
def bowl(r, *, radius=0.024, color=TEAL):
    """Deep open breakfast/serving bowl with a visibly hollow interior."""
    _vessel(r,"bowl",[(0.001,0),(radius*0.45,0),(radius*0.65,0.004),(radius,0.019),
                        (radius,0.021),(radius*0.9,0.021),(radius*0.52,0.005),(0.001,0.004)],color=color)
    _anchors(r, rim=(0,0,0.021), center=(0,0,0.006))


@_register
def spoon(r, *, color="#A7A7A0"):
    """Tin spoon with oval bowl and a long narrow handle, lying on its back."""
    _ball(r,"bowl",(0.005,0.007,0.0018),(0,0.013,0.0018),color,"metal")
    _tube(r,"handle",[(0,0.009,0.002),(0,-0.008,0.002),(0,-0.023,0.002)],0.0016,color,"metal")
    _anchors(r, handle=(0,-0.020,0.002))


@_register
def lamp(r, *, height=0.23, color="#C89B50", shade=CREAM, lit=True):
    """Floor/table lamp; height is total size, lit adds a real warm point light."""
    f = height/0.23
    _cyl(r,"foot",0.027*f,0.008*f,(0,0,0.004*f),color,"metal",top=0.023*f)
    _tube(r,"stem",[(0,0,0.008*f),(0.001*f,0,0.18*f)],0.003*f,color,"metal")
    _vessel(r,"shade",[(0.037*f,0.175*f),(0.020*f,0.228*f),(0.018*f,0.228*f),
                         (0.035*f,0.175*f)],color=shade,role="fabric")
    _ball(r,"bulb",(0.008*f,0.008*f,0.010*f),(0,0,0.19*f),"#FFD69A","glow" if lit else "ceramic")
    if lit:
        data = bpy.data.lights.new(r.name+".practical","POINT")
        data.energy = 0.025*f*f
        data.color = util.hex_rgb("#FFD39A")[:3]
        data.shadow_soft_size = 0.006*f
        obj = bpy.data.objects.new(data.name,data)
        util.link(obj)
        obj.parent = r
        obj.location = (0,0,0.185*f)
    _anchors(r, bulb=(0,0,0.19*f))


@_register
def clock(r, *, hour=10, minute=10, radius=0.035, color=WOOD):
    """Round wall clock facing -Y, with minute ticks and actual positioned hands."""
    z = radius
    _cyl(r,"case",radius,0.009,(0,0,z),color,"wood",axis="Y")
    _cyl(r,"face",radius*0.86,0.002,(0,-0.0055,z),CREAM,"paper",axis="Y")
    for i in range(12):
        a = i*math.tau/12
        _ball(r,"hour_mark",(0.0014,0.0007,0.0014),(radius*.73*math.sin(a),-0.007,z+radius*.73*math.cos(a)),DARK)
    for label,a,length,thick in (("hour",(hour+minute/60)*math.tau/12,radius*.46,.0016),
                                 ("minute",minute*math.tau/60,radius*.67,.0011)):
        _tube(r,label,[(0,-.008,z),(length*math.sin(a),-.008,z+length*math.cos(a))],thick,DARK,"metal")
    _ball(r,"pin",(.002,.002,.002),(0,-.009,z),"#B25637")
    _anchors(r, center=(0,-.009,z))


@_register
def picture(r, *, width=0.075, height=0.06, color=WOOD):
    """Framed miniature painting with raised painted sky, hills and a sun."""
    _box(r,"backing",(width,.005,height),(0,0,height/2),color)
    _box(r,"sky",(width-.01,.002,height-.01),(0,-.0035,height/2),"#8CB8C1","paper")
    _ball(r,"hill",(width*.37,.0015,height*.20),(-width*.12,-.005,height*.25),"#648553","paper")
    _ball(r,"hill",(width*.25,.0014,height*.17),(width*.22,-.0055,height*.21),"#8DA064","paper")
    _ball(r,"sun",(.006,.001,.006),(width*.22,-.005,height*.71),"#E7B954","paper")
    for x in (-width/2+.003,width/2-.003):
        _box(r,"frame",(.006,.009,height),(x,-.003,height/2),color)
    for z in (.003,height-.003):
        _box(r,"frame",(width,.009,.006),(0,-.003,z),color)
    _anchors(r, center=(0,-.004,height/2))


@_register
def rug(r, *, width=.18, depth=.12, color="#A6503E", trim="#D7BA78"):
    """Low woven rug, contrasting inset and rolled fringe stitches."""
    _box(r,"rug",(width,depth,.002),(0,0,.001),trim,"fabric")
    _box(r,"field",(width-.012,depth-.012,.0008),(0,0,.002),color,"fabric")
    for side in (-1,1):
        for i in range(15):
            x = (i/14-.5)*(width-.008)
            _tube(r,"fringe",[(x,side*(depth/2-.002),.001),(x+.001,side*(depth/2+.006),.001)],.0008,trim,"fabric")
    _anchors(r, center=(0,0,.0025))


@_register
def book(r, *, width=.034, depth=.045, height=.009, color="#7C463D"):
    """Closed clothbound book lying flat, cream page block and rounded spine."""
    _box(r,"pages",(width-.002,depth-.003,height-.002),(0,0,height/2),CREAM,"paper")
    for z in (.0007,height-.0007):
        _box(r,"cover",(width,depth,.0014),(0,0,z),color,"fabric")
    _box(r,"spine",(.003,depth,height),(-width/2+.001,0,height/2),color,"fabric")
    for y in (-.012,.012):
        _box(r,"spine_band",(.0006,.002,height*.75),(-width/2-.0004,y,height/2),"#CEAA60","paper")
    _anchors(r, top=(0,0,height))


@_register
def book_stack(r, *, count=4, color="#6A7E83"):
    """Slightly skewed stack of count closed books."""
    colors = [color,"#8E5447","#B59755","#527663"]
    rand = random.Random(int(r["seed"]))
    for i in range(count):
        child = build_prop("book",at=(rand.uniform(-.003,.003),0,i*.009),heading=rand.uniform(-.13,.13),color=colors[i%4],seed=i)
        child.parent = r
    _anchors(r, top=(0,0,count*.009))


@_register
def plant(r, *, color="#47764A", pot="#AD6546", height=.095):
    """Terracotta pot with splayed sculpted oval leaves and stems."""
    _vessel(r,"pot",[(.001,0),(.013,0),(.019,.030),(.017,.033),(.014,.030),(.010,.004),(.001,.004)],color=pot)
    _ring(r,"lip",(0,0,.029),.017,.0025,pot)
    _cyl(r,"soil",.014,.002,(0,0,.025),"#4C3E2B","default")
    for i in range(8):
        a=i*2.4
        z=.045+(height-.045)*(i%3)/2
        end=(.020*math.cos(a),.020*math.sin(a),z)
        _tube(r,"stem",[(0,0,.025),end],.0014,color,"default")
        leaf=_ball(r,"leaf",(.009,.004,.020),end,color)
        leaf.data.transform(Matrix.Translation(end) @ Matrix.Rotation(a,4,"Z") @ Matrix.Rotation(.65,4,"Y") @ Matrix.Translation(Vector(end)*-1))
    _anchors(r, pot=(0,0,.030), top=(0,0,height))


@_register
def crate(r, *, width=.075, depth=.065, height=.060, color=WOOD):
    """Open slatted wooden crate with corner posts and visible board gaps."""
    _box(r,"bottom",(width,depth,.005),(0,0,.0025),color)
    _legs(r,width-.006,depth-.006,height,color,.003)
    for z in (height*.23,height*.55,height*.87):
        for y in (-depth/2,depth/2):
            _box(r,"slat",(width,.004,height*.24),(0,y,z),color)
        for x in (-width/2,width/2):
            _box(r,"slat",(.004,depth,height*.24),(x,0,z),color)
    _anchors(r, top=(0,0,height), inside=(0,0,.006))


@_register
def ball(r, *, radius=.023, color="#B74B36", stripe=CREAM):
    """Toy ball with a contrasting raised equatorial stripe."""
    _ball(r,"ball",(radius,radius,radius),(0,0,radius),color)
    _ring(r,"stripe",(0,0,radius),radius*.997,.0012,stripe,"default")
    _anchors(r, center=(0,0,radius))
    r["roll_radius"] = radius


@_register
def toaster(r, *, color=CREAM, toast=True):
    """Rounded two-slot toaster with optional bread, knob and side lever."""
    _legs(r,.047,.026,.004,DARK,.003)
    _box(r,"body",(.065,.043,.034),(0,0,.020),color,"metal")
    for y in (-.010,.010):
        _box(r,"slot",(.045,.005,.001),(0,y,.0375),DARK,"default")
        if toast:
            _box(r,"crust",(.036,.006,.021),(0,y,.043),"#9B602E","default")
            _box(r,"bread",(.030,.0065,.016),(0,y-.0003,.044),"#E3BF79","default")
    _box(r,"lever",(.012,.009,.004),(.036,-.003,.016),DARK,"default")
    _ball(r,"knob",(.004,.002,.004),(.021,-.023,.015),DARK)
    _anchors(r, lever=(.040,-.003,.016), top=(0,0,.038))


@_register
def radio(r, *, color="#7C4E39", trim="#D5B878"):
    """Vintage wireless with speaker grille, tuning scale, handle and two knobs."""
    _legs(r,.070,.028,.006,DARK,.003)
    _box(r,"case",(.092,.040,.060),(0,0,.035),color)
    _box(r,"speaker",(.045,.003,.043),(-.017,-.021,.034),trim,"fabric")
    for i in range(7):
        _box(r,"grille",(.002,.0015,.038),(-.034+i*.0055,-.023,.034),color)
    _box(r,"dial",(.028,.003,.014),(.026,-.022,.047),CREAM,"paper")
    for i in range(6):
        _box(r,"tick",(.0008,.001,.007),(.015+i*.004,-.024,.047),DARK,"metal")
    for x in (.016,.034):
        _cyl(r,"knob",.005,.005,(x,-.024,.021),trim,"metal",axis="Y")
    _tube(r,"handle",[(-.025,0,.064),(-.023,0,.078),(.023,0,.078),(.025,0,.064)],.003,DARK,"default")
    _anchors(r, handle=(0,0,.078), dial=(.026,-.026,.047))


@_register
def lever(r, *, color="#BB5336", metal="#8B9694", angle=-25):
    """Pivoting lever: positive local Y rotation throws the red knob toward +X."""
    _box(r,"base",(.069,.055,.012),(0,0,.006),metal,"metal")
    for x in (-.026,.026):
        for y in (-.019,.019):
            _cyl(r,"bolt",.003,.002,(x,y,.013),"#BCB8A6","metal",top=.0025)
    _cyl(r,"quadrant",.024,.012,(0,0,.027),metal,"metal",axis="Y")
    arm = bpy.data.objects.new(r.name + ".arm", None)
    util.link(arm)
    arm.parent, arm.location = r, (0, 0, .030)
    arm.rotation_euler.y = math.radians(angle)
    _tube(arm,"shaft",[(0,0,0),(0,0,.064)],.003,metal,"metal")
    _ball(arm,"grip",(.010,.009,.011),(0,0,.064),color)
    _anchors(r, handle=(0,0,.064), pivot=(0,0,.030))
    r["anchor_parts"] = {"handle": arm.name}


@_register
def gear(r, *, radius=.027, teeth=12, color="#B29C64"):
    """Thick toothed gear standing upright with open hub and three spokes."""
    z=radius+.003
    _ring(r,"rim",(0,0,z),radius*.72,radius*.13,color,"metal",plane="XZ")
    _ring(r,"hub",(0,0,z),radius*.22,radius*.10,color,"metal",plane="XZ")
    for i in range(3):
        a=i*math.tau/3
        _tube(r,"spoke",[(radius*.22*math.sin(a),0,z+radius*.22*math.cos(a)),
                          (radius*.72*math.sin(a),0,z+radius*.72*math.cos(a))],radius*.09,color,"metal")
    for i in range(teeth):
        a=i*math.tau/teeth
        o=util.rounded_box("tooth",(radius*.29,.009,radius*.30),bevel=.18)
        o.data.transform(Matrix.Translation((radius*.91*math.sin(a),0,z+radius*.91*math.cos(a))) @ Matrix.Rotation(a,4,"Y"))
        _part(r,o,"metal",color)
    _anchors(r, hub=(0,0,z))


@_register
def pipe(r, *, color="#89948D", radius=.007):
    """Bent open-ended pipe segment with chunky coupling collars."""
    pts=[(-.035,0,.010),(-.007,0,.010),(.006,0,.015),(.010,0,.028),(.010,0,.060)]
    _tube(r,"pipe",pts,radius,color,"metal",cap=False)
    for at,plane in (((-.035,0,.010),"YZ"),((.010,0,.060),"XY")):
        _ring(r,"collar",at,radius*1.03,.002,color,"metal",plane)
    # Recessed dark interior stops the brightly lit far wall reading as a cap.
    _cyl(r,"upper_interior",radius*.94,.0006,(.010,0,.052),DARK,"default")
    _cyl(r,"inlet_interior",radius*.94,.0006,(-.028,0,.010),DARK,"default",axis="X")
    _anchors(r, inlet=pts[0], outlet=pts[-1])


@_register
def tree(r, *, height=.40, color="#5B823E", trunk="#795337"):
    """Lollipop orchard tree with branching trunk and clustered clay canopy."""
    _cyl(r,"trunk",.017,height*.68,(0,0,height*.34),trunk,"wood",top=.010)
    for i in range(3):
        a=i*2.1
        _tube(r,"branch",[(0,0,height*.38),(.055*math.cos(a),.055*math.sin(a),height*.75)],.007,trunk)
    for i in range(9):
        a=i*2.4
        _ball(r,"canopy",(.061,.053,.067),(.055*math.cos(a),.044*math.sin(a),height-.067-(i%3)*.032),color)
    _anchors(r, trunk=(0,-.017,height*.25), canopy=(0,0,height-.04))


@_register
def bush(r, *, width=.12, height=.075, color="#527A40"):
    """Asymmetric leafy shrub with visible branching, not a radial pumpkin."""
    rand=random.Random(int(r["seed"]))
    base=util.hex_rgb(color)
    for i in range(5):
        x=(i/4-.5)*width*.67
        y=rand.uniform(-.09,.09)*width
        z=height*(.46 if i in (0,4) else .62)
        _tube(r,"twig",[(0,0,.003),(x,y,z)],.0024,"#71543A","wood")
        tint=tuple(min(1,c*(.85+.075*i)) for c in base[:3])
        _ball(r,"foliage",(width*.23,width*.22,height*.31),(x,y,z),tint)
        for j in range(5):
            a=j*2.4+i
            _ball(r,"leaf",(width*.065,width*.030,height*.08),
                  (x+width*.16*math.sin(a),y-width*.17,z+height*.20*math.cos(a)),tint)
    _anchors(r, top=(0,0,height*.9))


@_register
def flower(r, *, height=.07, color="#E0A43E", leaf="#537847"):
    """Upright daisy-like flower facing -Y, with two leaves and five petals."""
    _tube(r,"stem",[(0,0,.001),(.002,0,height*.5),(0,0,height)],.0015,leaf,"default")
    for s in (-1,1):
        _ball(r,"leaf",(.012,.003,.005),(s*.009,0,height*.42),leaf)
    for i in range(5):
        a=i*math.tau/5
        _ball(r,"petal",(.007,.003,.008),(.008*math.sin(a),0,height+.008*math.cos(a)),color)
    _ball(r,"pollen",(.005,.004,.005),(0,-.004,height),"#9E6634")
    _anchors(r, bloom=(0,-.004,height))


@_register
def fence(r, *, length=.45, height=.12, color="#DED2AD"):
    """Picket fence segment; length is the total approximate span."""
    count=max(3,round(length/.030))
    for i in range(count):
        x=(i/(count-1)-.5)*(length-.018)
        _box(r,"picket",(.017,.009,height-.009),(x,0,(height-.009)/2),color)
        _ball(r,"round_tip",(.0085,.0045,.0085),(x,0,height-.009),color,"wood")
    for z in (height*.26,height*.69):
        _box(r,"rail",(length,.011,.014),(0,.008,z),color)
    _anchors(r, center=(0,0,height*.5), left=(-length/2,0,0), right=(length/2,0,0))


@_register
def cloud(r, *, width=.14, height=.40, color="#F3F0E5", wire="#92948A", shape="plain"):
    """Wire-supported cloud silhouette: plain, teapot, rabbit or dark flat-bottomed storm."""
    _cyl(r,"wire",.0008,height-.025,(0,.007,(height-.025)/2),wire,"metal")
    z = height - .030
    if shape == "plain":
        for x,s,dz in ((-.30,.25,-.005),(0,.32,.010),(.30,.24,-.008),(-.10,.25,-.012)):
            _ball(r,"cloud",(width*s,.018,width*s*.68),(width*x,0,z+dz),color)
    elif shape == "teapot":
        _ball(r,"belly",(width*.29,.020,width*.22),(0,0,z),color)
        _ring(r,"handle",(-width*.34,0,z),width*.18,width*.045,color,"default",plane="XZ")
        _tube(r,"spout",[(width*.20,0,z-width*.09),(width*.39,0,z),
                         (width*.49,0,z+width*.18)],[width*.09,width*.065,width*.045],color,"default")
        _ball(r,"lid",(width*.23,.021,width*.045),(0,0,z+width*.21),color)
        _ball(r,"knob",(width*.05,.013,width*.055),(0,0,z+width*.29),color)
    elif shape == "rabbit":
        _ball(r,"body",(width*.27,.021,width*.22),(-width*.08,0,z-width*.04),color)
        _ball(r,"head",(width*.15,.021,width*.15),(width*.20,0,z+width*.12),color)
        for x,dz in ((.14,.0),(.28,-.025)):
            ear = _ball(r,"ear",(width*.045,.014,width*.23),(width*x,0,z+width*.36+dz),color)
            ear.data.transform(Matrix.Translation((width*x,0,z+width*.36+dz))
                               @ Matrix.Rotation(-.14 if x < .2 else .15,4,"Y")
                               @ Matrix.Translation((-width*x,0,-z-width*.36-dz)))
        _ball(r,"tail",(width*.10,.020,width*.10),(-width*.37,0,z-width*.05),color)
        _ball(r,"foot",(width*.18,.021,width*.065),(width*.05,0,z-width*.23),color)
    elif shape == "storm":
        import bmesh
        color = "#424C5D" if color == "#F3F0E5" else color
        blobs=[]
        for x,s,dz in ((-.36,.23,0),(-.13,.29,.012),(.14,.30,.018),(.38,.22,0)):
            blobs.append(_ball(r,"thunderhead",(width*s,.026,width*s*.80),(width*x,0,z+dz),color))
        obj=util.join(blobs,"storm_cloud")
        util.remesh(obj,voxel=width/90,smooth_iters=3)
        bm=bmesh.new()
        bm.from_mesh(obj.data)
        bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),
                               plane_co=(0,0,z-width*.10),plane_no=(0,0,1),clear_inner=True)
        bmesh.ops.holes_fill(bm,edges=[e for e in bm.edges if e.is_boundary],sides=0)
        bm.to_mesh(obj.data)
        bm.free()
    else:
        raise ValueError("cloud shape must be plain, teapot, rabbit or storm")
    _anchors(r, cloud=(0,0,height-.03))


@_register
def rock(r, *, width=.06, color="#85877B"):
    """Squashed irregular clay pebble."""
    _ball(r,"stone",(width*.5,width*.36,width*.29),(0,0,width*.27),color)
    _anchors(r, top=(0,0,width*.54))


@_register
def mushroom(r, *, height=.05, color="#AE4936", spots=CREAM):
    """Fairytale toadstool with pale stalk, broad cap and raised cream spots."""
    _cyl(r,"stem",.006,height*.75,(0,0,height*.375),CREAM,"default",top=.004)
    _ball(r,"cap",(.023,.020,.011),(0,0,height-.011),color)
    for i in range(7):
        a=i*2.4
        d=.013 if i else 0
        _ball(r,"spot",(.003,.0025,.0014),(d*math.cos(a),d*math.sin(a),height-.0025),spots)
    _anchors(r, cap=(0,0,height))


@_register
def block(r, *, size=(.05, .03, .04), color="#D9742B", text="", text_color=DARK, role="default"):
    """Chunky clay building block (width, depth, height in metres); optional lettering on the front (-Y)."""
    w, d, h = size
    _box(r, "block", (w, d, h), (0, 0, h / 2), color, role)
    if text:
        _text(r, text, (0, -d / 2 - .0006, h / 2), w * .84, h * .42, color=text_color)
    _anchors(r, top=(0, 0, h), front=(0, -d / 2, h / 2), grip=(0, 0, h * .6))


@_register
def bridge(r, *, length=.11, height=.035, width=.034, color="#3E6753", road="#55595C", line="#F3E7D3"):
    """One span of a toy road bridge along X: two piers, an arch on each side, a grey road deck with a
    dashed centre line and coloured railings. Anchors `start` and `end` are the deck ends at rolling
    height, so spans can be lined up end to end."""
    for x in (-length * .38, length * .38):
        _box(r, "pier", (length * .14, width * .86, height - .006), (x, 0, (height - .006) / 2), color, "default")
    for y in (-width / 2 + .003, width / 2 - .003):
        arch = [(length * .38 * math.cos(a), y, .004 + (height - .012) * math.sin(a)) for a in
                [math.pi * i / 10 for i in range(11)]]
        _tube(r, "arch", arch, .0035, color, "default")
        _box(r, "rail", (length, .004, .007), (0, y * 1.02, height + .0035), color, "default")
    _box(r, "deck", (length, width, .008), (0, 0, height - .004), road, "default")
    for i in range(4):
        _box(r, "dash", (length * .13, .003, .0012), (-length * .375 + i * length * .25, 0, height + .0004), line, "paper")
    _anchors(r, start=(-length / 2, 0, height), end=(length / 2, 0, height), top=(0, 0, height))


@_register
def star_map(r, *, width=.3, height=.12, size=.009, color="#F0A36B", wire="#B9A88E", stars=None, shape="ball"):
    """Wall decoration facing -Y: clay stars joined in order by thin wire, a constellation. `stars`
    are (x, z) pairs, each 0..1 across the width and height; five by default. shape "star" draws
    five-pointed stars instead of beads."""
    stars = stars or [(0, .3), (.24, .95), (.5, .45), (.76, 1.0), (1, .25)]
    points = [((x - .5) * width, 0, z * height) for x, z in stars]
    _tube(r, "wire", points, .0012, wire, "metal")
    for point in points:
        if shape == "star":
            _prism(r, "star", _star_outline(size * 1.6), size * .7, point, color)
        else:
            _ball(r, "star", (size, size * .45, size), point, color, "default")
    _anchors(r, center=(0, 0, height / 2))


@_register
def sign(r, *, width=.11, height=.19, color=WOOD, board=CREAM, text=""):
    """Signpost facing -Y; text is centered and fitted to its board."""
    _box(r,"post",(.012,.012,height-.010),(0,.005,(height-.010)/2),color)
    _box(r,"board",(width,.013,.055),(0,0,height-.0275),board)
    for x in (-width*.4,width*.4):
        _ball(r,"nail",(.0015,.001,.0015),(x,-.007,height-.008),"#5A594C","metal")
    if text:
        _text(r,text,(0,-.0075,height-.0275),width*.73,.020)
    _anchors(r, board=(0,-.008,height-.0275))


@_register
def bed(r, *, width=.14, length=.25, color=WOOD, blanket="#7C9184"):
    """Single miniature bed with headboard, pillow and folded blanket."""
    _legs(r,width-.022,length-.022,.045,color,.006)
    _box(r,"frame",(width,length,.022),(0,0,.044),color)
    _box(r,"mattress",(width-.01,length-.012,.025),(0,0,.065),CREAM,"fabric")
    _box(r,"headboard",(width+.01,.013,.11),(0,length/2,.074),color)
    _box(r,"footboard",(width+.01,.012,.06),(0,-length/2,.046),color)
    _box(r,"blanket",(width-.007,length*.63,.006),(0,-length*.12,.080),blanket,"fabric")
    _box(r,"pillow",(width*.73,length*.21,.016),(0,length*.32,.084),CREAM,"fabric")
    _anchors(r, pillow=(0,length*.32,.092), mattress=(0,0,.077))


@_register
def window_box(r, *, width=.16, color="#9A6647", flowers="#C96D60"):
    """Wall/window planter trough with a row of flowering clay plants."""
    _box(r,"planter",(width,.038,.030),(0,0,.015),color)
    _box(r,"soil",(width-.008,.030,.002),(0,0,.031),"#4D3B2B","default")
    for x in (-width*.34,0,width*.34):
        child=build_prop("flower",height=.045,color=flowers,at=(x,0,.032),seed=int(r["seed"])+round(x*1000))
        child.parent=r
    _anchors(r, rim=(0,-.020,.030), top=(0,0,.090))


@_register
def crumbs(r, *, count=12, spread=.035, color="#C78D45"):
    """Seeded biscuit-coloured crumbs within a disc of radius spread (metres)."""
    rand = random.Random(int(r["seed"]))
    for i in range(max(1, int(count))):
        a, d, s = rand.random()*math.tau, spread*math.sqrt(rand.random()), rand.uniform(.0007,.0018)
        if i%4 == 0:
            s *= 1.8
        obj = util.ellipsoid("crumb",(s,s*rand.uniform(.55,1.),s*rand.uniform(.6,1.2)),
                             (d*math.cos(a),d*math.sin(a),s),subdiv=1)
        center = Vector((d*math.cos(a),d*math.sin(a),s))
        for vertex in obj.data.vertices:
            vertex.co = center + (vertex.co-center)*rand.uniform(.65,1.22)
        _part(r,obj,"default",color)
        if i%3 == 0:
            _ball(r,"chocolate_fleck",(s*.30,s*.25,s*.15),tuple(center+Vector((0,0,s*.65))),"#65402A")
    _anchors(r, center=(0,0,.001))


@_register
def dog_biscuit(r, *, color="#BD864A"):
    """Four-lobed bone-shaped dog biscuit lying flat."""
    _box(r,"bone_middle",(.028,.012,.005),(0,0,.0025),color,"default")
    for x in (-.016,.016):
        for y in (-.0055,.0055):
            _ball(r,"bone_end",(.007,.006,.0028),(x,y,.0028),color)
    for x in (-.007,0,.007):
        _ball(r,"baked_dimple",(.001,.001,.0003),(x,0,.0052),"#80562D")
    _anchors(r, center=(0,0,.0055), grip=(0,0,.0025))


@_register
def flag(r, *, text="MINE", color="#E8DCA9"):
    """Cocktail-stick claim flag; lettering faces -Y."""
    _cyl(r,"stick",.001,.077,(0,0,.0385),WOOD,"wood")
    _box(r,"flag",(.049,.001,.027),(.025,0,.061),color,"paper")
    _text(r,text,(.025,-.0007,.061),.043,.014)
    _anchors(r, grip=(0,0,.021), top=(.025,0,.0745))


@_register
def note(r, *, text="I.O.U.", paw=False, color="#F2E9CB"):
    """Paper slip tilted 12 degrees toward -Y; optional dark four-toed paw print."""
    sheet = bpy.data.objects.new(r.name+".sheet",None)
    util.link(sheet)
    sheet.parent = r
    sheet.rotation_euler.x = math.radians(12)
    sheet.location.z = .006
    _box(sheet,"paper",(.068,.046,.0007),(0,0,0),color,"paper")
    _text(sheet,text,(0,.004 if paw else 0,.0005),.060,.016,tilt=0)
    if paw:
        _ball(sheet,"paw_pad",(.005,.004,.00025),(0,-.013,.0006),DARK,"paper")
        for x,y in ((-.006,-.009),(-.0025,-.006),(.0025,-.006),(.006,-.009)):
            _ball(sheet,"paw_toe",(.0019,.0023,.00025),(x,y,.0006),DARK,"paper")
    _anchors(r, center=(0,0,.006))


@_register
def kettle(r, *, color="#9BA9A1", handle=DARK):
    """Stove kettle with domed lid, raised spout and tall arched carrying handle."""
    _cyl(r,"base",.026,.004,(0,0,.002),DARK,"metal")
    _vessel(r,"steel_body",[(.001,.003),(.025,.003),(.027,.007),(.025,.017),
                           (.017,.033),(.011,.036),(.001,.036)],color=color,role="metal")
    _cyl(r,"lid",.013,.003,(0,0,.037),color,"metal",top=.010)
    _ball(r,"knob",(.004,.004,.003),(0,0,.041),handle)
    _tube(r,"spout",[(.019,0,.013),(.033,0,.023),(.041,0,.030)],
          [.010,.007,.006],color,"metal",cap=False)
    _cyl(r,"whistle_cap",.007,.004,(.043,0,.031),handle,"metal",axis="X")
    _ball(r,"whistle_vent",(.0006,.002,.002),(.0455,0,.031),DARK)
    _tube(r,"whistle_lifter",[(.034,0,.032),(.033,0,.038),(.039,0,.039)],.0015,handle,"default")
    pts=[(-.024,0,.024),(-.025,0,.048),(-.018,0,.060),
         (0,0,.064),(.018,0,.060),(.025,0,.048),(.024,0,.024)]
    _tube(r,"handle",pts,.0035,handle,"default")
    _anchors(r, handle=(0,0,.064), spout=(.046,0,.031), lid=(0,0,.044))


@_register
def bell(r, *, color="#C3A14F"):
    """Brass desk service bell with black base and central plunger."""
    _cyl(r,"base",.022,.005,(0,0,.0025),DARK,"default")
    _vessel(r,"bell",[(.019,.005),(.019,.009),(.015,.019),(.007,.024),
                      (.002,.024),(.002,.020),(.012,.016),(.016,.007)],color=color,role="metal")
    _cyl(r,"plunger",.0016,.007,(0,0,.026),DARK,"metal")
    _ball(r,"button",(.005,.005,.0018),(0,0,.030),color,"metal")
    _anchors(r, button=(0,0,.0318))


@_register
def sugar_cube(r, *, size=.009, color="#F5EDD9"):
    """Single small sugar cube with visible crystalline surface grains."""
    _box(r,"cube",(size,)*3,(0,0,size/2),color,"default")
    rand = random.Random(int(r["seed"]))
    grains=[]
    for axis in range(3):
        for sign in (-1,1):
            for i in range(36):
                p=Vector((rand.uniform(-.36,.36)*size,rand.uniform(-.36,.36)*size,
                          rand.uniform(-.36,.36)*size))
                p[axis]=sign*size*.49
                p.z+=size/2
                g=util.ellipsoid("crystal",(size*rand.uniform(.018,.035),)*3,p,subdiv=1)
                grains.append(g)
    _part(r,util.join(grains,"sugar_crystals"),"default",color)
    _anchors(r, center=(0,0,size/2), top=(0,0,size))


@_register
def toast(r, *, color="#D7AF6E", crust="#8C5129"):
    """One upright slice of toast, squared base and two rounded shoulders."""
    _box(r,"crust",(.034,.006,.029),(0,0,.0145),crust,"default")
    _box(r,"crumb",(.028,.0066,.025),(0,-.0003,.015),color,"default")
    for x in (-.008,.008):
        _ball(r,"crust_crown",(.012,.003,.010),(x,0,.028),crust)
        _ball(r,"crumb_crown",(.009,.0034,.0075),(x,-.0003,.028),color)
    _anchors(r, grip=(0,0,.015), top=(0,0,.038))


@_register
def raindrop(r, *, color="#8AC6DC", size=.012):
    """Tear-shaped blue clay raindrop, not a transparent water simulation."""
    _ball(r,"droplet",(size*.36,size*.30,size*.40),(0,0,size*.40),color,"ceramic")
    _cyl(r,"taper",size*.32,size*.65,(0,0,size*.72),color,"ceramic",top=0)
    _anchors(r, center=(0,0,size*.5), tip=(0,0,size*1.045))


@_register
def tea_towel(r, *, color="#DED6BC", stripe="#657C86"):
    """Rumpled folded striped tea towel; thin rippled layers, stitched hems."""
    def height(x,y):
        return .0018+.0008*math.sin(x*270+y*140)+.0005*math.cos(y*450)
    for layer in range(2):
        verts=[]
        for i in range(17):
            for j in range(13):
                x=(i/16-.5)*(.064 if layer==0 else .051)
                y=(j/12-.5)*.038
                verts.append((x+.003*layer,y,height(x,y)+layer*.0011))
        mesh=bpy.data.meshes.new("rumpled_cloth")
        mesh.from_pydata(verts,[],[(i*13+j,(i+1)*13+j,(i+1)*13+j+1,i*13+j+1)
                                  for i in range(16) for j in range(12)])
        mesh.update()
        obj=bpy.data.objects.new("folded_cloth",mesh)
        util.link(obj)
        solid=obj.modifiers.new("cloth_thickness","SOLIDIFY")
        solid.thickness=.00035
        _part(r,obj,"fabric",color)
    for x in (-.019,-.016,.018,.021):
        _tube(r,"woven_stripe",[(x,(j/20-.5)*.038,height(x-.003,(j/20-.5)*.038)+.0013)
                               for j in range(21)],.00035,stripe,"fabric")
    for y in (-.018,.018):
        _tube(r,"stitched_hem",[(x,y,height(x,y)+.0002) for x in [i*.004-.032 for i in range(17)]],
              .00022,stripe,"fabric")
        for i in range(17):
            x=-.030+i*.0037
            _tube(r,"thread",[(x,y,height(x,y)),(x+.0004,y+math.copysign(.002,y),height(x,y)-.0004)],
                  .00016,color,"fabric")
    _anchors(r, top=(0,0,.004))


@_register
def oil_can(r, *, color="#AC4934"):
    """Vintage pump oil can with long tapered spout and rear loop handle."""
    _cyl(r,"body",.017,.027,(0,0,.0135),color,"metal",top=.012)
    _cyl(r,"cap",.008,.004,(0,0,.029),DARK,"metal")
    _tube(r,"spout",[(.004,0,.029),(.018,0,.040),(.039,0,.050)],[.0035,.0025,.001], "#9EAA9F","metal")
    _ring(r,"handle",(-.016,0,.021),.010,.0025,color,"metal",plane="XZ")
    _tube(r,"pump",[(-.008,0,.031),(-.009,0,.041),(.005,0,.040)],.0018,DARK,"metal")
    _anchors(r, handle=(-.025,0,.021), spout=(.039,0,.050))


@_register
def blueprint(r, *, text="", width=.13, height=.085, color="#326887"):
    """Wall-pinned blue drawing sheet facing -Y, optional legible title."""
    _box(r,"paper",(width,.0008,height),(0,0,height/2),color,"paper")
    ink="#DDE7DA"
    for x in (-width*.44,width*.44):
        _tube(r,"border",[(x,-.0006,height*.06),(x,-.0006,height*.94)],.00025,ink,"paper")
    for z in (height*.06,height*.94):
        _tube(r,"border",[(-width*.44,-.0006,z),(width*.44,-.0006,z)],.00025,ink,"paper")
    _ring(r,"wheel",(-width*.20,-.0007,height*.40),height*.16,.0006,ink,"paper",plane="XZ")
    _ring(r,"wheel",(width*.20,-.0007,height*.40),height*.16,.0006,ink,"paper",plane="XZ")
    for z in (.35,.62):
        _tube(r,"dimension",[(-width*.32,-.0008,height*z),(width*.32,-.0008,height*z)],.0004,ink,"paper")
    _tube(r,"machine_outline",[(-width*.28,-.0008,height*.40),(-width*.20,-.0008,height*.68),
                               (width*.18,-.0008,height*.68),(width*.28,-.0008,height*.40)],.0006,ink,"paper")
    # Dimension strings, extension lines, wheel spokes and a conventional title
    # block distinguish a technical drawing from a decorative two-wheel sign.
    for z in (.18,.74):
        _tube(r,"dimension_rule",[(-width*.35,-.0009,height*z),(width*.35,-.0009,height*z)],.00022,ink,"paper")
        for x in (-width*.35,width*.35):
            _tube(r,"extension",[(x,-.0009,height*(z-.05)),(x,-.0009,height*(z+.05))],.00022,ink,"paper")
            direction=1 if x<0 else -1
            for dz in (-.018,.018):
                _tube(r,"arrow",[(x+direction*width*.04,-.0009,height*(z+dz)),(x,-.0009,height*z)],
                      .00022,ink,"paper")
    for x in (-width*.2,width*.2):
        for i in range(8):
            a=i*math.tau/8
            _tube(r,"spoke",[(x,-.0009,height*.4),
                            (x+height*.15*math.cos(a),-.0009,height*(.4+.15*math.sin(a)))],.00023,ink,"paper")
        for dz in (-.23,.23):
            _tube(r,"centreline",[(x,-.0009,height*(.4+dz)),(x,-.0009,height*(.4+dz*.5))],.0002,ink,"paper")
    for z in (.08,.12,.16):
        _tube(r,"title_rule",[(width*.08,-.0009,height*z),(width*.43,-.0009,height*z)],.00020,ink,"paper")
    for x in (.08,.25,.43):
        _tube(r,"title_cell",[(width*x,-.0009,height*.08),(width*x,-.0009,height*.16)],.0002,ink,"paper")
    if text:
        _text(r,text,(0,-.001,height*.83),width*.80,height*.12,color=ink)
    for x in (-width*.42,width*.42):
        _ball(r,"pin",(.0018,.001,.0018),(x,-.001,height*.91),"#B95840","metal")
    _anchors(r, center=(0,-.001,height/2), top=(0,0,height))


# ------------------------------------------------ designer-toy objects ----
# Generic designer-toy objects: thick, round-cornered, satin. Fronts face -Y.
ORANGE, SAGE, PAPER, INK, BONE, BRASS = "#E08A4F", "#5C947F", "#FFF4E8", "#3E3228", "#F7EEDD", "#CDB380"


def _chunk(r, name, size, at, color, role="default", bevel=.3):
    """Box with generously rounded corners (bevel: share of the smallest side)."""
    o = util.rounded_box(name, size, bevel=bevel, segments=6)
    o.data.transform(Matrix.Translation(at))
    return _part(r, o, role, color)


def _prism(r, name, outline, thick, at, color, role="default", bevel=.3):
    """A flat shape standing in the XZ plane, `thick` deep along Y, with softened rims.
    outline: (x, z) pairs going anticlockwise as seen from the front."""
    bm = bmesh.new()
    front = [bm.verts.new((x, -thick / 2, z)) for x, z in outline]
    back = [bm.verts.new((x, thick / 2, z)) for x, z in outline]
    caps = [bm.faces.new(front), bm.faces.new(back[::-1])]
    for i in range(len(outline)):
        j = (i + 1) % len(outline)
        bm.faces.new((front[j], front[i], back[i], back[j]))
    rim = list({e for f in caps for e in f.edges})
    bmesh.ops.bevel(bm, geom=rim, offset=thick * bevel, segments=3, profile=.5, affect="EDGES", clamp_overlap=True)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bmesh.ops.translate(bm, vec=Vector(at), verts=bm.verts)
    obj = util.new_mesh_object(name, bm)
    for face in obj.data.polygons:
        face.use_smooth = len(face.vertices) <= 4  # caps stay flat
    return _part(r, obj, role, color)


def _slab(r, name, width, height, thick, at, color, role="default", corner=.25):
    """Upright card with rounded corners (corner: share of the shorter side), facing -Y."""
    c = corner * min(width, height)
    outline = []
    for cx, cz, a0 in ((width / 2 - c, height / 2 - c, 0), (-width / 2 + c, height / 2 - c, 90),
                       (-width / 2 + c, -height / 2 + c, 180), (width / 2 - c, -height / 2 + c, 270)):
        outline += [(cx + c * math.cos(math.radians(a0 + 15 * i)), cz + c * math.sin(math.radians(a0 + 15 * i))) for i in range(7)]
    return _prism(r, name, outline, thick, at, color, role)


def _star_outline(radius):
    """Five-pointed star, one point up, with blunted tips (anticlockwise from the top)."""
    def at(angle, r):
        return (-r * math.sin(math.radians(angle)), r * math.cos(math.radians(angle)))

    pts = []
    for i in range(5):
        tip, before, after = at(72 * i, 1.0), at(72 * i - 36, .46), at(72 * i + 36, .46)
        pts += [before, tuple(tip[k] * .82 + before[k] * .18 for k in (0, 1)), at(72 * i, .95),
                tuple(tip[k] * .82 + after[k] * .18 for k in (0, 1))]
    return [(x * radius, z * radius) for x, z in pts]


def _disk(r, name, radius, height, at, color, role="default"):
    """Round slab with rolled edges, standing on `at`."""
    b = min(height * .45, radius * .25)
    profile = [(0, 0)] + [(radius - b + b * math.cos(a), b + b * math.sin(a)) for a in [math.radians(-90 + 18 * i) for i in range(6)]]
    profile += [(radius - b + b * math.cos(a), height - b + b * math.sin(a)) for a in [math.radians(18 * i) for i in range(6)]] + [(0, height)]
    return _vessel(r, name, profile, at, color, role)


def _lean(r, name, back=0.0, at=(0, 0, 0)):
    """Child frame that leans `back` degrees away from the camera about its bottom edge."""
    frame = bpy.data.objects.new(r.name + "." + name, None)
    util.link(frame)
    frame.parent = r
    frame.location = at
    frame.rotation_euler.x = -math.radians(back)
    return frame


def _leaned(back, x, y, z):
    """Where a point of a `_lean` frame ends up."""
    a = math.radians(back)
    return (x, y * math.cos(a) + z * math.sin(a), -y * math.sin(a) + z * math.cos(a))


def _bubble(r, width, height, at, color="#FFFFFF", dot=INK, thick=.003):
    """Speech bubble with three dots, facing -Y, centred on `at`."""
    x, y, z = at
    _slab(r, "bubble", width, height, thick, at, color, corner=.42)
    _ball(r, "bubble_tail", (height * .2, thick * .5, height * .2), (x - width * .26, y, z - height * .5), color)
    for i in (-1, 0, 1):
        _ball(r, "bubble_dot", (height * .1, thick * .4, height * .1), (x + i * width * .22, y - thick * .5, z), dot)


def _check(r, at, size, color, thick):
    """Thick tick mark facing -Y, about `size` wide, centred on `at`."""
    x, y, z = at
    _tube(r, "check", [(x - size * .45, y, z + size * .02), (x - size * .12, y, z - size * .3)], thick, color, "default")
    _tube(r, "check", [(x - size * .12, y, z - size * .3), (x + size * .48, y, z + size * .4)], thick, color, "default")


@_register
def plinth(r, *, radius=.07, height=.014, color=ORANGE, top=PAPER):
    """Round display base: a thick disk with a paler top surface."""
    _disk(r, "base", radius, height * .82, (0, 0, 0), color)
    _disk(r, "top", radius * .86, height * .5, (0, 0, height * .5), top)
    _anchors(r, top=(0, 0, height), center=(0, 0, height / 2))


@_register
def dome(r, *, radius=.062, height=.165, color="#FFFFFF"):
    """Clear bell jar, open underneath: a thin shell with a rounded top and a rolled rim. Stands over
    a figure on a plinth and lifts off."""
    wall = .0015

    def side(rad, top):
        return [(rad, 0)] + [(rad * math.cos(a), top - rad + rad * math.sin(a)) for a in [math.pi / 2 * i / 14 for i in range(15)]]

    _vessel(r, "shell", side(radius, height) + side(radius - wall, height - wall)[::-1], color=color, role="glass")
    _ring(r, "rim", (0, 0, .003), radius + .0006, .003, color, "glass")
    _anchors(r, top=(0, 0, height), grip=(0, 0, height))


@_register
def monitor(r, *, width=.11, color=BONE, trim=ORANGE, screen=SAGE):
    """Chunky retro monitor: a speech bubble on the screen, three button dots."""
    w, h, d, foot = width, width * .76, width * .42, width * .09
    _chunk(r, "foot", (w * .62, d * .9, foot), (0, 0, foot / 2), trim, bevel=.45)
    _chunk(r, "neck", (w * .26, d * .5, foot), (0, 0, foot * 1.4), trim)
    z, front = foot * 1.7 + h / 2, -d / 2
    _chunk(r, "body", (w, d, h), (0, 0, z), color, bevel=.26)
    _slab(r, "bezel", w * .84, h * .62, .006, (0, front - .001, z - h * .1), trim)
    _slab(r, "screen", w * .74, h * .5, .006, (0, front - .003, z - h * .1), screen)
    _bubble(r, w * .42, h * .28, (-w * .06, front - .0075, z - h * .08))
    for i, c in enumerate((trim, screen, "#FFFFFF")):
        _ball(r, "button", (w * .024,) * 3, (-w * .36 + i * w * .075, front - .0005, z + h * .31), c)
    _anchors(r, screen=(0, front - .006, z - h * .1), top=(0, 0, z + h / 2))


@_register
def phone(r, *, height=.085, color=BONE, screen=SAGE):
    """Chunky toy phone leaning back on a little foot, a speech bubble on its screen."""
    h, w, t = height, height * .56, height * .12
    f = _lean(r, "body", 12)
    _slab(f, "case", w, h, t, (0, 0, h / 2), color, corner=.24)
    _slab(f, "screen", w * .8, h * .76, .003, (0, -t / 2 - .0006, h * .54), screen, corner=.16)
    _bubble(f, w * .56, h * .2, (0, -t / 2 - .0035, h * .62))
    _ball(f, "home", (w * .07, .002, w * .07), (0, -t / 2, h * .08), ORANGE)
    _chunk(r, "dock", (w * .95, h * .46, h * .1), (0, h * .08, h * .05), ORANGE, bevel=.4)   # it stands in a little dock
    _anchors(r, screen=_leaned(12, 0, -t / 2 - .003, h * .54), top=_leaned(12, 0, 0, h))


@_register
def notebook(r, *, width=.10, color=BONE, cover=ORANGE, tab=SAGE):
    """Ring-bound notebook leaning back: two speech bubbles on the page."""
    w, h, t = width, width * 1.12, width * .1
    f = _lean(r, "book", 20)
    _slab(f, "cover", w, h, t * .4, (0, t * .5, h / 2), cover, corner=.1)
    _slab(f, "pages", w * .93, h * .94, t * .8, (w * .015, -t * .1, h / 2), color, corner=.08)
    for i in range(4):
        _ring(f, "ring", (-w / 2 + .001, t * .1, h * (.2 + .2 * i)), t * .78, .0032, cover, "default")
    _chunk(f, "tab", (w * .12, t * .5, h * .16), (w / 2 + w * .02, -t * .1, h * .74), tab, bevel=.35)
    y = -t * .5 - .002
    _bubble(f, w * .4, h * .17, (-w * .14, y, h * .7), tab, dot="#FFFFFF")
    _bubble(f, w * .4, h * .17, (w * .16, y, h * .38), cover, dot="#FFFFFF")
    for x, z in ((w * .2, h * .73), (w * .2, h * .67), (-w * .18, h * .41), (-w * .18, h * .35)):
        _slab(f, "line", w * .24, h * .028, .002, (x, y + .001, z), "#C9B9A2", corner=.5)
    _chunk(r, "rest", (w * .5, h * .3, h * .08), (0, h * .22, h * .04), cover, bevel=.4)
    _chunk(r, "ledge", (w * 1.02, t * 3.2, h * .06), (0, t * .2, h * .03), cover, bevel=.4)   # an easel ledge: nothing hovers
    _anchors(r, page=_leaned(20, 0, y, h / 2), top=_leaned(20, 0, 0, h))


@_register
def link(r, *, length=.11, color=ORANGE, bar=SAGE):
    """Two square bases joined by a thick arch, a button on each base."""
    b = length * .3
    x, rise = length / 2 - b / 2, length * .27
    for s in (-1, 1):
        _chunk(r, "base", (b, b, b * .62), (s * x, 0, b * .31), color, bevel=.35)
        _cyl(r, "disc", b * .3, .004, (s * x, -b / 2 - .001, b * .31), BONE, "default", axis="Y")
        _ball(r, "button", (b * .13,) * 3, (s * x, -b / 2 - .003, b * .31), color)
    _tube(r, "arch", [(-x * math.cos(a), 0, b * .5 + rise * math.sin(a)) for a in [math.pi * i / 16 for i in range(17)]], b * .2, bar, "default")
    _anchors(r, start=(-x, 0, b * .62), end=(x, 0, b * .62), top=(0, 0, b * .7 + rise))


@_register
def machine(r, *, width=.10, color=BONE, trim=ORANGE, belt=SAGE):
    """Chunky little machine: chimney, button dots, a gear over a conveyor belt
    in the front opening."""
    w, d, bh = width, width * .56, width * .58
    _chunk(r, "base", (w, d, w * .14), (0, 0, w * .07), trim, bevel=.4)
    z, front = w * .12 + bh / 2, -d * .45
    _chunk(r, "body", (w * .92, d * .9, bh), (0, 0, z), color, bevel=.25)
    _chunk(r, "lid", (w * .52, d * .7, w * .09), (-w * .1, 0, z + bh / 2 + w * .02), trim, bevel=.4)
    _cyl(r, "chimney", w * .065, w * .2, (w * .3, 0, z + bh / 2 + w * .07), trim, "default")
    _disk(r, "chimney_cap", w * .09, w * .045, (w * .3, 0, z + bh / 2 + w * .16), trim)
    ox = w * .1
    _slab(r, "opening", w * .5, bh * .6, .004, (ox, front - .001, z - bh * .06), INK, corner=.2)
    gz, gr = z + bh * .06, w * .08
    _cyl(r, "gear", gr * .78, .005, (ox, front - .004, gz), BRASS, "default", axis="Y")
    for k in range(8):
        a = math.tau * k / 8
        _chunk(r, "tooth", (gr * .34, .005, gr * .34), (ox + gr * .85 * math.cos(a), front - .004, gz + gr * .85 * math.sin(a)), BRASS)
    _ball(r, "hub", (gr * .25, .002, gr * .25), (ox, front - .0065, gz), INK)
    _chunk(r, "belt", (w * .44, w * .16, w * .06), (ox, front - w * .03, z - bh * .31), belt, bevel=.45)
    for i, c in enumerate((trim, belt, "#FFFFFF")):
        _ball(r, "button", (w * .026,) * 3, (-w * .32, front - .0005, z + bh * (.2 - .2 * i)), c)
    _anchors(r, top=(0, 0, z + bh / 2), slot=(ox, front, z - bh * .06))


@_register
def magnifier(r, *, length=.045, color=SAGE):
    """Chunky magnifying glass standing on its handle."""
    lens, hz = length * .27, length * .46
    _tube(r, "handle", [(0, 0, 0), (0, 0, hz)], length * .085, color, "default")
    _ring(r, "frame", (0, 0, hz + lens), lens, length * .075, color, "default", plane="XZ")
    _ball(r, "lens", (lens, length * .03, lens), (0, 0, hz + lens), "#DDF1EC", "glass")
    _anchors(r, grip=(0, 0, hz * .5), top=(0, 0, hz + 2 * lens))


@_register
def wrench(r, *, length=.045, color="#9FA7A3"):
    """Chunky open-ended spanner standing on end."""
    jaw, cz = length * .19, length * .78
    _slab(r, "shaft", length * .16, length * .66, length * .1, (0, 0, length * .37), color, "metal", corner=.45)
    _tube(r, "jaw", [(jaw * math.cos(a), 0, cz + jaw * math.sin(a)) for a in [math.radians(135 + 270 * i / 14) for i in range(15)]],
          length * .075, color, "metal")
    _ring(r, "eye", (0, 0, length * .07), length * .07, length * .045, color, "metal", plane="XZ")
    _anchors(r, grip=(0, 0, length * .2), top=(0, 0, cz + jaw))


@_register
def clipboard(r, *, height=.04, color=ORANGE, check=SAGE):
    """Chunky clipboard standing on its bottom edge: paper with a thick tick."""
    h, w = height, height * .74
    _slab(r, "board", w, h, h * .1, (0, 0, h / 2), color, corner=.14)
    _slab(r, "paper", w * .8, h * .74, h * .05, (0, -h * .06, h * .44), PAPER, "paper", corner=.08)
    _chunk(r, "clip", (w * .4, h * .12, h * .14), (0, -h * .04, h * .92), "#9FA7A3", "metal", bevel=.35)
    _check(r, (0, -h * .1, h * .44), w * .5, check, h * .045)
    _anchors(r, grip=(0, 0, 0), top=(0, 0, h))


@_register
def task_card(r, *, width=.05, color=PAPER, accent=ORANGE, done=False, check=SAGE):
    """Thick card standing on edge: a coloured header and two lines of 'writing'; done=True shows a
    big tick instead of the lines."""
    w, h, t = width, width * .76, width * .12
    _slab(r, "card", w, h, t, (0, 0, h / 2), color, corner=.16)
    _chunk(r, "foot", (w * .5, t * 2.6, h * .08), (0, 0, h * .04), accent, bevel=.4)   # a card holder: it stands, it does not float
    y = -t / 2 - .0005
    _slab(r, "header", w * .8, h * .18, .002, (0, y, h * .78), accent, corner=.45)
    if done:
        _check(r, (0, y - .002, h * .36), w * .44, check, w * .05)
    else:
        for i, k in enumerate((.7, .5)):
            _slab(r, "line", w * k, h * .09, .002, (-w * (.4 - k / 2), y, h * (.5 - .22 * i)), INK, corner=.5)
    _anchors(r, top=(0, 0, h), center=(0, 0, h / 2), grip=(0, 0, 0))


@_register
def star(r, *, radius=.018, thickness=.008, color="#F0B45A", stem=0.0, thread=0.0, stem_color=BRASS, role="default"):
    """Plump five-pointed star facing -Y. `stem` stands it on a thin rod of that height with a small
    round foot; `thread` hangs it from a thread of that length going straight up (out of frame), the
    way a prop is flown in for the camera."""
    z = stem + radius * .85
    if stem:
        _disk(r, "foot", radius * .55, radius * .22, (0, thickness * .2, 0), stem_color)
        _tube(r, "rod", [(0, thickness * .2, 0), (0, thickness * .2, z)], radius * .07, stem_color, "metal")
    _prism(r, "star", [(x, z + y) for x, y in _star_outline(radius)], thickness, (0, 0, 0), color, role)
    if thread:
        _tube(r, "thread", [(0, 0, z + radius * .9), (0, 0, z + radius + thread)], .0005, "#B9AFA0", "metal")
    _anchors(r, center=(0, 0, z), top=(0, 0, z + radius))


# ------------------------------------------------ office furniture ----
# Reusable furniture and dressing. Fronts face -Y; a wall-mounted
# piece has its back on the y=0 plane, so `at` is the point on the wall under its bottom centre.
TIMBER, IRON, STEEL, CORK, SHEET, STICKY = "#6B4326", "#2B2A28", "#C9CCD0", "#BE7A45", "#F3ECDD", "#EFC44F"


def _practical(r, at, *, power, name=None, color="#FFC98A", size=.006):
    """Warm point light that belongs to a prop. `name` is the exact object name (so an episode can
    switch it); by default it is "<prop>.practical"."""
    data = bpy.data.lights.new(name or r.name + ".practical", "POINT")
    data.energy, data.color, data.shadow_soft_size = power, util.hex_rgb(color)[:3], size
    obj = bpy.data.objects.new(data.name, data)
    util.link(obj)
    obj.parent, obj.location = r, at
    return obj


def _ink(r, points, at, size, color=DARK, thick=.00035):
    """Pen line on a sheet facing -Y: points are (x, z) in units of `size`, around `at`."""
    return _tube(r, "ink", [(at[0] + x * size, at[1], at[2] + z * size) for x, z in points], thick, color, "paper")


def _arc(cx, cz, rx, rz, a0, a1, n=10):
    return [(cx + rx * math.cos(math.radians(a0 + (a1 - a0) * i / n)), cz + rz * math.sin(math.radians(a0 + (a1 - a0) * i / n)))
            for i in range(n + 1)]


SKETCHES = {
    # pen drawings in a unit square (x -0.5..0.5, z -0.5..0.5): lists of polylines
    "mug": [[(-.26, .2), (-.24, -.3), (.14, -.3), (.16, .2), (-.26, .2)], _arc(.2, -.04, .13, .15, 80, -80),
            _arc(-.05, .2, .21, .05, 0, 360, 14), [(-.12, .3), (-.08, .38), (-.13, .46)], [(.02, .3), (.06, .38), (.01, .46)]],
    "headlamp": [_arc(0, -.05, .2, .2, 0, 360, 16), _arc(0, -.05, .1, .1, 0, 360, 12),
                 [(-.2, .0), (-.46, .08), (-.46, -.18), (-.2, -.1)], [(.2, .0), (.46, .08), (.46, -.18), (.2, -.1)],
                 [(-.1, .24), (-.16, .4)], [(0, .26), (0, .44)], [(.1, .24), (.16, .4)]],
    "mountains": [[(-.46, -.3), (-.18, .22), (-.04, -.02), (.14, .34), (.46, -.3)], [(-.46, -.3), (.46, -.3)],
                  [(-.25, .09), (-.18, .0), (-.1, .08)], [(.06, .2), (.14, .1), (.21, .2)],
                  [(-.34, -.3), (-.34, -.2)], [(-.42, -.2), (-.34, .02), (-.26, -.2), (-.42, -.2)],
                  [(.3, -.3), (.3, -.22)], [(.23, -.22), (.3, -.04), (.37, -.22), (.23, -.22)]],
    "circles": [_arc(-.26, 0, .14, .14, 0, 360, 12), _arc(.02, .05, .11, .11, 0, 360, 12), _arc(.28, -.04, .13, .13, 0, 360, 12)],
}


@_register
def desk(r, *, width=.22, depth=.10, height=.095, color="#96643A", drawers="right", pull="#C8A45A"):
    """Writing desk; the sitter is on the -Y side. A thick top, a pedestal of three drawers under one
    end (drawers: right | left | none), two legs under the other and a rail along the back. Anchor
    `knee` is the floor point under the front edge of the knee space (a seated character's root goes
    about 0.04 m in front of it); `front` is the same point on the desk top."""
    top, side = .011, {"right": 1, "left": -1, "none": 0}[drawers]
    under = height - top
    _box(r, "top", (width, depth, top), (0, 0, height - top / 2), color)
    ped = width * .32
    posts = [-1, 1]
    if side:
        x = side * (width / 2 - ped / 2 - .004)
        _box(r, "pedestal", (ped, depth - .012, under), (x, 0, under / 2), color)
        each = (under - .008) / 3
        for i in range(3):
            z = .005 + each * (i + .5)
            _box(r, "drawer", (ped - .008, .005, each - .004), (x, -depth / 2 + .0045, z), color)
            _ball(r, "pull", (.0045, .003, .003), (x, -depth / 2 + .001, z), pull, "metal")
        posts = [-side]
    for s in posts:
        for y in (-depth / 2 + .012, depth / 2 - .012):
            _box(r, "leg", (.012, .012, under), (s * (width / 2 - .012), y, under / 2), color)
    _box(r, "rail", (width - .024, .006, .032), (0, depth / 2 - .012, under - .016), color)
    knee = -side * ped / 2
    _anchors(r, top=(0, 0, height), knee=(knee, -depth / 2, 0), front=(knee, -depth / 2, height))


@_register
def office_chair(r, *, seat_height=.052, width=.068, color="#3F5E8C", frame=IRON):
    """Swivel chair on a five-star base with castors; padded seat and back in `color`. The sitter
    faces -Y; seat_height is the top of the cushion."""
    hub = .014
    for i in range(5):
        a = i * math.tau / 5 + .3
        _tube(r, "spoke", [(0, 0, hub), (.033 * math.cos(a), .033 * math.sin(a), .008)], .0034, frame, "metal")
        _ball(r, "castor", (.005, .005, .005), (.035 * math.cos(a), .035 * math.sin(a), .005), frame)
    _cyl(r, "column", .0045, seat_height - .012 - hub + .006, (0, 0, (seat_height - .012 + hub) / 2), frame, "metal")
    _chunk(r, "seat", (width, width * .94, .014), (0, 0, seat_height - .007), color, "fabric", bevel=.42)
    _tube(r, "back_post", [(0, width * .40, seat_height - .011), (0, width * .50, seat_height + .028)], .004, frame, "metal")
    _chunk(r, "back", (width * .92, .015, .064), (0, width * .5, seat_height + .054), color, "fabric", bevel=.42)
    _anchors(r, seat=(0, 0, seat_height), back=(0, width * .5, seat_height + .086))


@_register
def padded_chair(r, *, seat_height=.058, width=.066, color="#E0A93B", frame=WOOD):
    """Four-legged wooden chair with an upholstered seat and back pad in `color`; the sitter faces -Y."""
    _legs(r, width - .016, width - .020, seat_height - .012, frame, .0042)
    _box(r, "frame", (width, width * .94, .008), (0, 0, seat_height - .013), frame)
    _chunk(r, "seat", (width - .004, width * .9, .013), (0, 0, seat_height - .0065), color, "fabric", bevel=.42)
    for x in (-width / 2 + .006, width / 2 - .006):
        _box(r, "back_post", (.008, .008, .072), (x, width * .44, seat_height + .028), frame)
    _chunk(r, "back", (width * .96, .014, .052), (0, width * .43, seat_height + .046), color, "fabric", bevel=.42)
    _anchors(r, seat=(0, 0, seat_height), back=(0, width * .43, seat_height + .072))


@_register
def computer(r, *, width=.066, color="#3A3835", screen="#EFE6D6", keys="#DCD7CC", keyboard=True, gap=.045):
    """Desktop computer: a flat monitor on a foot (screen faces -Y), with a keyboard and mouse `gap`
    metres in front of it. Anchors: screen (centre of the glass), keyboard, top."""
    w, h, foot = width, width * .62, width * .30
    _disk(r, "foot", width * .22, .004, (0, 0, 0), color)
    _box(r, "neck", (.008, .006, foot), (0, .004, foot / 2), color, "default")
    z = foot * .82 + h / 2
    _chunk(r, "case", (w, .008, h), (0, 0, z), color, bevel=.3)
    _slab(r, "screen", w * .9, h * .84, .003, (0, -.0045, z), screen, "glass", corner=.06)
    if keyboard:
        _chunk(r, "keyboard", (w * .82, w * .28, .004), (0, -gap, .002), keys, bevel=.3)
        for row in range(3):
            _box(r, "keys", (w * .74, w * .055, .0012), (0, -gap + (row - 1) * w * .08, .0042), "#F4F1EA", "default")
        _ball(r, "mouse", (.0045, .0065, .003), (w * .58, -gap, .003), keys)
    _anchors(r, screen=(0, -.006, z), keyboard=(0, -gap, .004), top=(0, 0, z + h / 2))


@_register
def bookshelf(r, *, width=.16, height=.26, depth=.06, shelves=4, color="#7A4E2D", fill=.8):
    """Tall open bookcase standing on the floor, facing -Y: `shelves` boards between the bottom and
    the top, each loaded (share `fill` of its width) with upright books, a leaning book, a basket or
    a storage box, chosen by the seed. Anchors: top, center (front of the middle)."""
    rand = random.Random(int(r["seed"]) + 11)
    t = .007
    for x in (-width / 2 + t / 2, width / 2 - t / 2):
        _box(r, "side", (t, depth, height), (x, 0, height / 2), color)
    _box(r, "back", (width - t, .004, height - t), (0, depth / 2 - .002, height / 2), color)
    levels = [.012 + i * (height - .012 - t) / (shelves + 1) for i in range(shelves + 2)]
    for z in levels:
        _box(r, "board", (width - t, depth - .004, t), (0, -.001, z + t / 2), color)
    books = ["#7B3F34", "#3F5873", "#B08A45", "#4E6B52", "#8B5A3C", "#C9B79A", "#5A4A6A", "#9A4B2E"]
    for level, z in enumerate(levels[:-1]):
        room, floor, x = levels[level + 1] - z - t, z + t, -width / 2 + t + .003
        end = x + (width - 2 * t - .006) * fill
        while x < end - .008:
            kind = rand.random()
            if kind < .16 and end - x > .034:      # woven basket
                rad = min(.016, room * .42)
                _vessel(r, "basket", [(.001, 0), (rad * .8, 0), (rad, rad * 1.5), (rad * .9, rad * 1.5), (rad * .72, .003), (.001, .003)],
                        (x + rad, 0, floor), "#B98C55", "fabric")
                x += rad * 2 + .004
            elif kind < .3 and end - x > .03:      # storage box
                bw, bh = rand.uniform(.024, .03), min(room * .8, rand.uniform(.022, .032))
                _box(r, "box", (bw, depth * .62, bh), (x + bw / 2, -.002, floor + bh / 2), rand.choice(["#7C8590", "#5F6F7C", "#A79A86"]), "paper")
                x += bw + .004
            else:                                  # a run of upright books
                for _ in range(rand.randint(2, 5)):
                    bw, bh = rand.uniform(.0055, .010), room * rand.uniform(.62, .9)
                    if x + bw > end:
                        break
                    _box(r, "book", (bw, depth * rand.uniform(.5, .66), bh), (x + bw / 2, -.004, floor + bh / 2), rand.choice(books), "fabric")
                    x += bw + .0006
                x += rand.uniform(.002, .008)
    _anchors(r, top=(0, 0, height), center=(0, -depth / 2, height / 2))


@_register
def desk_lamp(r, *, height=.105, reach=.045, color=IRON, lit=True, light=None, power=.03):
    """Articulated desk lamp: round foot, two arms and a cone shade that hangs `reach` metres in
    front (-Y) of the foot. lit adds a warm point light under the shade (object name `light`, by
    default "<prop>.practical"); the bulb is plain glass, so the lamp is dark when its light is off."""
    _disk(r, "foot", .016, .005, (0, 0, 0), color, "metal")
    elbow, head = (0, .018, height * .62), (0, -reach, height)
    _tube(r, "arm", [(0, 0, .004), elbow], .0022, color, "metal")
    _tube(r, "arm", [elbow, (0, -reach * .72, height + .012), (0, -reach, height + .008)], .0022, color, "metal")
    _ball(r, "joint", (.004, .004, .004), elbow, color, "metal")
    _vessel(r, "shade", [(.019, -.014), (.007, .006), (.004, .008), (.003, .006), (.017, -.014)], head, color, "metal")
    _ball(r, "bulb", (.0055, .0055, .0065), (0, -reach, height - .006), "#FFF1D6", "glass")
    if lit:
        _practical(r, (0, -reach, height - .016), power=power, name=light)
    _anchors(r, bulb=(0, -reach, height - .006), foot=(0, 0, 0), top=(0, -reach * .72, height + .012))


@_register
def wall_lamp(r, *, reach=.04, drop=.03, color=IRON, lit=True, light=None, power=.05):
    """Wall sconce (back on the y=0 plane): a round plate, a swan-neck arm reaching `reach` metres
    out and a bell shade hanging `drop` below it, open downwards. lit adds a warm point light under
    the shade (object name `light`, by default "<prop>.practical")."""
    z = drop + .022
    _cyl(r, "plate", .011, .004, (0, -.002, z), color, "metal", axis="Y")
    _tube(r, "neck", [(0, -.003, z), (0, -reach * .55, z + .014), (0, -reach, z + .006), (0, -reach, z - .006)], .0024, color, "metal")
    _vessel(r, "shade", [(.024, -.020), (.012, -.004), (.004, .002), (.003, .0), (.011, -.006), (.022, -.020)], (0, -reach, z - .006), color, "metal")
    _ball(r, "bulb", (.006, .006, .007), (0, -reach, z - .016), "#FFF1D6", "glass")
    if lit:
        _practical(r, (0, -reach, z - .028), power=power, name=light)
    _anchors(r, bulb=(0, -reach, z - .016), plate=(0, 0, z))


@_register
def hanging_plant(r, *, drop=.045, trail=.075, color="#4C7A45", pot="#B98C55"):
    """Trailing plant in a basket pot hung on three cords from a ceiling hook `drop` metres above
    the rim; vines hang up to `trail` below the pot. The root is the lowest leaf: place it at
    ceiling height minus the prop's height (anchor `hook` is the top)."""
    rand = random.Random(int(r["seed"]) + 5)
    base = trail
    _vessel(r, "pot", [(.001, 0), (.014, 0), (.021, .026), (.019, .028), (.016, .026), (.011, .004), (.001, .004)], (0, 0, base), pot, "fabric")
    _cyl(r, "soil", .016, .002, (0, 0, base + .023), "#4C3E2B", "default")
    top = base + .028 + drop
    for i in range(3):
        a = i * math.tau / 3 + .5
        _tube(r, "cord", [(.019 * math.cos(a), .019 * math.sin(a), base + .027), (0, 0, top)], .0007, "#D8C7A0", "fabric")
    _ball(r, "hook", (.003, .003, .003), (0, 0, top), IRON, "metal")
    for i in range(9):
        a = i * 2.4 + rand.uniform(-.3, .3)
        length = trail * rand.uniform(.45, 1.0)
        out = rand.uniform(.022, .034)
        pts = [(0, 0, base + .024), (out * .7 * math.cos(a), out * .7 * math.sin(a), base + .036),
               (out * math.cos(a), out * math.sin(a), base + .012), (out * 1.05 * math.cos(a), out * 1.05 * math.sin(a), base + .024 - length)]
        _tube(r, "vine", pts, .0011, color, "default")
        for k in range(4):
            f = (k + 1) / 4
            z = base + .012 - (length - .012) * f
            leaf = (out * (1 + .05 * f) * math.cos(a + .25 * (-1) ** k), out * (1 + .05 * f) * math.sin(a + .25 * (-1) ** k), z)
            _ball(r, "leaf", (.0075, .0035, .0095), leaf, color)
    for i in range(6):
        a = i * 1.05
        _ball(r, "leaf", (.010, .006, .012), (.012 * math.cos(a), .012 * math.sin(a), base + .036), color)
    _anchors(r, hook=(0, 0, top), pot=(0, 0, base))


@_register
def corkboard(r, *, width=.36, height=.21, frame=.013, color=CORK, frame_color="#8A5631"):
    """Framed cork pinboard for a wall (back on the y=0 plane), facing -Y. width/height are the
    outside of the frame. Anchors: center (on the cork), top, and the corners of the cork
    (`min` bottom-left, `max` top-right) for laying notes out."""
    _box(r, "cork", (width - frame, .006, height - frame), (0, -.004, height / 2), color, "paper")
    for x in (-width / 2 + frame / 2, width / 2 - frame / 2):
        _box(r, "frame", (frame, .014, height), (x, -.007, height / 2), frame_color)
    for z in (frame / 2, height - frame / 2):
        _box(r, "frame", (width, .014, frame), (0, -.007, z), frame_color)
    _anchors(r, center=(0, -.0072, height / 2), top=(0, -.007, height),
             min=(-width / 2 + frame, -.0072, frame), max=(width / 2 - frame, -.0072, height - frame))


@_register
def paper_note(r, *, width=.045, height=.045, lines=(), sketch="", color=SHEET, ink=DARK, pin="", font=""):
    """Sheet of paper for a wall or pinboard (back on the y=0 plane), facing -Y. `lines` are rows of
    lettering, top to bottom, each "text" or [text, size] with size relative to the sheet (1 = a
    headline); `sketch` is a pen drawing: mug | headlamp | mountains | circles; `pin` is the colour
    of a push pin at the top centre ("" = none); `font` is a font file for the lettering. Anchors: center and pin (both on the surface), top."""
    _box(r, "sheet", (width, .0007, height), (0, -.0004, height / 2), color, "paper")
    y = -.0009
    rows = [(row, 1.0) if isinstance(row, str) else (row[0], float(row[1])) for row in lines]
    if rows:
        unit = height * .78 / max(1e-6, sum(s for _, s in rows) * 1.25)
        unit = min(unit, width * .13)
        z = height / 2 + sum(s for _, s in rows) * unit * 1.25 / 2
        for text, s in rows:
            z -= s * unit * .62
            _text(r, text, (0, y, z), width * .88, s * unit, color=ink, font=font)
            z -= s * unit * .63
    if sketch:
        if sketch not in SKETCHES:
            raise ValueError(f"unknown sketch {sketch!r}; choose {', '.join(SKETCHES)}")
        for line in SKETCHES[sketch]:
            _ink(r, line, (0, y, height / 2), min(width, height) * .8, ink)
    if pin:
        _ball(r, "pin", (.0022, .0014, .0022), (0, -.0016, height - .0045), pin, "metal")
    _anchors(r, center=(0, -.0008, height / 2), pin=(0, -.0008, height - .0045), top=(0, 0, height))


@_register
def sticky_note(r, *, size=.022, color=STICKY):
    """Blank square sticky note for a wall (back on the y=0 plane): stuck along its top edge, the
    bottom curls a little toward the viewer."""
    n = 6
    verts = []
    for i in range(n + 1):
        f = i / n
        for x in (-size / 2, size / 2):
            verts.append((x, -.0006 - .0035 * (1 - f) ** 2, size * f))
    mesh = bpy.data.meshes.new("sticky")
    mesh.from_pydata(verts, [], [(2 * i, 2 * i + 1, 2 * i + 3, 2 * i + 2) for i in range(n)])
    mesh.update()
    obj = bpy.data.objects.new("sticky", mesh)
    util.link(obj)
    solid = obj.modifiers.new("thickness", "SOLIDIFY")
    solid.thickness = .0004
    util.apply_modifiers(obj)
    _part(r, obj, "paper", color)
    _anchors(r, center=(0, -.001, size / 2), top=(0, 0, size))


@_register
def push_pin(r, *, color=STEEL, size=.0045):
    """Round-headed push pin, head toward -Y and point toward +Y (into a wall). Anchors: head, tip."""
    _ball(r, "head", (size / 2, size * .34, size / 2), (0, -size * .5, size / 2), color, "metal")
    _cyl(r, "shaft", size * .09, size * 1.1, (0, size * .05, size / 2), "#9EA3A8", "metal", axis="Y")
    _anchors(r, head=(0, -size * .8, size / 2), tip=(0, size * .6, size / 2), grip=(0, -size * .5, size / 2))


@_register
def vintage_camera(r, *, width=.036, color="#3B2B22", metal=STEEL):
    """Old rangefinder camera, lens toward -Y: leather body, bright top plate with a viewfinder
    window, a wind knob and a shutter button, and a short lens barrel with a glass eye."""
    w, h, d = width, width * .56, width * .32
    _chunk(r, "body", (w, d, h * .72), (0, 0, h * .36), color, bevel=.25)
    _chunk(r, "top_plate", (w, d, h * .28), (0, 0, h * .86), metal, "metal", bevel=.3)
    _cyl(r, "barrel", h * .34, d * .7, (0, -d * .78, h * .40), metal, "metal", axis="Y")
    _cyl(r, "lens_ring", h * .27, d * .2, (0, -d * 1.16, h * .40), IRON, "metal", axis="Y")
    _ball(r, "lens", (h * .2, .0015, h * .2), (0, -d * 1.26, h * .40), "#39485A", "glass")
    _box(r, "finder", (w * .2, .002, h * .13), (w * .24, -d / 2 - .0005, h * .86), IRON, "glass")
    _cyl(r, "wind_knob", w * .09, h * .1, (-w * .32, 0, h * 1.04), metal, "metal")
    _cyl(r, "shutter", w * .04, h * .08, (w * .30, -d * .1, h * 1.03), "#B5543A", "metal")
    for x in (-w / 2, w / 2):
        _ring(r, "lug", (x, 0, h * .8), .0022, .0006, metal, "metal", plane="YZ")
    _anchors(r, lens=(0, -d * 1.28, h * .40), top=(0, 0, h), grip=(0, 0, h * .5))


@_register
def headlamp(r, *, width=.03, color="#E3B02F", face="#8D9299", strap="#3A3B3F", lit=False, light=None, power=.01):
    """Headlamp lying on a table, lamp toward -Y: a rounded lamp body in `color` with a grey face
    and a glass lens, on a loop of elastic strap with a buckle. lit adds a small warm light in
    front of the lens. Anchors: lens, top, grip."""
    w, h = width, width * .62
    loop = [(w * .95 * math.cos(a), w * .2 + w * .62 * math.sin(a), h * .42 + h * .12 * math.sin(2 * a)) for a in
            [math.tau * i / 28 for i in range(29)]]
    _tube(r, "strap", loop, [h * .13] * len(loop), strap, "fabric")
    _chunk(r, "buckle", (w * .16, w * .08, h * .5), (w * .9, w * .3, h * .42), color, bevel=.3)
    _chunk(r, "body", (w * .62, w * .36, h * .9), (0, -w * .40, h * .45), color, bevel=.42)
    _cyl(r, "face", h * .36, w * .1, (0, -w * .60, h * .46), face, "metal", axis="Y")
    _ball(r, "lens", (h * .25, .0018, h * .25), (0, -w * .655, h * .46), "#FFF0CF", "glass")
    _chunk(r, "switch", (w * .16, w * .12, h * .1), (0, -w * .40, h * .93), face, bevel=.35)
    if lit:
        _practical(r, (0, -w * .8, h * .46), power=power, name=light, size=.003)
    _anchors(r, lens=(0, -w * .66, h * .46), top=(0, -w * .4, h), grip=(0, 0, h * .42))


@_register
def berry_vase(r, *, height=.075, color="#EFE9DC", leaf="#4F7A45", berry="#B9382F"):
    """Speckled stoneware vase holding sprigs of green leaves and clusters of red berries;
    `height` is the top of the sprigs."""
    rand = random.Random(int(r["seed"]) + 3)
    vz = height * .42
    _vessel(r, "vase", [(.001, 0), (.009, 0), (.014, vz * .45), (.012, vz * .85), (.0085, vz), (.0065, vz),
                        (.010, vz * .8), (.011, vz * .45), (.007, .004), (.001, .004)], color=color)
    for i in range(12):
        a, z = rand.uniform(0, math.tau), rand.uniform(.1, .8) * vz
        rad = .0135 if z < vz * .6 else .012
        _ball(r, "speck", (.0009, .0009, .0009), (rad * math.cos(a), rad * math.sin(a), z), "#8B7C68")
    for i in range(7):
        a = i * 2.4 + rand.uniform(-.2, .2)
        out, top = rand.uniform(.008, .024), height * rand.uniform(.72, 1.0)
        tip = (out * math.cos(a), out * math.sin(a), top)
        _tube(r, "stem", [(0, 0, vz * .7), (tip[0] * .5, tip[1] * .5, vz + (top - vz) * .6), tip], .0009, "#6B5136", "default")
        if i % 2:
            for k in range(5):
                b = k * 2.4 + i
                _ball(r, "berry", (.0032, .0032, .0032), (tip[0] + .0045 * math.cos(b), tip[1] + .0045 * math.sin(b), tip[2] - .003 * (k % 3)), berry, "ceramic")
        else:
            for k in range(3):
                f = .5 + .25 * k
                at = (tip[0] * f + .004 * (-1) ** k, tip[1] * f, vz + (top - vz) * f)
                _ball(r, "leaf", (.008, .003, .011), at, leaf)
    _anchors(r, rim=(0, 0, vz), top=(0, 0, height))


@_register
def beam(r, *, length=.6, thick=.03, color=TIMBER):
    """Hand-hewn ceiling beam lying along Y (centred), `thick` square, with adze-cut corners.
    Place the root at the height of its underside. Anchors: center, top."""
    o = util.rounded_box("beam", (thick, length, thick), bevel=.16, segments=2)
    o.data.transform(Matrix.Translation((0, 0, thick / 2)))
    util.lumpify(o, thick * .03, .05, int(r["seed"]) + 1)
    _part(r, o, "wood", color)
    _anchors(r, center=(0, 0, thick / 2), top=(0, 0, thick))


@_register
def snowy_pine(r, *, height=.40, color="#3F6247", snow="#EEF2F7", trunk="#5B4030"):
    """Conifer under snow: a trunk and stacked skirts of boughs, each carrying a lopsided cap of
    snow and a few clumps on its rim."""
    rand = random.Random(int(r["seed"]) + 7)
    _cyl(r, "trunk", height * .035, height * .3, (0, 0, height * .15), trunk, "wood", top=height * .025)
    tiers = 5
    for i in range(tiers):
        f = i / (tiers - 1)
        rad, tall = height * (.25 - .17 * f), height * (.26 - .05 * f)
        z = height * (.16 + .62 * f) + tall / 2
        _cyl(r, "boughs", rad, tall, (0, 0, z), color, "default", top=rad * .12)
        dx, dy = rand.uniform(-.1, .1) * rad, rand.uniform(-.1, .1) * rad
        _cyl(r, "snow", rad * .8, tall * .62, (dx, dy, z + tall * .25), snow, "default", top=rad * .1)
        for k in range(5):
            a = k * math.tau / 5 + rand.uniform(-.4, .4) + i
            _ball(r, "snow_clump", (rad * .26, rad * .26, rad * .14), (rad * .78 * math.cos(a), rad * .78 * math.sin(a), z - tall * .30), snow)
    _ball(r, "snow_tip", (height * .028, height * .028, height * .04), (0, 0, height - height * .03), snow)
    _anchors(r, top=(0, 0, height), trunk=(0, 0, height * .1))


@_register
def round_rug(r, *, radius=.18, color="#D2B48A", color2="#BFA074"):
    """Round braided rug: a coil of thick woven rope, alternate turns in two tones, lying flat."""
    _disk(r, "base", radius * .98, .0022, (0, 0, 0), color2, "fabric")
    rope = .0052
    turns = max(2, int(radius / (rope * 2)))
    for i in range(turns):
        rad = radius - rope - i * rope * 2
        if rad < rope:
            break
        _ring(r, "braid", (0, 0, .0034), rad, rope * .98, color if i % 2 else color2, "fabric")
    _anchors(r, center=(0, 0, .006))


@_register
def round_table(r, *, radius=.08, height=.10, color="#A56B3B", legs=4):
    """Rustic round table: a thick slab top on `legs` log legs set in from the edge."""
    top = .016
    _disk(r, "top", radius, top, (0, 0, height - top), color, "wood")
    for i in range(legs):
        a = math.tau * (i + .5) / legs
        x, y = radius * .62 * math.cos(a), radius * .62 * math.sin(a)
        _cyl(r, "leg", .0085, height - top, (x, y, (height - top) / 2), color, "wood", top=.0075)
    _anchors(r, top=(0, 0, height))


@_register
def folder(r, *, width=.036, height=.048, color="#3D5F9A", pages=SHEET):
    """Stiff document folder standing on its lower edge, cover toward -Y, with a sliver of paper
    showing at the top and a label. `grip` is where a hand takes it (the middle of the spine side)."""
    t = .0075
    _chunk(r, "cover", (width, t, height), (0, 0, height / 2), color, "paper", bevel=.2)
    _box(r, "pages", (width * .9, t * .5, height * .05), (0, 0, height + .0005), pages, "paper")
    _box(r, "label", (width * .5, .0008, height * .16), (0, -t / 2 - .0002, height * .66), pages, "paper")
    _anchors(r, grip=(0, 0, height * .5), top=(0, 0, height), front=(0, -t / 2, height / 2))


@_register
def basket_plant(r, *, height=.22, color="#4B7C45", basket="#B48A52"):
    """Big leafy floor plant in a woven basket; `height` is the top of the tallest leaf."""
    rand = random.Random(int(r["seed"]) + 9)
    bh = height * .30
    rad = height * .17
    _vessel(r, "basket", [(.001, 0), (rad * .82, 0), (rad, bh), (rad * .92, bh), (rad * .76, .004), (.001, .004)], color=basket, role="fabric")
    for i in range(4):
        _ring(r, "weave", (0, 0, bh * (.14 + .25 * i)), rad * (.84 + .05 * i), .0022, basket, "fabric")
    _cyl(r, "soil", rad * .9, .003, (0, 0, bh * .86), "#4C3E2B", "default")
    for i in range(11):
        a = i * 2.4 + rand.uniform(-.25, .25)
        top = height * rand.uniform(.62, .97)
        out = rad * rand.uniform(.6, 1.7)
        tip = Vector((out * math.cos(a), out * math.sin(a), top))
        _tube(r, "stalk", [(0, 0, bh * .8), (tip.x * .45, tip.y * .45, bh + (top - bh) * .62), tuple(tip)], .0018, "#3F6A3C", "default")
        size = height * rand.uniform(.11, .17)
        leaf = _ball(r, "leaf", (size * .55, size * .14, size), tuple(tip), color)
        leaf.data.transform(Matrix.Translation(tip) @ Matrix.Rotation(a + math.pi / 2, 4, "Z") @ Matrix.Rotation(rand.uniform(.5, 1.0), 4, "X")
                            @ Matrix.Translation(-tip))
    _anchors(r, top=(0, 0, height), pot=(0, 0, bh))


@_register
def pencil_cup(r, *, height=.02, color="#8A5A3A"):
    """Desk tidy: a small cup with a fistful of pencils and pens."""
    _vessel(r, "cup", [(.001, 0), (.007, 0), (.008, height), (.007, height), (.0062, .003), (.001, .003)], color=color)
    for i, c in enumerate(("#D9A441", "#B5543A", "#4E6B8A", "#D9A441", "#3F6A3C")):
        a = i * 1.3
        foot, tip = (.003 * math.cos(a), .003 * math.sin(a), .004), (.0075 * math.cos(a), .0075 * math.sin(a), height * 1.75 + .002 * (i % 2))
        _tube(r, "pencil", [foot, tip], .0011, c, "default")
    _anchors(r, rim=(0, 0, height), top=(0, 0, height * 1.75))


@_register
def strand(r, *, to=(.1, 0, 0), radius=.0011, color="#F6E7B8", role="glow"):
    """A thin line from the prop's position to `to` (an offset in metres): the line of a constellation,
    a string, a wire. Glows by default."""
    _tube(r, "strand", [(0, 0, 0), tuple(to)], radius, color, role)
    _anchors(r, start=(0, 0, 0), end=tuple(to))


def build_prop(kind: str, name: str | None = None, *, at=(0,0,0), heading=0.0,
               scale=1.0, seed=0, **params) -> bpy.types.Object:
    """Build and place a prop; heading is radians about +Z, scale is uniform.

    The returned Empty owns all pieces, lights and local-space anchor metadata.
    Every mesh is finished with a material and metre-space rest coordinates.
    Builders must create their geometry sitting approximately on z=0; this entry
    point removes submillimetre construction/lump drift before placement.
    """
    if kind not in PROPS:
        raise ValueError(f"unknown prop {kind!r}; choose {', '.join(PROPS)}")
    if scale <= 0:
        raise ValueError("scale must be positive")
    root=bpy.data.objects.new(name or kind,None)
    util.link(root)
    root.empty_display_size=.015
    root["kind"]=kind
    root["seed"]=int(seed)
    PROPS[kind](root,**params)
    rand=random.Random(int(seed))
    meshes=[o for o in descendants(root) if o.type=="MESH"]
    for o in meshes:
        # Nested completed props already carry rest data; don't finish them twice.
        if o.data.attributes.get("rest") is None:
            smallest=min(max(v,1e-5) for v in o.dimensions)
            util.lumpify(o,min(.00022,smallest*.025)*style.active().lumpiness,.009,rand.randrange(2**30))
            store_rest(o)
    lo,_=bounds(root)
    delta=-lo.z
    for o in root.children:
        o.location.z += delta
    for key,point in root["anchors"].items():
        if key not in root.get("anchor_parts", {}):
            point[2]+=delta
    root.location=at
    root.rotation_euler.z=heading
    root.scale=(scale,)*3
    return root
