"""Reusable three-sided miniature stages. Action marks always face the open -Y side."""
from __future__ import annotations

import math
import random
import time
from collections.abc import Callable

import bpy

from . import stage, style, util
from .materials import patterns
from .materials.nodes import store_rest
from .props import build_prop, anchor, _box, _ball, _tube, _cyl

SETS: dict[str, Callable] = {}


def _root(name):
    root=bpy.data.objects.new(name,None)
    util.link(root)
    return root


def _surface(obj, role, color, material=None):
    util.set_material(obj,material or style.active().material(role,color))
    store_rest(obj)
    return obj


def _box_surface(name,size,at,role,color,material=None):
    return _surface(util.rounded_box(name,size,at,bevel=.04,segments=2),role,color,material)


def _pattern(role, color, recipe, **params):
    """Keep authored style overrides: only default-role recipes get set patterns."""
    st=style.active()
    selected=st.spec["materials"][role]["recipe"]
    if selected != style.DEFAULT_STYLE["materials"][role]["recipe"]:
        return st.material(role,color)
    return recipe("set_"+recipe.__name__,color,**params)


def _window(parent, x, y, sill, width, height):
    z=sill+height/2
    _box(parent,"daylight",(width,.004,height),(x,y+.006,z),"#C6DEDF","glow")
    for dx in (-width/2,width/2,0):
        _box(parent,"window_frame",(.008,.019,height+.012),(x+dx,y-.003,z),"#E6D7AF")
    for dz in (-height/2,height/2,0):
        _box(parent,"window_frame",(width+.014,.019,.008),(x,y-.003,z+dz),"#E6D7AF")
    _box(parent,"sill",(width+.038,.045,.009),(x,y-.015,sill-.006),"#E6D7AF")
    _tube(parent,"curtain_rail",[(x-width*.72,y-.027,sill+height+.022),
                                 (x+width*.72,y-.027,sill+height+.022)],.003,"#88643F")
    for side in (-1,1):
        for i in range(5):
            cx=x+side*(width*.48+i*.006)
            _tube(parent,"curtain",[(cx,y-.025,sill+height+.012),
                                    (cx+side*.006,y-.032,sill+height*.45),
                                    (cx+side*.002,y-.025,sill-.015)],
                  [.005,.004,.006],"#C88C69","fabric")
    stage.area_light("window_daylight",(x,y-.025,z),(x,-.10,.11),power=.45,size=width,color="#D3E7FF")


def room(*, width=1.10, depth=.85, height=.50, wall="#B6C1A1", floor="#97724C",
         wallpaper=None, window=None, door=None, skirting=True, name="room") -> dict:
    """Open-front three-wall shell with real back-wall openings.

    width/depth/height are metres. wallpaper is None or a dict with color2,
    width and axis for stripes. window is None or {x,width,height,sill}; door
    is None or {x,width,height,color}. Openings are on the back (+Y) wall.
    Returns shell object, floor bounds, plus window/door attachment anchors.
    The door is a closed painted panel (not an animated/hinged prop).
    """
    if min(width,depth,height)<=0:
        raise ValueError("room dimensions must be positive")
    shell=_root(name)
    floor_obj=_box_surface(name+"_floor",(width+.04,depth+.04,.018),(0,0,-.009),"floor",floor)
    floor_obj.parent=shell
    mat=_pattern("wall",wall,patterns.stripes,**wallpaper) if wallpaper else style.active().material("wall",wall)
    holes=[]
    anchors={}
    if window:
        x=window.get("x",-.10)
        w=window.get("width",.20)
        h=window.get("height",.18)
        z=window.get("sill",.22)
        holes.append((x-w/2,x+w/2,z,z+h))
        _window(shell,x,depth/2,z,w,h)
        anchors["window"]=(x,depth/2-.025,z+h/2)
    if door:
        x=door.get("x",-.38)
        w=door.get("width",.14)
        h=door.get("height",.31)
        holes.append((x-w/2,x+w/2,0,h))
        _box(shell,"door",(w-.004,.009,h),(x,depth/2,h/2),door.get("color","#879C86"))
        for dx in (-w/2,w/2):
            _box(shell,"door_casing",(.009,.018,h+.010),(x+dx,depth/2-.006,(h+.010)/2),"#E6D7AF")
        _box(shell,"door_lintel",(w+.018,.018,.010),(x,depth/2-.006,h+.005),"#E6D7AF")
        for z in (.085,.225):
            _box(shell,"door_panel",(w*.71,.004,.075),(x,depth/2-.007,z),"#738E79")
        _ball(shell,"door_knob",(.004,.005,.004),(x+w*.30,depth/2-.013,.15),"#BD9A54","metal")
        anchors["door"]=(x,depth/2-.055,0)
    # Split on all opening edges: no solid wall behind window/door.
    xs=sorted(set([-width/2,width/2]+[q for h in holes for q in h[:2]]))
    zs=sorted(set([0,height]+[q for h in holes for q in h[2:]]))
    for x0,x1 in zip(xs,xs[1:]):
        for z0,z1 in zip(zs,zs[1:]):
            mid=((x0+x1)/2,(z0+z1)/2)
            if any(a<mid[0]<b and c<mid[1]<d for a,b,c,d in holes):
                continue
            obj=_box_surface("back_wall",(x1-x0,.015,z1-z0),(mid[0],depth/2+.0075,mid[1]),"wall",wall,mat)
            obj.parent=shell
    for x in (-width/2-.0075,width/2+.0075):
        obj=_box_surface("side_wall",(.015,depth,height),(x,0,height/2),"wall",wall,mat)
        obj.parent=shell
    if skirting:
        for x in (-width/2+.003,width/2-.003):
            _box(shell,"skirting",(.009,depth,.019),(x,0,.0095),"#D9C7A2")
        # Back-wall skirting avoids door opening.
        for x0,x1 in zip(xs,xs[1:]):
            if any(a<(x0+x1)/2<b and c==0 for a,b,c,d in holes):
                continue
            _box(shell,"skirting",(x1-x0,.009,.019),((x0+x1)/2,depth/2-.003,.0095),"#D9C7A2")
    for obj in shell.children:
        if obj.type=="MESH" and obj.data.attributes.get("rest") is None:
            store_rest(obj)
    return {"shell":shell,"anchors":anchors,"bounds":((-width/2,-depth/2),(width/2,depth/2))}


def _cameras(wide=(-.09,-1.34,.57), target=(0,.06,.17)):
    return {
        "wide":{"from":wide,"to":target,"lens":39},
        "two_shot":{"from":(0,-.83,.29),"to":(0,-.09,.15),"lens":46},
        "close_a":{"from":(-.17,-.56,.26),"to":(-.11,-.12,.19),"lens":65},
        "close_b":{"from":(.17,-.56,.26),"to":(.11,-.12,.19),"lens":65},
    }


def kitchen(*, seed=0, clutter=.6, wall="#A5B395", floor="#A88459") -> dict:
    """Cosy English cottage kitchen; clear foreground dialogue strip."""
    shell=room(wall=wall,floor=floor,wallpaper={"color2":"#D8D4B0","width":.016,"axis":"X"},
               window={"x":-.095,"width":.21,"height":.17,"sill":.23},
               door={"x":-.39,"width":.14,"height":.31},name="kitchen")
    p={}
    def add(key,kind,at,**params):
        p[key]=build_prop(kind,key,at=at,seed=seed+len(p),**params)
        return p[key]
    rug_height=.0025
    table=add("table","table",(.275,.115,rug_height))
    a=add("chair_a","chair",(.275,-.005,rug_height),heading=math.pi)
    b=add("chair_b","chair",(.275,.245,rug_height))
    add("rug","rug",(.275,.12,0),width=.245,depth=.30,color="#7A5548")
    add("cupboard","cupboard",(.445,.33,0),width=.13,height=.22)
    s=add("shelf","shelf",(.230,.389,.255),width=.29,depth=.052)
    sz=anchor(s,"top").z
    add("shelf_bowl","bowl",(.170,.382,sz),radius=.021)
    add("shelf_mug","mug",(.245,.380,sz),color="#C3864B")
    add("shelf_plates","plate",(.300,.38,sz),radius=.020)
    top=anchor(table,"top").z
    add("teapot","teapot",(.30,.14,top))
    add("mug","mug",(.235,.10,top))
    add("biscuits_plate","plate",(.30,.075,top),radius=.022)
    add("biscuit","biscuit",(.30,.075,top+.004))
    add("toaster","toaster",(.445,.325,.22))
    add("clock","clock",(.225,.411,.385),radius=.031)
    add("lamp","lamp",(-.445,-.095,0),height=.26)
    add("picture","picture",(.465,.409,.290),width=.075,height=.063)
    add("plant","plant",(-.095,.408,.2285),height=.062)
    if clutter > 0:
        dressing = [
            ("towel","tea_towel",tuple(anchor(b,"seat")),{}),
            ("jam_jar","mug",(.49,.35,.22),{"color":"#9B5D49","tea":False}),
            ("second_picture","picture",(-.265,.411,.29),{"width":.065,"height":.052}),
            ("sugar_bowl","bowl",(.355,.37,sz),{"radius":.017}),
            ("extra_cup","mug",(.11,.382,sz),{"color":"#B8784F"}),
            ("shelf_crumbs","crumbs",(.34,.38,sz),{"count":8,"spread":.009}),
            ("hanging_spoon","spoon",(.37,.408,.22),{}),
            ("second_spoon","spoon",(.395,.408,.22),{}),
            ("sugar","sugar_cube",(.355,.37,sz+.006),{}),
        ]
        for key,kind,at,params in dressing[:max(1, math.ceil(len(dressing)*clutter))]:
            obj = add(key,kind,at,**params)
            if "spoon" in key:
                obj.rotation_euler.x = math.pi/2
                # The handle is now upright against the back wall.
    anchors={"center":(0,-.12,0),"mark_a":(-.11,-.12,0),"mark_b":(.11,-.12,0),
             "table_top":tuple(anchor(table,"top")),"seat_a":tuple(anchor(a,"seat")),
             "seat_b":tuple(anchor(b,"seat")),**shell["anchors"]}
    return {"anchors":anchors,"cameras":_cameras(),"light_rig":"cosy","props":p,
            "bounds":shell["bounds"],"shell":shell["shell"]}


def workshop(*, seed=0, clutter=.6, wall="#A56D51", floor="#786548") -> dict:
    """Inventor's shed with brickwork, workbench, lever machine and loose parts."""
    shell=room(wall=wall,floor=floor,window={"x":-.29,"width":.20,"height":.15,"sill":.28},name="workshop")
    brick=_pattern("wall",wall,patterns.brick,mortar="#CFBC98")
    for obj in shell["shell"].children:
        if obj.name.startswith("back_wall"):
            util.set_material(obj,brick)
        elif obj.name.startswith("side_wall"):
            # Broad upright shed planks: strips are a material, not extra geometry.
            util.set_material(obj,_pattern("wall","#94754C",patterns.stripes,color2="#80613D",width=.045,axis="Y"))
    p={}
    def add(key,kind,at,**params):
        p[key]=build_prop(kind,key,at=at,seed=seed+len(p),**params)
        return p[key]
    bench=add("bench","table",(.13,.30,0),width=.44,depth=.15,height=.115,color="#795C38")
    machine=add("lever_machine","lever",(.16,.28,.115),angle=-22)
    add("radio","radio",(.280,.31,.115))
    add("bench_gear","gear",(.015,.315,.115),radius=.024)
    add("bench_pipe","pipe",(.070,.31,.115))
    shelf=add("parts_shelf","shelf",(.25,.39,.275),width=.32,depth=.053)
    z=anchor(shelf,"top").z
    add("shelf_gear","gear",(.15,.38,z),radius=.029)
    add("shelf_pipe","pipe",(.255,.38,z))
    add("shelf_books","book_stack",(.36,.38,z),count=3)
    add("crate_left","crate",(-.40,.23,0),width=.10,depth=.09,height=.085)
    add("crate_right","crate",(.445,.19,0))
    add("spare_gear","gear",(-.39,.23,.086),radius=.029)
    add("stool","stool",(.35,.035,0),height=.065)
    add("picture","picture",(.455,.408,.34),width=.075,height=.08)
    if clutter > 0:
        dressing = [
            ("plans","blueprint",(-.06,.412,.23),{"text":"TEA-O-MATIC"}),
            ("oil","oil_can",(-.31,.24,0),{}),
            ("spare_pipe","pipe",(.445,.1,0),{}),
            ("small_gear","gear",(.20,.38,z),{"radius":.018}),
            ("rolled_plans","blueprint",(-.43,.412,.15),{"width":.10,"text":"PLAN B"}),
            ("tools","spoon",(-.22,.412,.18),{}),
            ("nuts","gear",(.31,.38,z),{"radius":.008,"teeth":6}),
            ("bolts","sugar_cube",(.34,.38,z),{"size":.006,"color":"#8D9994"}),
        ]
        for key,kind,at,params in dressing[:max(1, math.ceil(len(dressing)*clutter))]:
            obj = add(key,kind,at,**params)
            if key == "tools":
                obj.rotation_euler.x = math.pi/2
        add("floor_swarf","crumbs",(.23,.16,0),spread=.035,count=max(3,round(24*clutter)),color="#8C8E7A")
        add("loose_cog","gear",(-.24,.16,0),radius=.010,teeth=8)
    # A hanging inverted shade with real bulb, not a floor lamp in mid-air.
    hanging=_root("hanging_lamp")
    _tube(hanging,"cable",[(0,.24,.49),(0,.24,.395)],.0015,"#3B3731","default")
    _cyl(hanging,"shade",.045,.034,(0,.24,.381),"#476F68","metal",top=.012)
    _ball(hanging,"bulb",(.009,.009,.011),(0,.24,.359),"#FFDEAE","glow")
    for obj in hanging.children:
        store_rest(obj)
    stage.area_light("bench_lamp",(0,.24,.345),(0,.22,.11),power=.18,size=.065,color="#FFD39A")
    anchors={"center":(0,-.12,0),"mark_a":(-.11,-.12,0),"mark_b":(.11,-.12,0),
             "bench_top":tuple(anchor(bench,"top")),"lever":tuple(anchor(machine,"handle"))}
    return {"anchors":anchors,"cameras":_cameras(),"light_rig":"cosy","props":p,
            "bounds":shell["bounds"],"shell":shell["shell"]}


def _backdrop(width, depth, height):
    """U-shaped painted card with curved rear corners; deliberately open front."""
    radius=.16
    x=width/2
    y=depth/2
    path=[(-x,-depth/2),(-x,y-radius)]
    for i in range(1,13):
        a=math.pi-(math.pi/2)*(i/12)
        path.append((-x+radius+radius*math.cos(a),y-radius+radius*math.sin(a)))
    path.append((x-radius,y))
    for i in range(1,13):
        a=math.pi/2-(math.pi/2)*(i/12)
        path.append((x-radius+radius*math.cos(a),y-radius+radius*math.sin(a)))
    path.append((x,-depth/2))
    verts=[(px,py,z) for px,py in path for z in (0,height)]
    faces=[(i*2,i*2+1,(i+1)*2+1,(i+1)*2) for i in range(len(path)-1)]
    mesh=bpy.data.meshes.new("painted_cyclorama")
    mesh.from_pydata(verts,[],faces)
    mesh.update()
    for face in mesh.polygons:
        face.use_smooth=True
    obj=bpy.data.objects.new(mesh.name,mesh)
    util.link(obj)
    return _surface(obj,"wall","#93C4D5",_pattern("wall","#7AB8D0",patterns.sky,bottom="#E2E6C1",height=height))


def garden(*, seed=0, clutter=.6, grass="#668E49", sky="#7AB8D0") -> dict:
    """Three-sided painted outdoor stage with craft lawn and clear central path."""
    width,depth=1.22,1.0
    shell=_root("garden")
    floor=_box_surface("lawn",(width+.04,depth+.04,.018),(0,0,-.009),"floor",grass,
                       _pattern("floor",grass,patterns.grass))
    floor.parent=shell
    backdrop=_backdrop(width,depth,.63)
    # Public sky param controls the top color, leaving user style overrides intact.
    util.set_material(backdrop,_pattern("wall",sky,patterns.sky,bottom="#E2E6C1",height=.63))
    backdrop.parent=shell
    p={}
    def add(key,kind,at,**params):
        p[key]=build_prop(kind,key,at=at,seed=seed+len(p),**params)
        return p[key]
    add("fence","fence",(0,.40,0),length=1.07,height=.13)
    add("tree","tree",(-.405,.235,0),height=.43)
    add("bush_a","bush",(-.42,-.015,0),width=.19,height=.11)
    add("bush_b","bush",(.43,.30,0),width=.18,height=.10)
    sign=add("sign","sign",(.40,.04,0),height=.22,text="MIND THE PEAS" if clutter>0 else "")
    add("cloud_a","cloud",(-.22,.445,0),width=.18,height=.52)
    add("cloud_b","cloud",(.24,.445,0),width=.21,height=.47)
    rand=random.Random(seed)
    for i in range(12):
        side=-1 if i%2 else 1
        x=side*rand.uniform(.27,.51)
        y=rand.uniform(-.31,.23)
        add("flower_"+str(i),"flower",(x,y,0),height=rand.uniform(.048,.080),
            color=["#D49C3D","#BA655B","#E2D4B7"][i%3])
    add("rock","rock",(-.31,-.28,0),width=.055)
    add("mushroom","mushroom",(-.32,.19,0),height=.05)
    for i in range(math.ceil(20*clutter)):
        side = -1 if i%2 else 1
        x, y = side*rand.uniform(.29,.52), rand.uniform(-.34,.29)
        kind = ("flower","rock","mushroom")[i%3]
        params = ({"height":.045,"color":"#D2B758"} if kind=="flower"
                  else {"width":.019} if kind=="rock" else {"height":.028})
        add("clutter_"+str(i),kind,(x,y,0),**params)
    if clutter > 0:
        garden_chair=add("garden_chair","chair",(-.25,.07,0),color="#719080",cushion="#B18B5B")
        add("gardener_cup","mug",tuple(anchor(garden_chair,"seat")),color="#BA6743")
        add("seedling_crate","crate",(.265,.05,0),width=.065,depth=.055,height=.040)
        add("seedlings","plant",(.265,.05,.006),height=.065)
        add("forgotten_ball","ball",(.265,-.29,0),radius=.015,color="#C27844")
    # A flat, flush sandy path is part of the set shell, not an obstruction.
    path=_box_surface("garden_path",(.37,.81,.0006),(0,-.08,.0003),"paper","#B7A17B")
    path.parent=shell
    anchors={"center":(0,-.12,0),"mark_a":(-.11,-.12,0),"mark_b":(.11,-.12,0),
             "path_start":(0,-.43,0),"path_end":(0,.31,0),"sign":tuple(anchor(sign,"board"))}
    cams=_cameras(wide=(-.07,-1.55,.63),target=(0,.055,.23))
    return {"anchors":anchors,"cameras":cams,"light_rig":"bright","props":p,
            "bounds":((-width/2,-depth/2),(width/2,depth/2)),"shell":shell}


SETS.update(kitchen=kitchen,workshop=workshop,garden=garden)


def build_set(kind: str, *, seed=0, clutter=.6, **params) -> dict:
    """Build a whole unlit-camera-ready set; returns marks, cameras and props.

    Practical lights belong to the set; callers add the named stage.light_rig.
    Does not reset the scene or change the user's active material style.
    build_seconds measures this build only, excluding camera/render work.
    """
    if kind not in SETS:
        raise ValueError(f"unknown set {kind!r}; choose {', '.join(SETS)}")
    if not 0 <= clutter <= 1:
        raise ValueError("clutter must be in 0..1")
    start=time.perf_counter()
    result=SETS[kind](seed=seed,clutter=clutter,**params)
    result["build_seconds"]=round(time.perf_counter()-start,4)
    return result
