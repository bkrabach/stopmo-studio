"""Blender numeric acceptance: tools/bl.sh tools/check_props.py (nonzero on failure)."""
from __future__ import annotations

import math
import os
import sys
import time
import traceback

sys.path.insert(0,os.environ["STOPMO_SRC"])
import bpy
from mathutils import Vector
from stopmo_bl import props, sets, stage, style, util
from stopmo_bl.materials import library, patterns

FAILURES=[]
COUNTS={"prop_builds":0,"prop_meshes":0,"sets":0,"clearance_checks":0,"anchors":0}


def require(condition, message):
    if not condition:
        FAILURES.append(message)
        print("FAIL",message,flush=True)


def check_meshes(objects, label):
    for obj in objects:
        if obj.type!="MESH":
            continue
        COUNTS["prop_meshes"]+=1
        require(len(obj.data.vertices)>0,label+": empty mesh "+obj.name)
        require(obj.data.attributes.get("rest") is not None,label+": missing rest "+obj.name)
        require(bool(obj.data.materials) and all(m is not None for m in obj.data.materials),
                label+": missing material "+obj.name)
        require(all(math.isfinite(c) for v in obj.data.vertices for c in v.co),label+": nonfinite mesh "+obj.name)


def check_prop(kind,seed):
    util.reset_scene()
    style.use()
    root=props.build_prop(kind,seed=seed)
    COUNTS["prop_builds"]+=1
    lo,hi=props.bounds(root)
    label=f"{kind}[seed={seed}]"
    require(-.002<=lo.z<=.004,f"{label}: floor min_z={lo.z:.6f}")
    size=hi-lo
    require(all(0<d<=1.5 for d in size),f"{label}: dimensions={tuple(size)}")
    check_meshes(props.descendants(root),label)
    for name,point in root["anchors"].items():
        COUNTS["anchors"]+=1
        p=props.anchor(root,name)
        require(all(lo[i]-.2*size[i]-.0001<=p[i]<=hi[i]+.2*size[i]+.0001 for i in range(3)),
                f"{label}: anchor {name} {tuple(p)} outside {tuple(lo)}..{tuple(hi)}")
    if kind=="lamp":
        require(any(o.type=="LIGHT" for o in props.descendants(root)),"lamp: no practical light")
    # Verify world anchor transform semantics, independently of the builder.
    if root["anchors"]:
        root.location=(.21,-.16,.03)
        root.rotation_euler.z=.7
        root.scale=(1.3,)*3
        bpy.context.view_layer.update()
        key=next(iter(root["anchors"]))
        part_name=root.get("anchor_parts",{}).get(key)
        owner=bpy.data.objects[part_name] if part_name else root
        expected=owner.matrix_world @ Vector(root["anchors"][key])
        require((props.anchor(root,key)-expected).length<1e-6,label+": incorrect world anchor")
    print("PROP_OK",label,"size",tuple(round(v,4) for v in size),flush=True)


def check_set(kind,seed=0):
    util.reset_scene()
    style.use()
    result=sets.build_set(kind,seed=seed)
    COUNTS["sets"]+=1
    required={"anchors","cameras","light_rig","props","bounds"}
    require(required<=set(result),kind+": missing return keys")
    marks={"center","mark_a","mark_b"}
    extra={"kitchen":{"table_top","seat_a","seat_b","window","door"},
           "workshop":{"bench_top","lever"},"garden":{"path_start","path_end","sign"}}[kind]
    require(marks|extra<=set(result["anchors"]),kind+": missing anchors")
    require({"wide","two_shot","close_a","close_b"}<=set(result["cameras"]),kind+": missing cameras")
    require(result["light_rig"] in stage.LIGHT_RIGS,kind+": bad rig")
    for name,camera in result["cameras"].items():
        require({"from","to","lens"}<=set(camera),kind+": incomplete camera "+name)
        require(camera["lens"]>0 and (Vector(camera["from"])-Vector(camera["to"])).length>.01,
                kind+": degenerate camera "+name)
    mn,mx=result["bounds"]
    for key in marks:
        point=result["anchors"][key]
        require(all(mn[i]<=point[i]<=mx[i] for i in (0,1)),kind+": mark outside floor "+key)
        for name,root in result["props"].items():
            lo,hi=props.bounds(root)
            dx=max(lo.x-point[0],0,point[0]-hi.x)
            dy=max(lo.y-point[1],0,point[1]-hi.y)
            distance=math.hypot(dx,dy)
            COUNTS["clearance_checks"]+=1
            require(distance>=.05,f"{kind}: {key} only {distance:.4f} m from {name}")
    # New clutter must not obstruct the front kitchen table edge or workshop
    # chain-reaction lane. Original hero equipment may occupy the bench itself.
    for name,root in result["props"].items():
        if kind=="kitchen" and name in {"towel","jam_jar","second_picture","sugar_bowl","extra_cup",
                                       "shelf_crumbs","hanging_spoon","second_spoon","sugar"}:
            lo,hi=props.bounds(root)
            require(not (lo.x < .37 and hi.x > .18 and lo.y < .075 and hi.y > .05),
                    f"kitchen: clutter {name} blocks table front edge")
        if kind=="workshop" and name in {"plans","oil","spare_pipe","small_gear","rolled_plans","tools","nuts","bolts"}:
            lo,hi=props.bounds(root)
            require(not (lo.x < .34 and hi.x > -.08 and lo.y < .375 and hi.y > .225
                         and lo.z < .18 and hi.z > .11),
                    f"workshop: clutter {name} blocks bench gag lane")
    separation=(Vector(result["anchors"]["mark_a"])-Vector(result["anchors"]["mark_b"])).length
    require(.20<=separation<=.24,kind+": marks not approximately .22 m apart")
    check_meshes(list(bpy.context.scene.objects),kind)
    print("SET_OK",kind,"seed",seed,"build_s",result["build_seconds"],"props",len(result["props"]),flush=True)


start=time.perf_counter()
for kind in props.PROPS:
    for seed in (0,173):
        try:
            check_prop(kind,seed)
        except Exception as error:
            FAILURES.append(f"{kind}[{seed}]: {error}")
            traceback.print_exc()
for kind in sets.SETS:
    for seed in (0,173):
        try:
            check_set(kind,seed)
        except Exception as error:
            FAILURES.append(f"{kind}[{seed}]: {error}")
            traceback.print_exc()
# Exercise every material registration, including checker (not used by a default prop).
for key,opts in (("stripes",{}),("checker",{}),("grass",{}),("sky",{}),("brick",{})):
    try:
        require(key in library.RECIPES,"missing registered pattern "+key)
        library.make(key,"check_"+key,"#7F9573",**opts)
    except Exception as error:
        FAILURES.append(f"pattern {key}: {error}")
        traceback.print_exc()
print("SUMMARY",COUNTS,"failures",len(FAILURES),"seconds",round(time.perf_counter()-start,2),flush=True)
if FAILURES:
    for failure in FAILURES:
        print("FAILURE",failure,flush=True)
    raise SystemExit(1)
print("PASS: every prop, both seeds; all sets, both seeds; patterns, rest, materials, bounds, anchors, clear marks.",flush=True)
