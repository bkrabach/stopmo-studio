"""Exposure-by-exposure staging acceptance. tools/bl.sh tools/check_stage.py [--looks].

No audio or external services. --looks also saves close-ups, lever states and
light looks under out/staging/looks for independent visual review.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, os.environ["STOPMO_SRC"])
import bpy
from mathutils import Vector
from stopmo_bl import stage, props
from stopmo_bl.director import Director
from stopmo_bl.archetypes.biped import REST

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "out/staging"
COUNTS = {"plans": 0, "exposures": 0, "assertions": 0, "actions": 0, "emotes": 0}


def require(condition: bool, message: str) -> None:
    COUNTS["assertions"] += 1
    if not condition:
        raise AssertionError(message)


def near(a, b, message: str, tolerance=1e-5) -> None:
    error = (Vector(a)-Vector(b)).length if hasattr(a,"__len__") else abs(a-b)
    require(error < tolerance, f"{message}: error {error:g}, {a} != {b}")


def characters() -> dict:
    """Independent synthetic test actors; no production show or voice files."""
    return {
        "actor_a": {"height": .25, "eyes": {"brows": {}}},
        "actor_b": {"height": .20, "eyes": {"brows": {}, "pupil": .3}},
    }


def plan(shot: dict, cast=None) -> dict:
    return {"shot":{"lead":0,"hold":.3,**shot},"characters":cast or {},
            "style":{"pose_jitter":0,"light_flicker":0},"seed":17,"frames":"none",
            "resolution":[1280,720],"samples":32}


def build(spec: dict, name: str):
    folder = OUT/name
    folder.mkdir(parents=True,exist_ok=True)
    (folder/"plan.json").write_text(json.dumps(spec,indent=2))
    director = Director(spec)
    director.run(str(folder))
    COUNTS["plans"] += 1
    return director


def prop_checks() -> None:
    spec = plan({"dress":[
        {"add":"ball","name":"ball","at":[0,0,0]},
        {"add":"lever","name":"lever"},
        {"add":"gear","name":"gear"},
        {"add":"crumbs","name":"crumbs","hidden":True,"scale":1.4}],
        "anchors":{"goal":[.12,0,0]},
        "beats":[
            {"prop":"ball","do":"move","to":"goal","time":1,"arc":.06,"roll":True,"t":0},
            {"prop":"lever","part":"arm","do":"turn","by":50,"axis":"y","time":1,"t":0},
            {"prop":"gear","do":"spin","turns":3,"axis":"z","time":1,"t":0},
            {"prop":"crumbs","do":"show","t":.5},
            {"prop":"crumbs","do":"hide","t":1.},
            {"prop":"ball","do":"shake","time":.5,"t":1.5},
            {"prop":"ball","do":"move","to":"lever.pivot","time":.5,"t":2.5}]})
    d = build(spec,"numeric_props")
    s = d.shot
    ball,gear,lever,crumb = (s.props[n] for n in ("ball","gear","lever","crumbs"))
    arm = next(o for o in lever.children if o.name.endswith(".arm"))
    z = []
    for f in range(1,s.last+1):
        s.scene.frame_set(f)
        COUNTS["exposures"] += 1
        if f <= 13:
            z.append(ball.location.z)
            t=(f-1)/12
            near(ball.location,(.12*t*t*(3-2*t),0,4*.06*t*(1-t)),f"move f{f}")
            near(arm.rotation_euler.y, math.radians(-25+50*t*t*(3-2*t)),f"turn f{f}")
            near(gear.rotation_euler.z, math.tau*3*t,f"spin f{f}")
            near(arm.rotation_euler.x,0,f"turn other axis f{f}")
            near(arm.rotation_euler.z,0,f"turn other axis f{f}")
            near(ball.rotation_euler.y,.12/.023*t*t*(3-2*t),f"roll distance/radius f{f}")
        if f < 7 or f >= 13:
            near(tuple(crumb.scale),(1.4e-4,)*3,f"hidden f{f}",1e-6)
        else:
            require(all(v>.5 for v in crumb.scale),f"show f{f}")
        require(not crumb.hide_render,f"no keyed visibility f{f}")
    near(max(z),.06,"arc peak")
    s.scene.frame_set(13)
    require(abs(ball.rotation_euler.y)>4.,"roll did not rotate")
    near(ball.location,(.12,0,0),"move endpoint")
    s.scene.frame_set(37)
    near(ball.location,s.point("lever.pivot",37),"anchor move endpoint")
    # Scheduling rules, not only direct absolute-time actions.
    d = Director(plan({"dress":[{"add":"ball","name":"b"}],"beats":[
        {"prop":"b","do":"move","time":.5},{"prop":"b","do":"turn","by":20,"time":.25,"with":True,"delay":.25},
        {"prop":"b","do":"show","t":1.}]}))
    d.build()
    last=d.schedule()
    require(last==20,f"t/with/delay/end scheduling {last}")
    # A run of `with` beats counts every delay from the same anchor beat; delays do not stack.
    d = Director(plan({"dress":[{"add":"ball","name":"b"}],"beats":[
        {"wait":.5},{"prop":"b","do":"move","time":.5},
        {"prop":"b","do":"shake","time":.25,"with":True,"delay":.25},
        {"prop":"b","do":"turn","by":20,"time":.25,"with":True,"delay":.5},
        {"sfx":"pop","with":True},{"wait":.25},{"sfx":"pop","with":True,"delay":.25}]}))
    d.build()
    d.schedule()
    first=d.starts[0]
    require([f-first for f in d.starts]==[0,6,9,12,6,12,15],f"with-anchor scheduling {[f-first for f in d.starts]}")
    from mathutils import Euler, Matrix
    for axis in ("x","y","z"):
        d=build(plan({"dress":[{"add":"gear","name":"g"}],"beats":[{"wait":.5}]}),"numeric_axis_"+axis)
        s=d.shot
        obj=s.props["g"]
        base=Euler((.3,-.2,.4))
        s.prop_track(obj).defaults["rotation_euler"]=tuple(base)
        s.prop_action(1,{"prop":"g","do":"turn","axis":axis,"by":93,"time":.5})
        s.bake(1,7)
        for f in range(1,8):
            s.scene.frame_set(f)
            COUNTS["exposures"]+=1
            t=(f-1)/6
            expected=base.to_matrix() @ Matrix.Rotation(math.radians(93)*t*t*(3-2*t),3,axis.upper())
            actual=obj.rotation_euler.to_matrix()
            require(max(abs(actual[i][j]-expected[i][j]) for i in range(3) for j in range(3))<1e-5,
                    f"pretilted local {axis} rotation f{f}")


def light_camera_checks() -> None:
    spec = plan({"camera":{"from":[0,-.6,.2],"to":[0,0,.15],"roll":17},
        "lights":[{"name":"bulb","kind":"point","at":"center","power":2},
                  {"name":"spot","kind":"spot","at":[0,-.2,.3],"to":"center","power":3,"angle":28},
                  {"name":"soft","kind":"area","at":[.2,-.2,.3],"to":"center","power":4,"size":.08}],
        "beats":[{"lights":"interrogation","over":1,"t":0},
                 {"shake":1.,"time":1.,"t":0},
                 {"lights":"flash","time":.17,"t":1.25},
                 {"light":"bulb","power":0,"over":.5,"t":1.5},
                 {"camera":{"from":[.1,-.6,.2],"to":[0,0,.15],"roll":-10},"move":.5,"t":2.}]})
    d=build(spec,"numeric_lights")
    s=d.shot
    near(s.lights["spot"].data.spot_size,math.radians(28),"spot angle")
    for name,power in (("bulb",2),("spot",3),("soft",4)):
        near(s.light_tracks[name].value("energy",1),power,"extra light initial power")
    for f in range(1,s.last+1):
        s.scene.frame_set(f)
        COUNTS["exposures"] += 1
        flash = 16 <= f < 18
        for role in ("key","fill","rim"):
            expected=s.light_tracks[role].value("energy",f)*(6 if flash else 1)
            near(s.lights[role].data.energy,expected,f"rig/flash f{f}")
        near(s.camera.location,Vector(s.cam_track.value("from",f))+s.camera_bump(f),f"camera shake f{f}")
        bump=s.camera_bump(f).length
        near(bump,.004*(1-(f-1)/12)**2 if f<13 else 0.,f"shake envelope f{f}")
    s.scene.frame_set(13)
    for role in ("key","fill","rim"):
        near(s.lights[role].data.energy,stage.LIGHT_RIGS["interrogation"][role]["power"]*.9**2,"rig endpoint")
        near(s.lights[role].data.color,s.light_tracks[role].value("color",13),"rig colour")
        near(s.lights[role].location,s.light_tracks[role].value("location",13),"rig location")
    expected=s.camera.rotation_euler.to_matrix()
    # Roll is a camera-local Z rotation, not a world Euler component.
    direction=Vector((0,0,.15))-Vector((0,-.6,.2))
    base=direction.to_track_quat("-Z","Y")
    from mathutils import Matrix
    target=base.to_matrix() @ Matrix.Rotation(math.radians(17),3,"Z")
    require(max(abs(expected[i][j]-target[i][j]) for i in range(3) for j in range(3))<1e-5,"camera roll")
    s.scene.frame_set(25)
    near(s.lights["bulb"].data.energy,0,"power fade")
    s.scene.frame_set(18)
    near(s.lights["key"].data.energy,stage.LIGHT_RIGS["interrogation"]["key"]["power"]*.9**2,"flash restore")
    s.scene.frame_set(31)
    near(s.cam_track.value("roll",31),-10,"roll move end")
    for f in range(1,s.last+1):
        s.scene.frame_set(f)
        flash=16 <= f < 18
        bg=s.scene.world.node_tree.nodes["Background"]
        near(bg.inputs["Strength"].default_value,2.5 if flash else s.world_track.value("strength",f),
             f"world strength f{f}")
        near(bg.inputs["Color"].default_value,(.65,.80,1.,1.) if flash else s.world_track.value("color",f),
             f"world colour f{f}")
    near(s.light_tracks["key"].value("energy",7),(stage.LIGHT_RIGS["cosy"]["key"]["power"]+stage.LIGHT_RIGS["interrogation"]["key"]["power"])/2*.9**2,"rig halfway easing")


def actor_checks(cast: dict) -> None:
    for name,spec in cast.items():
        beats=[]
        for action in ("startle","double_take","shifty","slump","tremble","chew","sip","peer"):
            beats.append({"who":name,"do":action,"at":"target","time":.5})
            beats.append({"who":name,"do":"pose","pose":REST,"over":.25})
            COUNTS["actions"]+=1
        for mood in ("skeptical","deadpan","sheepish","guilty","proud"):
            beats.append({"who":name,"do":"emote","name":mood})
            COUNTS["emotes"]+=1
        d=build(plan({"cast":{name:{"holding":"cup","side":"r"}},"dress":[{"add":"mug","name":"cup"}],
                      "anchors":{"target":[.15,-.15,.19]},"beats":beats},cast),"numeric_"+name)
        s,p=d.shot,d.shot.performers[name].puppet
        p.pose({"brows.cock":1.})
        for brow in p.brows:
            require((brow["holder"].location.z-brow["rest"].z)*brow["sign"]>0,"brows.cock sign "+name)
        for eye in p.eyes:
            closed=p.swaps["lid_"+eye["side"]]["closed"][0]
            # All pupil-front vertices must be behind the closed shell's front.
            front=min(v.co.y for v in closed.data.vertices)+p.face.center.y
            pupil_front=eye["center"].y-eye["radius"]*(.985+.45*spec.get("eyes",{}).get("pupil",.26))
            require(front < pupil_front,f"{name}: pupil protrudes through closed eyelid")
        max_carry=0.
        max_foot=0.
        for f in range(1,s.last+1):
            s.scene.frame_set(f)
            COUNTS["exposures"]+=1
            arm=p.armature
            for bone in arm.pose.bones:
                require(all(math.isfinite(v) for row in bone.matrix for v in row),f"{name}: NaN bone f{f}")
            for side in ("l","r"):
                ankle=arm.pose.bones["foot_"+side].head
                max_foot=max(max_foot,abs(ankle.z-p.skel.rest_head["foot_"+side].z))
            hand=arm.pose.bones["hand_r"]
            grip=arm.matrix_world @ (hand.head+hand.matrix.to_3x3().col[1]*p.skel.length["hand_r"]*.75)
            cup=s.props["cup"]
            actual=cup.location+cup.rotation_euler.to_matrix() @ Vector(cup["grip"])
            max_carry=max(max_carry,(grip-actual).length)
            for key,variants in p.swaps.items():
                visible=[variant for variant,objects in variants.items() if any(o.scale.x>.5 for o in objects)]
                require(len(visible)==1,f"{name}: {key} invalid replacement states f{f}: {visible}")
        require(max_carry<.02,f"{name}: carry error {max_carry}")
        require(max_foot<.002,f"{name}: feet drift {max_foot}")
        print("ACTOR_OK",name,"max_carry_mm",round(max_carry*1000,5),"max_foot_mm",round(max_foot*1000,5),flush=True)
    # Exercise actual take/put as well as entry holding, including conflicting prop motion.
    name=next(iter(cast))
    d=build(plan({"cast":{name:{}},"dress":[{"add":"mug","name":"cup","at":[-.04,-.04,.10]}],
        "beats":[{"who":name,"do":"take","prop":"cup"},
                 {"prop":"cup","do":"move","to":[.5,0,.2],"time":1,"with":True,"delay":.6},
                 {"who":name,"do":"sip","time":.4},
                 {"who":name,"do":"put","prop":"cup","onto":[-.04,-.05,.1]}]},cast),"numeric_take")
    s=d.shot
    perf=s.performers[name]
    acquire,release=perf.held[0][0],perf.held[1][0]
    for f in range(acquire,release):
        s.scene.frame_set(f)
        p=perf.puppet
        hand=p.armature.pose.bones["hand_r"]
        grip=p.armature.matrix_world @ (hand.head+hand.matrix.to_3x3().col[1]*p.skel.length["hand_r"]*.75)
        near(s.props["cup"].location+Vector(s.props["cup"]["grip"]),grip,"take carry",.02)
    s.scene.frame_set(s.last)
    near(s.props["cup"].location,(-.04,-.05,.1),"put endpoint")


def looks(cast: dict) -> None:
    """Save full-size single frames only; a receipt is not a visual verdict."""
    folder=OUT/"looks"
    folder.mkdir(parents=True,exist_ok=True)
    for name in cast:
        for mood in ("skeptical","deadpan","sheepish","guilty","proud"):
            d=build(plan({"cast":{name:{"emote":mood}},
                          "camera":{"shot":"close","of":name},
                          "beats":[{"wait":.3}]},cast),"look_"+name+"_"+mood)
            d.shot.render(str(folder/name/mood),frames=[3])
    for rig in ("interrogation","storm","flash"):
        d=build(plan({"set":"kitchen","cast":{"actor_a":{"at":"mark_a"},"actor_b":{"at":"mark_b"}},
                      "camera":"two_shot","light_rig":rig if rig!="flash" else "storm",
                      "beats":[{"lights":"flash","time":.3}] if rig=="flash" else [{"wait":.3}]},cast),"look_"+rig)
        d.shot.render(str(folder/rig),frames=[2])
    d=build(plan({"dress":[{"add":"lever","name":"lever"}],
                  "camera":{"from":[.10,-.25,.12],"to":[0,0,.045],"lens":58,"fstop":11},
                  "beats":[{"prop":"lever","part":"arm","do":"turn","by":50,"axis":"y","time":1.}]},cast),"look_lever")
    d.shot.render(str(folder/"lever"),frames=[1,13])


def diagnose_face(cast: dict) -> None:
    """Print evaluated replacement transforms for the two strict facial states."""
    for name in cast:
        for mood in ("skeptical","proud"):
            d=build(plan({"cast":{name:{"emote":mood}},
                          "camera":{"shot":"close","of":name},"beats":[{"wait":.3}]},cast),
                    "diagnostic_"+name+"_"+mood)
            perf=d.shot.performers[name]
            d.scene.frame_set(3)
            print("FACE_STATE",name,mood,perf.track.sample(3),flush=True)
            for group in ("lid_l","lid_r"):
                for variant,objects in perf.puppet.swaps[group].items():
                    print("LID",group,variant,[(o.name,tuple(o.scale),tuple(o.matrix_world.translation)) for o in objects],flush=True)
            print("BROWS",[(b["side"],tuple(b["holder"].location),tuple(b["rest"])) for b in perf.puppet.brows],flush=True)
            d.scene.render.use_persistent_data=False
            d.shot.render(str(OUT/"diagnostic"/name/mood),frames=[3])


def main() -> None:
    started=time.perf_counter()
    cast=characters()
    if "--diagnose-face" in sys.argv:
        diagnose_face(cast)
        return
    if "--looks-only" in sys.argv:
        looks(cast)
        return
    prop_checks()
    light_camera_checks()
    actor_checks(cast)
    print("STAGING_SUMMARY",json.dumps(COUNTS),"failures 0 seconds",round(time.perf_counter()-started,2),flush=True)
    print("PASS: props/arc/roll/hinge/spin/pop, scheduling, carry/take/put, brows, 16 actions, "
          "10 emotes, finite poses/planted feet/exclusive swaps, camera roll/decay, "
          "rig/world/flash/practical lights.",flush=True)
    if "--looks" in sys.argv:
        looks(cast)


if __name__=="__main__":
    main()