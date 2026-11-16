"""Numeric check of the clay 'boil' dial:  tools/bl.sh tools/check_boil.py [outdir]

Renders a motionless clay swatch on consecutive exposures at several boil levels (fixed lights,
camera and render seed) and measures two things per level:
  change  mean absolute pixel difference between consecutive exposures (the flicker)
  detail  mean absolute image gradient (how much texture there is)
Passes when change is ~0 at boil 0, rises with every level, and detail stays within 15% of full.
"""
import os
import sys

sys.path.insert(0, os.environ["STOPMO_SRC"])
import bpy
import numpy as np

from stopmo_bl import stage, util
from stopmo_bl.materials import library as M
from stopmo_bl.materials.nodes import store_rest

args = sys.argv[sys.argv.index("--") + 1:]
outdir = args[0] if args else os.path.join(os.path.dirname(os.environ["STOPMO_SRC"]), "out", "check_boil")
os.makedirs(outdir, exist_ok=True)
LEVELS = [0.0, 0.15, 0.3, 0.5, 0.75, 1.0]
FRAMES = [1, 2, 3, 4]


def load(path):
    img = bpy.data.images.load(path)
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    return px.reshape(h, w, 4)[:, :, :3].mean(axis=2)


rows = []
for level in LEVELS:
    scene = util.reset_scene()
    stage.setup_render(scene, quality="preview", resolution=(640, 360), samples=48)
    table = util.rounded_box("table", size=(1.2, 0.8, 0.02), location=(0, 0, -0.01), bevel=0.2)
    store_rest(table)
    util.set_material(table, M.matte("table", "#6E6A62"))
    for i, colour in enumerate(["#E8B08A", "#5E8C4A", "#C2452D"]):
        ball = util.ellipsoid(f"ball{i}", radii=(0.035, 0.035, 0.033), location=((i - 1) * 0.085, 0, 0.033), subdiv=4)
        util.lumpify(ball, 0.0015, 0.02, seed=i)
        store_rest(ball)
        util.set_material(ball, M.clay(f"clay{i}", colour, boil=level))
    stage.light_rig(scene, "cosy", center=(0, 0, 0.03), scale=0.6)
    stage.add_camera(scene, (0.0, -0.3, 0.1), (0, 0, 0.03), lens=60, fstop=11)
    images = []
    for frame in FRAMES:
        scene.frame_set(frame)
        scene.render.filepath = os.path.join(outdir, f"boil_{level:.2f}_f{frame}.png")
        bpy.ops.render.render(write_still=True)
        images.append(load(scene.render.filepath))
    change = float(np.mean([np.abs(b - a).mean() for a, b in zip(images, images[1:])]))
    detail = float(np.mean([np.abs(np.diff(im, axis=0)).mean() + np.abs(np.diff(im, axis=1)).mean() for im in images]))
    rows.append((level, change, detail))

full_change, full_detail = rows[-1][1], rows[-1][2]
print("BOIL  level  change(x1e3)  % of full flicker  detail vs full")
for level, change, detail in rows:
    print(f"BOIL  {level:4.2f}   {change * 1e3:8.3f}      {100 * change / full_change:6.1f}%          {100 * detail / full_detail:6.1f}%")
problems = []
if rows[0][1] > 0.03 * full_change:
    problems.append("boil 0 still flickers")
if any(b[1] <= a[1] for a, b in zip(rows, rows[1:])):
    problems.append("flicker does not rise with every level")
if any(abs(detail / full_detail - 1.0) > 0.15 for _, _, detail in rows):
    problems.append("amount of texture changes with the level")
print("BOIL_CHECK", "PASS" if not problems else "FAIL: " + "; ".join(problems))
sys.exit(1 if problems else 0)
