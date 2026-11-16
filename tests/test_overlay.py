import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from stopmo import overlay

FONT = next((p for p in [
    os.environ.get("STOPMO_TEST_FONT", ""),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Georgia.ttf",
] if p and Path(p).is_file()), "")


def test_opacity_fades_in_quickly_and_out_slowly():
    item = {"fade_in": [1.0, 2.0], "fade_out": [3.0, 4.0]}
    assert overlay.opacity(item, 0.5) == 0 and overlay.opacity(item, 2.5) == 1 and overlay.opacity(item, 4.5) == 0
    assert overlay.opacity(item, 1.5) == pytest.approx(0.75)   # most of the way in by half time
    assert overlay.opacity(item, 3.5) == pytest.approx(0.75)   # and still mostly there half way out
    assert overlay.opacity({"opacity": 0.5}, 9.0) == 0.5


@pytest.mark.skipif(not FONT, reason="set STOPMO_TEST_FONT to a licensed system TTF")
def test_line_lands_where_it_is_asked_and_untouched_frames_are_kept(tmp_path):
    frames = tmp_path / "frames"
    frames.mkdir()
    for n in (1, 2, 3):
        Image.new("RGB", (400, 200), (20, 20, 20)).save(frames / f"f_{n:05d}.png")
    item = {"text": "Team", "font": FONT, "at": [0.1, 0.2], "width": 0.5, "color": "#FFFFFF", "fade_in": [0.9, 1.0]}
    out = overlay.apply(frames, tmp_path / "titled", [item], fps=1.0)
    first = np.asarray(Image.open(out / "f_00001.png"))
    assert first.max() == 20                                    # before the fade: nothing drawn
    last = np.asarray(Image.open(out / "f_00003.png").convert("L"))
    ys, xs = np.where(last > 128)
    assert abs(xs.min() - 40) <= 1 and abs(xs.max() - 239) <= 2  # left edge at 0.1, ink 0.5 of the width
    assert abs(ys.min() - 40) <= 1


def test_pop_springs_in_and_settles():
    item = {"pop": [1.0, 1.5]}
    assert overlay.pop_scale(item, 0.9) == 0.0
    assert overlay.pop_scale(item, 1.35) > 1.0          # overshoot on the way
    assert overlay.pop_scale(item, 2.0) == pytest.approx(1.0)
    assert overlay.pop_scale({}, 0.0) == 1.0


@pytest.mark.skipif(not FONT, reason="set STOPMO_TEST_FONT to a licensed system TTF")
def test_plate_and_centre(tmp_path):
    frames = tmp_path / "frames"
    frames.mkdir()
    Image.new("RGB", (400, 200), (20, 20, 20)).save(frames / "f_00001.png")
    item = {"text": "Label", "font": FONT, "center": [0.5, 0.5], "width": 0.2, "color": "#000000", "plate": {"color": "#FFFFFF"}}
    out = overlay.apply(frames, tmp_path / "titled", [item], fps=12.0)
    a = np.asarray(Image.open(out / "f_00001.png").convert("L"))
    ys, xs = np.where(a > 200)                             # the white plate
    assert abs((xs.min() + xs.max()) / 2 - 200) <= 2 and abs((ys.min() + ys.max()) / 2 - 100) <= 2
    assert xs.max() - xs.min() > 80                        # wider than the ink it carries
    assert a[100, 185:215].min() < 80                      # dark lettering on it
