"""Pose tracks are pure Python (no bpy), so they are tested on the host."""
import importlib.util
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "stopmo_bl" / "anim" / "track.py"
spec = importlib.util.spec_from_file_location("track", SRC)
track = importlib.util.module_from_spec(spec)
sys.modules["track"] = track
spec.loader.exec_module(track)


def test_channels_are_independent():
    t = track.Track({"a": 0.0, "b": (0.0, 0.0), "lids": "open"})
    t.key(10, {"a": 10.0}, "linear")
    t.key(20, {"b": (2.0, 4.0)}, "linear")
    assert t.value("a", 10) == 10.0 and t.value("a", 50) == 10.0
    assert t.value("b", 5) == (0.0, 0.0)          # still at its default: only eases in near its key
    assert t.value("b", 20) == (2.0, 4.0)
    assert t.value("lids", 15) == "open"


def test_interpolates_between_keys_and_strings_switch():
    t = track.Track({"a": 0.0, "lids": "open"})
    t.key(0, {"a": 0.0}, "linear")
    t.key(10, {"a": 10.0, "lids": "closed"}, "linear")
    assert abs(t.value("a", 5) - 5.0) < 1e-9
    t.key(0, {"lids": "open"})
    assert t.value("lids", 9) == "open" and t.value("lids", 10) == "closed"


def test_hold_pins_current_value():
    t = track.Track({"a": 0.0})
    t.key(0, {"a": 0.0}, "linear")
    t.key(10, {"a": 10.0}, "linear")
    t.hold(20, ["a"])
    t.key(30, {"a": 0.0}, "linear")
    assert t.value("a", 20) == 10.0 and abs(t.value("a", 25) - 5.0) < 1e-9


def test_snap_overshoots_then_settles():
    snap = track.EASES["snap"]
    assert abs(snap(0.0)) < 1e-9 and abs(snap(1.0) - 1.0) < 1e-9
    assert max(snap(i / 20) for i in range(21)) > 1.02


def test_jitter_is_deterministic_and_small():
    pose = {"head.yaw": 0.0, "arm_l.at": (0.2, 0.1, -0.9), "lids": "open"}
    a = track.jitter(pose, "seed/1", 1.0)
    assert a == track.jitter(pose, "seed/1", 1.0) != track.jitter(pose, "seed/2", 1.0)
    assert abs(a["head.yaw"]) < 3.0 and a["lids"] == "open"
    assert track.jitter(pose, "x", 0.0) == pose


def test_add_poses():
    out = track.add_poses({"a": 1.0, "b": (1.0, 2.0), "s": "x"}, {"a": 0.5, "b": (1.0, 1.0), "s": 3, "zz": 1})
    assert out == {"a": 1.5, "b": (2.0, 3.0), "s": "x"}


def test_jitter_holds_its_offset_while_the_pose_is_held():
    state = {}
    held = {"head.yaw": 10.0, "arm_l.at": (0.2, 0.1, -0.9)}
    first = track.jitter(held, "s/1", 1.0, state)
    second = track.jitter(held, "s/2", 1.0, state)
    assert second == first                                    # nothing moved: nothing re-randomised
    moved = track.jitter({**held, "head.yaw": 12.0}, "s/3", 1.0, state)
    assert moved["arm_l.at"] == first["arm_l.at"]             # the arm was not touched
    assert moved["head.yaw"] - 12.0 != first["head.yaw"] - 10.0   # the head was: a new error
    assert abs(moved["head.yaw"] - 12.0) < 3.0
    again = track.jitter({**held, "head.yaw": 12.0}, "s/4", 1.0, state)
    assert again == moved
