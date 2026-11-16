"""A shot: one camera setup, a cast of performers, baked and rendered exposure by exposure."""
from __future__ import annotations

import math
import os
import random
import time

import bpy
from mathutils import Matrix, Vector

from .. import stage as stage_mod
from .perform import Performer, _point
from .track import EASES, Track
from ..puppet import HIDDEN_SCALE
from ..util import hex_rgb


class _CameraPoint:
    """Where the camera is on a given exposure (so 'look at camera' follows camera moves)."""

    def __init__(self, shot):
        self.shot = shot

    def at_frame(self, frame) -> Vector:
        return Vector(self.shot.cam_track.value("from", frame))


class Shot:
    def __init__(self, scene, style, *, fps=None, seed=0):
        self.scene = scene
        self.style = style
        self.fps = float(fps or style["fps"])
        self.seed = seed
        self.performers: dict[str, Performer] = {}
        self.props: dict[str, bpy.types.Object] = {}
        self.anchors: dict[str, tuple] = {}
        self.cameras: dict[str, dict] = {}
        self.lights: dict[str, bpy.types.Object] = {}
        self.prop_tracks: dict[str, tuple[object, Track]] = {}
        self.roll_pivots: dict[str, tuple] = {}
        self.light_tracks: dict[str, Track] = {}
        self.world_track = Track()
        self.flashes: list[tuple[int,int]] = []
        self.bumps: list[tuple[int,int,float]] = []
        self.rig_center, self.rig_scale, self.rig_power = (0,0,.14), 1., 1.
        self.camera = None
        self.focus = None
        self.cam_track = Track()
        self.focus_target = None
        self.sfx: list[dict] = []
        self.first = 1
        self.last = 1

    # ------------------------------------------------------------ lookup ----
    def frames(self, seconds: float) -> int:
        return int(math.floor(seconds * self.fps + 0.5))

    def resolve(self, target):
        """Name -> performer, prop, anchor point or the camera; anything else passes through."""
        if isinstance(target, str):
            if target in self.performers:
                return self.performers[target]
            if target in self.props:
                bpy.context.view_layer.update()
                return self.props[target]
            if target in self.anchors:
                return Vector(self.anchors[target])
            if target == "camera":
                return _CameraPoint(self)
            if "." in target:  # "prop.anchor", e.g. "teapot.handle"
                prop, name = target.split(".", 1)
                root = self.props[prop]
                from ..props import anchor
                return anchor(root,name)
            raise KeyError(f"unknown target {target!r}")
        return target

    def point(self, target, frame=None) -> Vector:
        frame = self.first if frame is None else frame
        if isinstance(target,str):
            name, _, point = target.partition(".")
            if name in self.props:
                root = self.props[name]
                obj = root
                if point and point in root.get("anchor_parts",{}):
                    obj = next(o for o in root.children_recursive if o.name == root["anchor_parts"][point])
                local = Vector(root["anchors"][point]) if point else Vector((0,0,0))
                return self.prop_matrix(obj,frame,scheduled=getattr(self,"_baking_frame",None)!=frame) @ local
        return _point(self.resolve(target), frame)

    def prop_track(self, obj) -> Track:
        """Lazily capture an object's authored local transform before scheduling."""
        if obj.name not in self.prop_tracks:
            self.prop_tracks[obj.name] = (obj,Track({"location":tuple(obj.location),
                "rotation_euler":tuple(obj.rotation_euler),"scale":tuple(obj.scale)}))
        return self.prop_tracks[obj.name][1]

    def prop_matrix(self, obj, frame: int, *, scheduled=True) -> Matrix:
        """Scheduled local transforms composed through a prop hierarchy."""
        from mathutils import Euler
        track = self.prop_tracks.get(obj.name) if scheduled else None
        loc,rot,scale = ((track[1].value(k,frame) for k in ("location","rotation_euler","scale"))
                         if track else (obj.location,obj.rotation_euler,obj.scale))
        matrix = Matrix.LocRotScale(Vector(loc),Euler(rot).to_quaternion(),Vector(scale))
        return self.prop_matrix(obj.parent,frame,scheduled=scheduled) @ matrix if obj.parent else matrix

    def prop_action(self, start: int, beat: dict) -> int:
        """Schedule move/turn/spin/show/hide/shake; carried props are positioned last."""
        from ..props import bounds
        obj = self.props[beat["prop"]]
        if beat.get("part"):
            matches = [o for o in obj.children_recursive if beat["part"] in o.name.rsplit(".",1)[-1]]
            if len(matches) != 1:
                raise ValueError(f"part {beat['part']!r}: expected one match, got {[o.name for o in matches]}")
            obj = matches[0]
        tr = self.prop_track(obj)
        action = beat["do"]
        frames = max(1,self.frames(beat.get("time",1.)))
        ease = EASES[beat.get("ease","linear" if action == "spin" else "inout")]
        loc = Vector(tr.value("location",start))
        rot = Vector(tr.value("rotation_euler",start))
        if action in ("show","hide"):
            base = tuple(obj.get("visible_scale",tr.defaults["scale"]))
            tr.hold(start-1,["scale"])
            if action == "show":
                for i,shape in enumerate(((1.18,1.18,.78),(.94,.94,1.08),(1,1,1))):
                    tr.key(start+i,{"scale":tuple(a*b for a,b in zip(base,shape))},"step")
                return start+3
            tr.key(start,{"scale":tuple(v*HIDDEN_SCALE for v in base)},"step")
            return start+1
        tr.hold(start,["location","rotation_euler"])
        if action == "move":
            goal = self.point(beat["to"],start) if "to" in beat else loc.copy()
            if obj.parent:
                goal = self.prop_matrix(obj.parent,start).inverted() @ goal
            arc = float(beat.get("arc",0.))
            delta = goal-loc
            lo,hi = bounds(obj)
            radius = (float(obj["roll_radius"])*float(obj.get("visible_scale",obj.scale)[0])
                      if "roll_radius" in obj else max(hi.x-lo.x,hi.y-lo.y,hi.z-lo.z)/2)
            if beat.get("roll") and obj.name not in self.roll_pivots:
                bpy.context.view_layer.update()
                center = obj.matrix_world.inverted() @ ((lo+hi)/2)
                self.roll_pivots[obj.name] = (obj,center,obj.rotation_euler.to_matrix().copy(),
                                             {o.name:tuple(o.location) for o in obj.children})
            # Direction cross up: +X travel rotates about +Y; radius is in world metres.
            roll_axis = Vector((-delta.y,delta.x,0)).normalized() if delta.xy.length else Vector((0,1,0))
            for i in range(frames+1):
                t = i/frames
                pos = loc.lerp(goal,ease(t))
                pos.z += 4*arc*t*(1-t)
                values = {"location":tuple(pos)}
                if beat.get("roll"):
                    values["rotation_euler"] = tuple(rot+roll_axis*delta.xy.length/max(radius,1e-6)*ease(t))
                tr.key(start+i,values,"linear")
        elif action in ("turn","spin"):
            axis = "xyz".index(beat.get("axis","z").lower())
            angle = math.radians(float(beat.get("by",0.))) if action=="turn" else math.tau*float(beat.get("turns",1.))
            from mathutils import Euler
            base = Euler(rot).to_matrix()
            previous = Euler(rot)
            last_angle = 0.
            for i in range(frames+1):
                target_angle = angle*ease(i/frames)
                # Compose on the right: the named axis belongs to the prop,
                # even when its base has already been tilted on other axes.
                # Small internal steps unwrap spins spanning multiple turns
                # without adding sub-exposure animation keys.
                steps = max(1,math.ceil(abs(target_angle-last_angle)/(math.pi/2)))
                for j in range(1,steps+1):
                    a = last_angle+(target_angle-last_angle)*j/steps
                    previous = (base @ Matrix.Rotation(a,3,"XYZ"[axis])).to_euler("XYZ",previous)
                tr.key(start+i,{"rotation_euler":tuple(previous)},"linear")
                last_angle = target_angle
        elif action == "shake":
            rnd = random.Random(f"prop/{self.seed}/{beat['prop']}/{start}")
            for i in range(frames+1):
                amount = float(beat.get("amount",1.))*(1-i/frames)
                tr.key(start+i,{"location":tuple(loc+Vector((rnd.gauss(0,1),rnd.gauss(0,1),0))*.0015*amount),
                    "rotation_euler":tuple(rot+Vector((rnd.gauss(0,.05),rnd.gauss(0,.05),0))*amount)},"linear")
        else:
            raise KeyError(f"unknown prop action {action!r}")
        return start+frames

    def init_lights(self) -> None:
        """Capture all rig, set, prop and extra lights; every lamp gets exposure flicker."""
        for name,obj in self.lights.items():
            self.light_tracks[name] = Track({"energy":obj.data.energy,"color":tuple(obj.data.color),
                "location":tuple(obj.location),"size":getattr(obj.data,"size",.0),
                "spread":math.degrees(getattr(obj.data,"spread",math.pi))})  # area lamps: beam angle, 180 = open
        bg = self.scene.world.node_tree.nodes.get("Background")
        self.world_track = Track({"color":tuple(bg.inputs["Color"].default_value),"strength":bg.inputs["Strength"].default_value})

    def change_rig(self, start: int, rig: str, over: int=0) -> int:
        """Transition the three-point lamps and world; extras keep their own settings."""
        spec = stage_mod.LIGHT_RIGS[rig]
        for role in ("key","fill","rim"):
            tr,s = self.light_tracks[role],spec[role]
            tr.hold(start if over else start-1)
            tr.key(start+over,{"energy":s["power"]*self.rig_power*self.rig_scale**2,
                "color":hex_rgb(s["color"])[:3],"location":tuple(Vector(self.rig_center)+Vector(s["offset"])*self.rig_scale),
                "size":s["size"]*self.rig_scale,"spread":float(s.get("spread",180.))},"inout" if over else "step")
        self.world_track.hold(start if over else start-1)
        self.world_track.key(start+over,{"color":hex_rgb(spec["world"][0]),"strength":spec["world"][1]},"inout" if over else "step")
        return start+over

    def light_power(self, start: int, name: str, power: float, over: int=0) -> int:
        tr = self.light_tracks[name]
        tr.hold(start if over else start-1,["energy"])
        tr.key(start+over,{"energy":float(power)},"inout" if over else "step")
        return start+over

    def shake_camera(self, start: int, frames: int, amount: float) -> int:
        self.bumps.append((start,max(1,frames),float(amount)))
        return start+max(1,frames)

    def camera_bump(self, frame: int) -> Vector:
        """Seeded few-millimetre impact; exactly zero at and after its end."""
        delta = Vector()
        for start,frames,amount in self.bumps:
            if start <= frame < start+frames:
                r = random.Random(f"impact/{self.seed}/{start}/{frame}")
                direction = Vector((r.uniform(-1,1),r.uniform(-.35,.35),r.uniform(-1,1))).normalized()
                delta += direction*.004*amount*(1-(frame-start)/frames)**2
        return delta

    def add_performer(self, name, puppet, *, at=(0, 0), heading=0.0) -> Performer:
        perf = Performer(name, puppet, seed=self.seed, at=at, heading=heading)
        self.performers[name] = perf
        return perf

    # ------------------------------------------------------------ camera ----
    def camera_spec(self, spec) -> dict:
        """A camera name from the set, or {from, to, lens, fstop, focus}; points may be target names."""
        if isinstance(spec, str):
            spec = self.cameras[spec]
        if "shot" in spec:
            spec = self.frame_performer(spec)
        out = dict(spec)
        for key in ("from", "to"):
            if isinstance(out[key], str):
                out[key] = tuple(self.point(out[key]))
            out[key] = tuple(out[key])
        out.setdefault("lens", float(self.style["lens"]))
        out.setdefault("fstop", float(self.style["fstop"]))
        out.setdefault("roll",0.)
        return out

    FRAMINGS = {
        # name: (frame height in body heights, aim height in body heights; None = eye line)
        "close": (0.66, None),
        "medium": (0.82, 0.76),
        "full": (1.45, 0.52),
    }

    def frame_performer(self, spec: dict) -> dict:
        """{shot: close|medium|full, of: name, angle?: deg, lens?, height?}: frame one character.

        Works for any puppet size. `angle` orbits the camera around them (0 = straight on
        from the front of the set, + = from screen right); `height` raises the camera.
        """
        perf = self.performers[spec["of"]]
        tall, aim = self.FRAMINGS[spec["shot"]]
        lens = float(spec.get("lens", 65 if spec["shot"] == "close" else 50))
        base = Vector(perf.place.value("pos", self.first))
        eye = perf.head_point(self.first)
        target = Vector((eye.x, eye.y, eye.z if aim is None else aim * perf.H))
        if aim is not None:
            target.x, target.y, target.z = base.x, base.y, base.z + aim * perf.H
        distance = tall * perf.H * lens / 20.25  # 36 mm sensor, 16:9 -> 20.25 mm tall
        angle = math.radians(spec.get("angle", 0.0))
        offset = Vector((math.sin(angle), -math.cos(angle), spec.get("height", 0.06))) * distance
        return {"from": tuple(target + offset), "to": tuple(target), "lens": lens,
                "fstop": spec.get("fstop", 2.8 if spec["shot"] == "close" else 4.0), "focus": spec["of"], "roll":spec.get("roll",0.)}

    def set_camera(self, frame: int, spec, *, move: int = 0, ease="inout") -> None:
        """Cut to a camera setup at `frame`, or travel to it over `move` exposures."""
        spec = self.camera_spec(spec)
        if self.camera is None:
            self.camera, self.focus = stage_mod.add_camera(
                self.scene, spec["from"], spec["to"], lens=spec["lens"], fstop=spec["fstop"]
            )
        keys = {"from": spec["from"], "to": spec["to"], "lens": float(spec["lens"]), "fstop": float(spec["fstop"]), "roll":float(spec["roll"])}
        if move:
            self.cam_track.hold(frame)
            self.cam_track.key(frame + move, keys, ease)
        else:
            self.cam_track.key(frame, keys, "step")
        if "focus" in spec:
            self.focus_target = spec["focus"]

    def _bake_camera(self, frame: int, wobble: float) -> None:
        cam = self.camera
        src = Vector(self.cam_track.value("from", frame))
        dst = Vector(self.cam_track.value("to", frame))
        r = random.Random(f"cam/{self.seed}/{frame}")
        # style key camera_drift: a tripod nudged between exposures (1.0 = 0.4 mm, which is several
        # pixels of shake in a close-up). 0 = locked off; moves are still smooth.
        src = src + Vector((r.gauss(0, 1), r.gauss(0, 1), r.gauss(0, 1))) * 0.0004 * wobble
        cam.location = src + self.camera_bump(frame)
        stage_mod.look_at(cam, dst,roll=math.radians(self.cam_track.value("roll",frame)))
        cam.data.lens = self.cam_track.value("lens", frame)
        cam.data.dof.aperture_fstop = self.cam_track.value("fstop", frame)
        focus = self.point(self.focus_target, frame) if self.focus_target else dst
        self.focus.location = focus
        cam.keyframe_insert("location", frame=frame)
        cam.keyframe_insert("rotation_euler", frame=frame)
        cam.data.keyframe_insert("lens", frame=frame)
        cam.data.dof.keyframe_insert("aperture_fstop", frame=frame)
        self.focus.keyframe_insert("location", frame=frame)

    # -------------------------------------------------------------- bake ----
    def bake(self, first: int, last: int) -> None:
        self.first, self.last = first, last
        scene = self.scene
        scene.frame_start, scene.frame_end = first, last
        wobble = float(self.style["pose_jitter"])
        flicker = float(self.style["light_flicker"])
        if not self.light_tracks:
            self.init_lights()
        for perf in self.performers.values():
            perf.idle_amount = float(self.style.spec.get("idle", 1.0))  # 0 = held perfectly still between moves
            if self.style.spec.get("blinks", True):
                perf.plan_blinks(first, last, self.fps)
        for frame in range(first, last + 1):
            self._baking_frame = frame
            # Free prop tracks first. Hand carry keys replace these positions below.
            for obj,tr in self.prop_tracks.values():
                for channel in ("location","rotation_euler","scale"):
                    setattr(obj,channel,tr.value(channel,frame))
                    obj.keyframe_insert(channel,frame=frame)
            # Prop roots sit on z=0; roll geometry about its centre, not its floor
            # origin, without changing the director's root-location path.
            for obj,center,rest_rot,children in self.roll_pivots.values():
                offset = obj.rotation_euler.to_matrix().inverted() @ (rest_rot @ center)-center
                for child in obj.children:
                    tr = self.prop_tracks.get(child.name)
                    base = tr[1].value("location",frame) if tr else children[child.name]
                    child.location = Vector(base)+offset
                    child.keyframe_insert("location",frame=frame)
            for perf in self.performers.values():
                perf.bake_frame(frame, self.fps, self, wobble)
            if self.camera is not None:
                self._bake_camera(frame, float(self.style["camera_drift"]))
            r = random.Random(f"light/{self.seed}/{frame}")
            gain = 1.0 + r.gauss(0, flicker)  # exposure flicker: all lamps drift together
            flash = any(start <= frame < end for start,end in self.flashes)
            for name, light in self.lights.items():
                tr = self.light_tracks[name]
                light.data.energy = tr.value("energy",frame)*gain*(6. if flash else 1.)
                light.data.color = (.65,.80,1.) if flash else tr.value("color",frame)
                light.location = tr.value("location",frame)
                if light.data.type == "AREA":
                    light.data.size = tr.value("size",frame)
                    light.data.keyframe_insert("size",frame=frame)
                    light.data.spread = math.radians(tr.value("spread",frame))
                    light.data.keyframe_insert("spread",frame=frame)
                if name in ("key","fill","rim"):
                    stage_mod.look_at(light,self.rig_center)
                    light.keyframe_insert("rotation_euler",frame=frame)
                light.keyframe_insert("location",frame=frame)
                for channel in ("energy","color"):
                    light.data.keyframe_insert(channel, frame=frame)
            bg = scene.world.node_tree.nodes.get("Background")
            bg.inputs["Color"].default_value = (.65,.80,1.,1.) if flash else self.world_track.value("color",frame)
            bg.inputs["Strength"].default_value = 2.5 if flash else self.world_track.value("strength",frame)
            for channel in ("Color","Strength"):
                bg.inputs[channel].keyframe_insert("default_value",frame=frame)
        self._baking_frame = None

    # ------------------------------------------------------------ render ----
    def render(self, outdir: str, *, frames=None) -> dict:
        os.makedirs(outdir, exist_ok=True)
        scene = self.scene
        todo = list(frames) if frames is not None else list(range(self.first, self.last + 1))
        started = time.time()
        for frame in todo:
            scene.frame_set(frame)
            scene.render.filepath = os.path.join(outdir, f"f_{frame:05d}.png")
            bpy.ops.render.render(write_still=True)
        seconds = time.time() - started
        return {"frames": len(todo), "seconds": round(seconds, 2), "per_frame": round(seconds / max(len(todo), 1), 3)}
