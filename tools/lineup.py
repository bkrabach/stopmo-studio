"""Line a show's characters up on a plain set and render one picture: a quick look at the models.

    .venv/bin/stopmo lineup SHOW_DIR OUT.png [NAME ...]      (all characters with a body if no names)

Runs inside Blender; the command above writes the show as JSON and calls it.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.environ["STOPMO_SRC"])
import bpy  # noqa: E402

from stopmo_bl import stage, style, util  # noqa: E402
from stopmo_bl.archetypes import build  # noqa: E402
from stopmo_bl.director import build_set  # noqa: E402

args = sys.argv[sys.argv.index("--") + 1:]
show, out, names = json.loads(Path(args[0]).read_text()), args[1], args[2:]
spec = show["style"]
scene = util.reset_scene()
st = style.use(spec)
stage.setup_render(scene, quality="preview", resolution=(1920, 1080))
backdrop = show.get("set") or "studio"
if not (isinstance(backdrop, dict) and backdrop.get("kind") in ("studio", "cyc")):
    backdrop = "studio"   # a furnished room would hide the line-up: use the plain stage
info = build_set(backdrop, st, 0)
specs = show["characters"]
specs = {n: s for n, s in specs.items() if s.get("archetype") and (not names or n in names)}
gap = 1.25 * max(s.get("height", 0.25) for s in specs.values()) * (0.75 if all(s.get("archetype") == "toy" for s in specs.values()) else 0.55)
tall = max(s.get("height", 0.25) for s in specs.values())
for i, (name, s) in enumerate(specs.items()):
    puppet = build(name, s)
    puppet.place(((i - (len(specs) - 1) / 2) * gap, 0.0, 0.0), 0.0)
    puppet.pose({})
stage.light_rig(scene, st["light_rig"], center=(0, 0, tall / 2), scale=0.9)
width = max(len(specs) * gap, tall * 1.5)
stage.add_camera(scene, (0.0, -width * 1.5 - 0.1, tall * 0.7), (0, 0, tall * 0.5), lens=50, fstop=11)
scene.render.filepath = out
bpy.ops.render.render(write_still=True)
