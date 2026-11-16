"""The render checker must never report success for zero coverage."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest
from PIL import Image

spec = importlib.util.spec_from_file_location("check_render", Path(__file__).parents[1] / "tools/check_render.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def test_empty_build_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["check_render.py", str(tmp_path)])
    with pytest.raises(SystemExit) as exc:
        checker.main()
    assert exc.value.code == 2
    assert not (tmp_path / "render_check.json").exists()


def test_nonpositive_interval_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["check_render.py", str(tmp_path), "--every", "0"])
    with pytest.raises(SystemExit) as exc:
        checker.main()
    assert exc.value.code == 2


def test_short_shot_always_has_coverage(tmp_path, monkeypatch):
    (tmp_path / "plan.json").write_text("{}")
    (tmp_path / "timing.json").write_text(json.dumps({"frames": 1}))
    (tmp_path / "frames").mkdir()
    Image.new("RGB", (4, 4), "red").save(tmp_path / "frames/f_00001.png")
    def fake_render(plan, frames, work):
        assert frames == [1]
        (work / "frames").mkdir(parents=True)
        Image.new("RGB", (4, 4), "red").save(work / "frames/f_00001.png")
    monkeypatch.setattr(checker, "render", fake_render)
    result = checker.check(tmp_path, every=8, repair=False)
    assert result["checked"] == result["total"] == 1
    assert not result["differ"]
