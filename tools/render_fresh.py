"""Blender side of tools/check_render.py: render a plan's listed exposures with nothing carried over
between frames (Cycles persistent data off), as the reference for comparison.

    tools/bl.sh tools/render_fresh.py plan.json
"""
import json
import os
import sys

sys.path.insert(0, os.environ["STOPMO_SRC"])
from stopmo_bl.director import Director  # noqa: E402

path = sys.argv[sys.argv.index("--") + 1]
director = Director(json.load(open(path)))
director.scene.render.use_persistent_data = False
result = director.run(os.path.dirname(os.path.abspath(path)))
print("STOPMO_TIMING", json.dumps({"frames": result["frames"], "stats": result["stats"]}))
