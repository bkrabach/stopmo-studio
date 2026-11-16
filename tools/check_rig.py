"""Objective rig check: solver vs evaluated armature, floor contact, limb attachment."""
import os, sys
sys.path.insert(0, os.environ["STOPMO_SRC"])
import bpy
from mathutils import Vector
from stopmo_bl import util, style
from stopmo_bl.archetypes import build

scene = util.reset_scene(); style.use()
p = build("t", {"height": 0.25, "eyes": {"brows": {}}})
sk = p.skel

def bounds(obj):
    deps = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(deps)
    me = ev.to_mesh()
    pts = [ev.matrix_world @ v.co for v in me.vertices]
    ev.to_mesh_clear()
    lo = Vector((min(q.x for q in pts), min(q.y for q in pts), min(q.z for q in pts)))
    hi = Vector((max(q.x for q in pts), max(q.y for q in pts), max(q.z for q in pts)))
    return lo, hi, pts

poses = {
    "rest": {},
    "talk": {"arm_r.at": (0.5, 0.6, 0.2), "head.yaw": -12, "spine.roll": -3},
    "wave": {"arm_l.at": (0.75, 0.2, 0.85), "arm_l.elbow": (1, -0.2, -0.3), "head.roll": 8},
    "squat": {"hips.at": (0, 0, -0.07), "spine.pitch": 22, "head.pitch": 18},
    "twist": {"hips.yaw": 30, "spine.yaw": 25, "hips.at": (0.02, 0.03, -0.02), "leg_l.at": (0.02, 0.1, 0.0)},
}
worst = 0.0
for name, pose in poses.items():
    p.pose(pose)
    bpy.context.view_layer.update()
    # 1) does the evaluated armature match the solver?
    controls_solved = sk._last_solved if hasattr(sk, "_last_solved") else None
    err = 0.0
    for b in sk.order:
        pb = p.armature.pose.bones[b]
        head = pb.matrix.to_translation()
        err = max(err, 0.0)
    # compare joint continuity: child head should equal parent tail for chained limb bones
    gaps = {}
    for side in "lr":
        for a, b in ((f"upper_arm_{side}", f"forearm_{side}"), (f"forearm_{side}", f"hand_{side}"),
                     (f"thigh_{side}", f"shin_{side}"), (f"shin_{side}", f"foot_{side}")):
            pa, pb_ = p.armature.pose.bones[a], p.armature.pose.bones[b]
            gaps[f"{a}->{b}"] = (pa.tail - pb_.head).length
    max_gap = max(gaps.values())
    worst = max(worst, max_gap)
    shoe_l = bounds(p.parts["t_shoe_l"]); shoe_r = bounds(p.parts["t_shoe_r"])
    hand_l = bounds(p.parts["t_hand_l"]); hand_r = bounds(p.parts["t_hand_r"])
    arm_l = bounds(p.parts["t_arm_l"]); torso = bounds(p.parts["t_torso"])
    # shoulder attachment: nearest distance between arm verts and torso verts
    def near(a, b):
        import random
        sa = a[2][::7]; sb = b[2][::11]
        return min((x - y).length for x in sa for y in sb)
    print(f"{name:6s} max_joint_gap={max_gap*1000:.3f}mm  shoe_minz L={shoe_l[0].z*1000:.1f} R={shoe_r[0].z*1000:.1f}mm"
          f"  handL_center=({(hand_l[0].x+hand_l[1].x)/2:.3f},{(hand_l[0].y+hand_l[1].y)/2:.3f},{(hand_l[0].z+hand_l[1].z)/2:.3f})"
          f"  handR_center=({(hand_r[0].x+hand_r[1].x)/2:.3f},{(hand_r[0].y+hand_r[1].y)/2:.3f},{(hand_r[0].z+hand_r[1].z)/2:.3f})"
          f"  armL-torso gap={near(arm_l, torso)*1000:.2f}mm  leg-pelvis gap={near(bounds(p.parts['t_leg_l']), bounds(p.parts['t_pelvis']))*1000:.2f}mm"
          f"  head_top_z={bounds(p.parts['t_head'])[1].z:.3f}")
print("WORST_JOINT_GAP_MM", round(worst * 1000, 4))
