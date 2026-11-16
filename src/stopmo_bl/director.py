"""Director: turns one shot of a compiled plan into baked animation and rendered exposures.

Run inside Blender:  tools/bl.sh src/stopmo_bl/director.py plan.json

The plan is written by the host (`stopmo.build`): it already contains resolved
character specs, the style pack, and for every spoken line the wav path, its
length in exposures and the quantized mouth cues. The director schedules the
beats, bakes, renders, and writes `timing.json` so the host can lay the sound.

Beat reference (times in seconds; every beat may carry `t`, `with`, `delay`):

    {who, say: "text", gesture?, side?, emote?, look?, rate?}   speak a line (lip-synced); lines are kept
                                                            at least 0.25 s apart (shot key `line_gap`); a `who`
                                                            that is not in the shot is heard off-screen
    {who, do: gesture, name, side?, hold?}                  point / think / shrug / cheer ...
    {who, do: emote, name}                                  happy / sad / surprised ...
    {who, do: wave | nod | shake | hop | lean}              stock moves
    {who, do: look, at: target | null}                      head + eyes follow a target
    {who, do: walk, to: anchor | [x, y]}                    walk there (footsteps are added)
    {who, do: hop_to, to, hops?, hop?, height?, turn?}     travel in little hops (toy figures); a z in `to` hops up or
                                                            down; turn: false keeps facing the same way (a sideways shuffle)
    {who, do: face, to: target}  /  {who, do: turn, heading}
    {who, do: reach, to: target, side?}                     touch something
    {who, do: take, prop}  /  {who, do: put, prop, onto: anchor | [x, y, z]}
    {who, do: pose, pose: {...}, over?}                     explicit pose channels
    {who, do: startle | slump}                              recoil / persistent droop
    {who, do: double_take | peer, at: TARGET}                snap back / persistent lean
    {who, do: shifty, times: 3}                             eyes only, left-right
    {who, do: tremble | chew, time: 1}                       shudder / closed-mouth chewing
    {who, do: sip, side: r, time: 1}                         lift, hold for time, lower
    {camera: name | {from, to, lens?, fstop?, focus?, roll?}, move?}
    {camera: {shot: close|medium|full, of: who, angle?, roll?}}
    {shake: 1.0, time: 0.4}                                 decaying camera impact
    {prop: NAME, do: move, to?: TARGET, time: .5, arc: 0, ease: inout, roll: false}
    {prop: NAME, part?: arm, do: turn, by: 45, axis: y, time: .4, ease: inout}
    {prop: NAME, do: spin, turns: 3, axis: z, time: 1.5}     linear unless ease specified
    {prop: NAME, do: show | hide}                           3-exposure pop / instant vanish
    {prop: NAME, do: shake, time: 1, amount: 1}              seeded shudder
    {lights: RIG_NAME, over: 0}                             three-point rig + world transition
    {lights: flash, time: .17}                              cool lightning, then prior state
    {light: NAME, power: 0, over: 0}                        extra practical on/off/fade; `scale: 0..1` instead of
                                                            `power` is a share of the power the set built it with
    {sfx: kind, gain?}                                      a sound effect
    {wait: seconds}

TARGET is an anchor, "prop.anchor", character, prop, "camera" or [x,y,z].
Angles are degrees (except dress `heading`, radians); arc and positions are metres.
New emotes: skeptical, deadpan, sheepish, guilty, proud. Pose `brows.cock` is
-1..1, +1 raises the puppet's left brow. Cast accepts `holding: PROP, side: r`.
Dress accepts `hidden: true`. Shot `lights` is a list of {name, kind: point|spot|area,
at: TARGET, to?: TARGET, power: watts, color: "#RRGGBB", angle?: degrees, size?: metres}.
Sets accept `clutter: 0..1` (default .6). Held props follow the hand, not move beats.

A beat starts when the previous one ends, unless `t: seconds` (absolute time in the shot) or
`with: true`: start together with the latest beat that is not itself a `with` beat. A run of
`with` beats therefore all count their `delay` from that same beat:

    - {who: actor_a, do: hop}                      # the anchor
    - {sfx: pop, with: true, delay: 0.3}           # 0.3 s after the hop starts
    - {prop: crumbs, do: show, with: true, delay: 0.45}   # 0.45 s after the hop starts (not 0.75)
"""
from __future__ import annotations

import json
import math
import os
import sys
import time

if "STOPMO_SRC" in os.environ and os.environ["STOPMO_SRC"] not in sys.path:
    sys.path.insert(0, os.environ["STOPMO_SRC"])

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

from stopmo_bl import stage, style, util  # noqa: E402
from stopmo_bl.anim.shot import Shot  # noqa: E402
from stopmo_bl.archetypes import build as build_puppet  # noqa: E402
from stopmo_bl.materials.nodes import store_rest  # noqa: E402
from stopmo_bl.puppet import show_part  # noqa: E402


def studio_set(st, **params) -> dict:
    """Minimal built-in set: a floor and a back wall. Useful for tests and character sheets."""
    floor = util.rounded_box("floor", size=(2.4, 2.0, 0.02), location=(0, 0, -0.01), bevel=0.0)
    store_rest(floor)
    util.set_material(floor, st.material("floor", params.get("floor", "#8A5A33")))
    wall = util.rounded_box("wall", size=(2.4, 0.02, 1.2), location=(0, 0.45, 0.5), bevel=0.0)
    store_rest(wall)
    util.set_material(wall, st.material("wall", params.get("wall", "#9DB7A8")))
    return {
        "anchors": {"center": (0, 0, 0), "mark_a": (-0.12, 0, 0), "mark_b": (0.12, 0, 0)},
        "cameras": {
            "wide": {"from": (0.0, -1.05, 0.2), "to": (0, 0, 0.13), "lens": 50},
            "two_shot": {"from": (0.0, -0.78, 0.2), "to": (0, 0, 0.15), "lens": 50},
            "close_a": {"from": (-0.05, -0.5, 0.22), "to": (-0.12, 0, 0.2), "lens": 60},
            "close_b": {"from": (0.05, -0.5, 0.22), "to": (0.12, 0, 0.2), "lens": 60},
        },
        "light_rig": None,
        "props": {},
        "light_center": (0, 0, 0.15),
        "light_scale": 0.9,
    }


def title_card(st, spec: dict) -> dict:
    """Clay lettering on a painted card. Words pop on one at a time, like replacement animation.

    spec: {text: "Line one|Line two", subtitle?, url?, color?, sub_color?, url_color?, card?, size?}
    Lines wider than the card are shrunk to fit.
    """
    from mathutils import Matrix

    MAX_LINE = 0.56
    spec = {"text": spec} if isinstance(spec, str) else dict(spec)
    card = util.rounded_box("card", size=(1.6, 0.02, 1.0), location=(0, 0.06, 0.2), bevel=0.0)
    store_rest(card)
    util.set_material(card, st.material("wall", spec.get("card", "#2F4858")))
    floor = util.rounded_box("floor", size=(1.6, 1.0, 0.02), location=(0, -0.3, -0.01), bevel=0.0)
    store_rest(floor)
    util.set_material(floor, st.material("floor", spec.get("floor", "#8A5A33")))

    words = []  # (object, appear order)

    def line(text, size, z, color, role):
        made = []
        for word in text.split():
            curve = bpy.data.curves.new("w", "FONT")
            curve.body = word
            curve.size = size
            curve.extrude = size * 0.09
            curve.bevel_depth = size * 0.035
            curve.bevel_resolution = 3
            tmp = bpy.data.objects.new("w", curve)
            util.link(tmp)
            bpy.context.view_layer.update()
            deps = bpy.context.evaluated_depsgraph_get()
            mesh = bpy.data.meshes.new_from_object(tmp.evaluated_get(deps))
            bpy.data.objects.remove(tmp)
            obj = bpy.data.objects.new(f"word_{len(words) + len(made)}", mesh)
            util.link(obj)
            # stand the lettering up to face the camera, origin at its left baseline
            mesh.transform(Matrix.Rotation(math.radians(90), 4, "X"))
            util.shade_smooth(obj)
            if st.lumpiness > 0:
                util.lumpify(obj, size * 0.012 * st.lumpiness, size * 0.5, seed=word)
            store_rest(obj)
            util.set_material(obj, st.material(role, color))
            made.append(obj)
        gap = size * 0.32
        widths = [max(v.co.x for v in o.data.vertices) for o in made]
        total = sum(widths) + gap * (len(made) - 1)
        if total > MAX_LINE:  # shrink a long line (a web address) to fit the card
            k = MAX_LINE / total
            for o in made:
                o.data.transform(Matrix.Scale(k, 4))
            gap, widths = gap * k, [w * k for w in widths]
        x = -(sum(widths) + gap * (len(made) - 1)) / 2
        for obj, width in zip(made, widths):
            obj.location = (x, 0.05 - size * 0.1, z)  # pressed onto the card
            x += width + gap
            words.append(obj)

    lines = [t.strip() for t in spec["text"].split("|")]
    size = spec.get("size", 0.075 if max(len(t) for t in lines) <= 14 else 0.055)
    z = 0.2 + (len(lines) - 1) * size * 0.62 + (size * 0.35 if spec.get("subtitle") else 0) + (size * 0.3 if spec.get("url") else 0)
    for text in lines:
        line(text, size, z - size * 0.35, spec.get("color", "#F2C14E"), "cloth")
        z -= size * 1.25
    if spec.get("subtitle"):
        line(spec["subtitle"], size * 0.5, z - size * 0.1, spec.get("sub_color", "#F4F1E8"), "cloth")
        z -= size * 0.85
    if spec.get("url"):
        line(spec["url"], size * 0.34, z - size * 0.1, spec.get("url_color", spec.get("sub_color", "#F4F1E8")), "cloth")
    return {
        "anchors": {"center": (0, -0.2, 0)},
        "cameras": {"wide": {"from": (0.0, -0.9, 0.2), "to": (0, 0, 0.2), "lens": 50, "fstop": 8.0}},
        "light_rig": None,
        "props": {},
        "light_center": (0, -0.05, 0.2),
        "light_scale": 0.9,
        "words": words,
    }


def cyc_set(st, **params) -> dict:
    """Seamless backdrop: floor and back wall are one sheet that curves up, so there is no horizon line.
    `color` paints it; `depth` is where the curve starts (metres behind the centre), `cove` its radius."""
    depth, cove = float(params.get("depth", 0.3)), float(params.get("cove", 0.3))
    profile = [(-1.6, 0.0), (depth, 0.0)]
    profile += [(depth + cove * math.sin(a), cove * (1 - math.cos(a))) for a in [math.pi / 2 * i / 16 for i in range(1, 17)]]
    profile += [(depth + cove, 1.6)]
    verts = [(x, y, z) for x in (-1.8, 1.8) for y, z in profile]
    n = len(profile)
    faces = [(i, i + 1, n + i + 1, n + i) for i in range(n - 1)]
    mesh = bpy.data.meshes.new("backdrop")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    sheet = bpy.data.objects.new("backdrop", mesh)
    util.link(sheet)
    util.shade_smooth(sheet)
    store_rest(sheet)
    util.set_material(sheet, st.material("wall", params.get("color", "#FFF7EE")))
    return {
        "anchors": {"center": (0, 0, 0), "mark_a": (-0.12, 0, 0), "mark_b": (0.12, 0, 0)},
        "cameras": {
            "wide": {"from": (0.0, -1.05, 0.2), "to": (0, 0, 0.13), "lens": 50},
            "two_shot": {"from": (0.0, -0.78, 0.2), "to": (0, 0, 0.15), "lens": 50},
        },
        "light_rig": None,
        "props": {},
        "light_center": (0, 0, 0.1),
        "light_scale": 0.9,
    }


def build_set(spec, st, seed) -> dict:
    spec = {"kind": spec} if isinstance(spec, str) else dict(spec or {"kind": "studio"})
    kind = spec.pop("kind", "studio")
    if kind == "studio":
        return studio_set(st, **spec)
    if kind == "cyc":
        return cyc_set(st, **spec)
    from stopmo_bl import sets

    info = sets.build_set(kind, seed=seed, **spec)
    info.setdefault("light_center", info["anchors"].get("center", (0, 0, 0)))
    return info


class Director:
    def __init__(self, plan: dict):
        self.plan = plan
        self.spec = plan["shot"]
        self.scene = util.reset_scene()
        self.style = style.use(plan.get("style"))
        fps = float(self.style["fps"])
        stage.setup_render(
            self.scene,
            quality=plan.get("quality", "preview"),
            resolution=tuple(plan.get("resolution", (1920, 1080))),
            fps=int(fps),
            samples=plan.get("samples"),
        )
        self.shot = Shot(self.scene, self.style, seed=plan.get("seed", 0))
        self.audio: list[dict] = []
        self.sfx: list[dict] = []
        self.stats: dict = {}

    # ------------------------------------------------------------- setup ----
    def build(self) -> None:
        t = time.time()
        shot, spec = self.shot, self.spec
        if "title" in spec:
            info = title_card(self.style, spec["title"])
        else:
            info = build_set(spec.get("set"), self.style, self.plan.get("seed", 0))
        self.words = info.get("words", [])
        shot.anchors = {k: tuple(v) for k, v in info["anchors"].items()}
        shot.anchors.update({k: tuple(v) for k, v in spec.get("anchors", {}).items()})
        shot.cameras = info["cameras"]
        shot.props = dict(info.get("props", {}))
        self.dress(spec.get("dress", []))
        for prop in shot.props.values():
            if "visible_scale" not in prop:
                prop["visible_scale"] = tuple(prop.scale)
            shot.prop_track(prop)
        rig = spec.get("light_rig") or info.get("light_rig") or self.style["light_rig"]
        aim = spec.get("light_center", info.get("light_center", (0, 0, 0)))  # where the rig points: shot key or the set's
        center = Vector(shot.anchors[aim] if isinstance(aim, str) else aim)
        if center.z < 0.05:
            center.z = 0.14
        shot.lights = stage.light_rig(
            self.scene, rig, center=tuple(center), scale=info.get("light_scale", 1.0), power=spec.get("light_power", 1.0)
        )
        shot.rig_center, shot.rig_scale, shot.rig_power = tuple(center),info.get("light_scale",1.),spec.get("light_power",1.)
        self.stats["set_s"] = round(time.time() - t, 2)

        t = time.time()
        facing = {}
        for name, entry in spec.get("cast", {}).items():
            entry = entry or {}
            puppet = build_puppet(name, self.plan["characters"][name])
            at = entry.get("at", "center")
            pos = shot.anchors[at] if isinstance(at, str) else at
            perf = shot.add_performer(name, puppet, at=tuple(pos) if not isinstance(at, str) else (pos[0], pos[1]))
            facing[name] = entry.get("facing", "camera")
            perf.entry = entry
        shot.set_camera(1, spec.get("camera", "wide"))
        for name, target in facing.items():
            perf = shot.performers[name]
            if isinstance(target, (int, float)):
                heading = float(target)
            else:
                here = Vector(perf.place.value("pos", 1))
                d = shot.point(target, 1) - here
                heading = math.degrees(math.atan2(d.x, -d.y))
                # `open`: cheat the body toward the camera by this many degrees (stage blocking)
                c = shot.point("camera", 1) - here
                to_cam = (math.degrees(math.atan2(c.x, -c.y)) - heading + 180) % 360 - 180
                opened = float(perf.entry.get("open", 0.0))
                heading += max(-opened, min(opened, to_cam))
            perf.place.defaults["heading"] = heading
            if perf.entry.get("emote"):
                perf.emote(0, perf.entry["emote"], into=1)
            if perf.entry.get("look"):
                perf.look_at(1, perf.entry["look"])
            if perf.entry.get("pose"):
                perf.track.key(1, _pose(perf.entry["pose"]), "step")
            if perf.entry.get("holding"):
                prop = shot.props[perf.entry["holding"]]
                _grip_point(prop)
                perf.hold_prop(1,prop,perf.entry.get("side","r"))
        for item in spec.get("lights",[]):
            name = item["name"]
            if name in shot.lights:
                raise ValueError(f"duplicate/reserved light name {name!r}")
            shot.lights[name] = stage.practical_light(name,item.get("kind","point"),shot.point(item["at"]),
                shot.point(item.get("to",tuple(center))),power=float(item.get("power",1.)),
                color=item.get("color","#FFFFFF"),angle=float(item.get("angle",50.)),size=float(item.get("size",.02)))
        known = {o.name for o in shot.lights.values()}
        for obj in self.scene.objects:
            if obj.type == "LIGHT" and obj.name not in known:
                shot.lights[obj.name] = obj
        shot.init_lights()
        self.stats["cast_s"] = round(time.time() - t, 2)

    def dress(self, items: list) -> None:
        """Per-shot set dressing: move, remove or add props.

        {prop: name, at?: anchor | [x,y,z], offset?, scale?, turn?: degrees}   move / resize / turn a prop
        {prop: name, remove: true}                              take it off the set
        {add: kind, name, at, offset?, heading?, ...params}     build a new prop
        """
        shot = self.shot

        def where(item):
            at = item.get("at", (0, 0, 0))
            base = Vector(shot.anchors[at]) if isinstance(at, str) else Vector(at)
            return base + Vector(item.get("offset", (0, 0, 0)))

        for item in items:
            item = dict(item)
            if "add" in item:
                from stopmo_bl import props

                kind, name = item.pop("add"), item.pop("name", None)
                hidden = item.pop("hidden",False)
                at = tuple(where(item))
                for key in ("at", "offset"):
                    item.pop(key, None)
                prop = props.build_prop(kind, name, at=at, **item)
                shot.props[name or kind] = prop
                prop["visible_scale"] = tuple(prop.scale)
                if hidden:
                    prop.scale = tuple(v*1e-4 for v in prop.scale)
                continue
            prop = shot.props[item["prop"]]
            if item.get("remove"):
                prop["visible_scale"] = tuple(prop.scale)
                prop.scale = tuple(v*1e-4 for v in prop.scale)
            else:
                if "at" in item:
                    prop.location = where(item)
                if "scale" in item:
                    prop.scale = (item["scale"],) * 3
                if "turn" in item:  # degrees about the vertical axis
                    prop.rotation_euler.z = math.radians(item["turn"])
                prop["visible_scale"] = tuple(prop.scale)
                if item.get("hidden"):
                    prop.scale = tuple(v*1e-4 for v in prop.scale)
        bpy.context.view_layer.update()

    # ------------------------------------------------------------- beats ----
    def schedule(self) -> int:
        shot = self.shot
        fr = shot.frames
        cursor = 1 + fr(self.spec.get("lead", 0.3))
        speech_end = 0  # last exposure of the previous spoken line
        for i, word in enumerate(self.words):
            appear = cursor + i * 3
            show_part(word, False, appear - 1)  # a speck on the card until its turn
            for f, scale in ((appear, 1.22), (appear + 1, 0.95), (appear + 2, 1.0)):  # squashy pop
                word.scale = (scale, scale, scale)
                word.keyframe_insert("scale", frame=f)
            self.sfx.append({"kind": "pop", "frame": appear, "gain": 0.5, "seed": i})
        if self.words:
            cursor += len(self.words) * 3 + fr(self.spec.get("read", 1.6))
        anchor = cursor  # start of the latest beat that was not itself a `with` beat
        latest = cursor
        self.starts = []  # start exposure of every beat, in script order (for checks)
        for beat in self.spec.get("beats", []):
            if isinstance(beat.get("t"), (int, float)):
                start = 1 + fr(beat["t"])
            elif beat.get("with"):
                start = anchor  # several `with` beats in a row all count their delay from the same beat
            else:
                start = cursor
            start += fr(beat.get("delay", 0.0))
            if "say" in beat:  # leave a breath between lines, whoever speaks
                start = max(start, speech_end + fr(self.spec.get("line_gap", 0.25)))
            end = self.dispatch(beat, start)
            if "say" in beat:
                speech_end = start + beat["line"]["frames"]
            latest = max(latest, end)
            blocking = not beat.get("with") and "t" not in beat and "sfx" not in beat
            if "camera" in beat and not beat.get("wait_move"):
                blocking = False
            if blocking:
                cursor = max(cursor, end)
            if not beat.get("with"):
                anchor = start
            self.starts.append(start)
        return max(latest, cursor) + fr(self.spec.get("hold", 0.6))

    def dispatch(self, beat: dict, start: int) -> int:
        shot = self.shot
        fr = shot.frames
        if "wait" in beat:
            return start + fr(beat["wait"])
        if "sfx" in beat:
            self.sfx.append({"kind": beat["sfx"], "frame": start, "gain": beat.get("gain", 0.7), **({"pitch": beat["pitch"]} if beat.get("pitch") else {})})
            return start
        if "camera" in beat:
            move = fr(beat.get("move", 0.0))
            shot.set_camera(start, beat["camera"], move=move, ease=beat.get("ease", "inout"))
            return start + move
        if "shake" in beat and "who" not in beat:
            return shot.shake_camera(start,max(1,fr(beat.get("time",.4))),float(beat["shake"]))
        if "lights" in beat:
            if beat["lights"] == "flash":
                end = start+max(1,fr(beat.get("time",.17)))
                shot.flashes.append((start,end))
                return end
            return shot.change_rig(start,beat["lights"],fr(beat.get("over",0.)))
        if "light" in beat:
            if "scale" in beat:  # a share of the power the lamp was built with: 0 = off, 1 = as the set has it
                power = shot.light_tracks[beat["light"]].defaults["energy"] * float(beat["scale"])
            else:
                power = beat["power"]
            return shot.light_power(start,beat["light"],power,fr(beat.get("over",0.)))
        if "prop" in beat and "who" not in beat:
            return shot.prop_action(start,beat)
        if "say" in beat and beat["who"] not in shot.performers:  # off-screen voice
            line = beat["line"]
            self.audio.append({"wav": line["wav"], "frame": start, "gain": beat.get("gain", 0.9), "who": beat["who"]})
            return start + line["frames"]
        perf = shot.performers[beat["who"]]
        side = beat.get("side", "r")
        if "say" in beat:
            line = beat["line"]  # filled in by the host: {wav, frames, cues}
            self.audio.append({"wav": line["wav"], "frame": start, "gain": beat.get("gain", 1.0), "who": beat["who"]})
            if beat.get("emote"):
                perf.emote(start, beat["emote"])
            if "look" in beat:
                perf.look_at(start, beat["look"])
            end = perf.say(start, [tuple(c) for c in line["cues"]])
            end = max(end, start + line["frames"])
            if beat.get("gesture"):
                # hold through the line (at least a second), then relax as the next beat starts
                hold = max(int(self.shot.fps), end - start - 4)
                perf.gesture(start + 1, beat["gesture"], side=side, hold=hold)
                end = max(end, start + 1 + 3 + hold)
            return end
        do = beat["do"]
        if do == "startle":
            return perf.startle(start)
        if do == "double_take":
            return perf.double_take(start,beat["at"],stage=shot)
        if do == "shifty":
            return perf.shifty(start,times=beat.get("times",3))
        if do == "slump":
            return perf.slump(start)
        if do in ("tremble","chew"):
            return getattr(perf,do)(start,frames=max(2,fr(beat.get("time",1.))))
        if do == "sip":
            return perf.sip(start,frames=max(1,fr(beat.get("time",1.))),side=side)
        if do == "peer":
            return perf.peer(start,beat.get("at"))
        if do == "gesture":
            return perf.gesture(start, beat["name"], side=side, hold=fr(beat.get("hold", 0.8)))
        if do == "emote":
            return perf.emote(start, beat["name"])
        if do == "wave":
            return perf.wave(start, side=side, waves=beat.get("waves", 3))
        if do == "nod":
            return perf.nod(start, times=beat.get("times", 2))
        if do == "shake":
            return perf.shake(start, times=beat.get("times", 2))
        if do == "hop":
            end = perf.hop(start, height=beat.get("height", 0.14))
            toy = perf.puppet.archetype == "toy"  # a light figure lands with a tap, not a thump
            self.sfx.append({"kind": "tap" if toy else "thud", "frame": start + 6, "gain": 0.4 if toy else 0.5})
            return end
        if do == "lean":
            return perf.lean(start, pitch=beat.get("pitch", 12.0))
        if do == "look":
            perf.look_at(start, beat.get("at"))
            return start + 2
        if do == "hop_to":
            to = beat["to"]
            target = shot.anchors[to] if isinstance(to, str) and to in shot.anchors else tuple(shot.point(to, start))
            frames = beat.get("frames", 4)
            first = start
            end = perf.hop_to(start, target, hops=beat.get("hops"), hop=beat.get("hop", 0.5), height=beat.get("height", 0.3), frames=frames,
                              turn=beat.get("turn", True))
            hops = max(1, (end - first) // (frames + 2))
            for i in range(hops):
                self.sfx.append({"kind": "tap", "frame": end - (hops - 1 - i) * (frames + 2) - 1, "gain": 0.4, "seed": i})
            return end
        if do == "walk":
            to = beat["to"]
            target = shot.anchors[to] if isinstance(to, str) and to in shot.anchors else tuple(shot.point(to, start))
            step_frames = beat.get("step_frames", 4)
            end = perf.walk_to(start, target, step_frames=step_frames)
            for f in range(start + step_frames, end + 1, step_frames):
                self.sfx.append({"kind": "footstep", "frame": f, "gain": 0.45, "seed": f})
            return end
        if do == "face":
            return perf.face(start, tuple(shot.point(beat["to"], start)))
        if do == "turn":
            return perf.turn(start, beat["heading"])
        if do == "spin":   # a full turn on the spot (turns: how many), ending the way it faced
            return perf.turn(start, perf.place.value("heading", start) + 360 * beat.get("turns", 1), frames=max(4, fr(beat.get("time", 0.6))))
        if do == "reach":
            return perf.reach(start, shot.point(beat["to"], start), side=side, hold=fr(beat.get("hold", 0.5)))
        if do == "take":
            prop = shot.props[beat["prop"]]
            _grip_point(prop)
            grip = shot.prop_matrix(prop,start) @ (Vector(prop["grip"])/float(prop["visible_scale"][0]))
            end = perf.reach(start, grip, side=side, hold=2, release=True)
            perf.hold_prop(start + 5, prop, side)
            return end
        if do == "put":
            prop = shot.props[beat["prop"]]
            on = beat["onto"]
            point = shot.point(on,start)
            offset = Vector(shot.prop_track(prop).value("rotation_euler",start))
            from mathutils import Euler
            end = perf.reach(start, point + Euler(offset).to_matrix() @ _grip_offset(prop), side=side, hold=2, release=True)
            perf.hold_prop(start + 5, None, side)
            shot.prop_track(prop).hold(start+4,["location"])
            shot.prop_track(prop).key(start+5,{"location":tuple(point)},"step")
            return end
        if do == "pose":
            return perf.pose(start, _pose(beat["pose"]), into=max(1, fr(beat.get("over", 0.35))), ease=beat.get("ease", "inout"))
        raise KeyError(f"unknown action {do!r} in beat {beat}")

    # --------------------------------------------------------------- run ----
    def run(self, outdir: str) -> dict:
        self.build()
        last = self.schedule()
        t = time.time()
        self.shot.bake(1, last)
        self.stats["bake_s"] = round(time.time() - t, 2)
        frames = self.plan.get("frames")
        if frames == "none":
            render = {"frames": 0, "seconds": 0.0}
        else:
            if isinstance(frames, dict):  # {"every": n} and/or {"first": n}: a sample, or the opening n exposures
                stop = min(last, int(frames.get("first", last)))
                frames = list(range(1, stop + 1, int(frames.get("every", 1))))
            render = self.shot.render(os.path.join(outdir, "frames"), frames=frames)
        self.stats["render"] = render
        if self.plan.get("save_blend"):
            bpy.ops.wm.save_as_mainfile(filepath=os.path.join(outdir, "shot.blend"))
        timing = {
            "shot": self.spec.get("id"),
            "fps": self.shot.fps,
            "first": 1,
            "last": last,
            "frames": last,
            "audio": self.audio,
            "sfx": self.sfx,
            "stats": self.stats,
        }
        with open(os.path.join(outdir, "timing.json"), "w") as fh:
            json.dump(timing, fh, indent=1)
        return timing


def _pose(pose: dict) -> dict:
    """YAML gives lists; pose channels want tuples."""
    return {k: tuple(v) if isinstance(v, list) else v for k, v in pose.items()}


def _grip_offset(prop) -> Vector:
    anchors = prop.get("anchors")
    if anchors:
        for name in ("handle", "grip", "top"):
            if name in anchors:
                return Vector(anchors[name]) * float(prop.get("visible_scale",prop.scale)[0])
    return Vector((0, 0, 0))


def _grip_point(prop) -> Vector:
    offset = _grip_offset(prop)
    prop["grip"] = tuple(offset)
    return prop.matrix_world.translation + prop.rotation_euler.to_matrix() @ offset


if __name__ == "__main__":
    plan_path = sys.argv[sys.argv.index("--") + 1]
    with open(plan_path) as fh:
        plan = json.load(fh)
    out = os.path.dirname(os.path.abspath(plan_path))
    result = Director(plan).run(out)
    print("STOPMO_TIMING", json.dumps({"frames": result["frames"], "stats": result["stats"]}))
