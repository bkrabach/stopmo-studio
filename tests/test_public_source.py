"""Source-release boundaries; no Blender, model downloads, or media rendering required."""
import ast
import base64
from html import escape
import json
from pathlib import Path
import runpy
import subprocess
import sys
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIGURE = ROOT / "src" / "stopmo_bl" / "archetypes" / "figure.py"


def figure_loader():
    """Load only the actual pure-Python loader, without mocking Blender's geometry API."""
    source = ast.parse(FIGURE.read_text())
    nodes = []
    for node in source.body:
        if isinstance(node, ast.Import) and all(alias.name != "bpy" for alias in node.names):
            nodes.append(node)
        elif isinstance(node, ast.ImportFrom) and node.module in {"__future__", "pathlib", "types"}:
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "MODELS" for target in node.targets
        ):
            nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name == "_build_model":
            nodes.append(node)
    namespace = {"__file__": str(FIGURE)}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(FIGURE), "exec"), namespace)
    return namespace


def test_models_folder_is_at_repository_root():
    assert figure_loader()["MODELS"] == ROOT / "models"


def test_only_public_stage_presets_are_registered():
    source = ast.parse((ROOT / "src" / "stopmo_bl" / "sets.py").read_text())
    registrations = [
        node for node in ast.walk(source)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "SETS" and node.func.attr == "update"
    ]
    assert len(registrations) == 1
    assert {item.arg for item in registrations[0].keywords} == {"kitchen", "workshop", "garden"}
    # No excluded room implementation should remain merely unregistered.
    assert {node.name for node in source.body if isinstance(node, ast.FunctionDef)} == {
        "_root", "_surface", "_box_surface", "_pattern", "_window", "room", "_cameras",
        "kitchen", "workshop", "_backdrop", "garden", "build_set",
    }


def test_model_loader_isolates_basenames_and_sibling_imports(tmp_path, monkeypatch):
    models = tmp_path / "models"
    namespace = figure_loader()
    namespace["MODELS"] = models
    old_common, old_child, old_hero = ModuleType("common"), ModuleType("common.child"), ModuleType("hero")
    monkeypatch.setitem(sys.modules, "common", old_common)
    monkeypatch.setitem(sys.modules, "common.child", old_child)
    monkeypatch.setitem(sys.modules, "hero", old_hero)
    original_path = sys.path[:]
    original_namespaces = {name for name in sys.modules if name.startswith("_stopmo_model_")}
    for value in ("cast_a", "cast_b"):
        folder = models / value
        folder.mkdir(parents=True)
        (folder / "common.py").write_text(f"VALUE = {value!r}\n")
        (folder / "helper.py").write_text("from .common import VALUE\n")
        (folder / "hero.py").write_text(
            "import common\nfrom . import helper\n"
            "def build():\n    import common\n    return common.VALUE, helper.VALUE\n"
        )
        assert namespace["_build_model"](value + "/hero") == (value, value)
        assert sys.modules["common"] is old_common
        assert sys.modules["common.child"] is old_child
        assert sys.modules["hero"] is old_hero
        assert sys.path == original_path
        assert {name for name in sys.modules if name.startswith("_stopmo_model_")} == original_namespaces


@pytest.mark.parametrize("model", ["", "../outside", "/outside", "cast/../hero", "cast/hero.py",
                                  "cast//hero", "cast\\hero", None, 12])
def test_model_loader_rejects_nonrelative_module_paths(tmp_path, model):
    namespace = figure_loader()
    namespace["MODELS"] = tmp_path / "models"
    with pytest.raises(ValueError):
        namespace["_build_model"](model)


def test_model_loader_rejects_symlink_escape(tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("raise RuntimeError('must not execute')\n")
    (models / "linked.py").symlink_to(outside)
    namespace = figure_loader()
    namespace["MODELS"] = models
    with pytest.raises(ValueError, match="inside models"):
        namespace["_build_model"]("linked")


def test_model_loader_restores_import_state_on_build_failure(tmp_path, monkeypatch):
    models = tmp_path / "models"
    models.mkdir()
    (models / "common.py").write_text("VALUE = 1\n")
    (models / "broken.py").write_text(
        "import common\n"
        "def build():\n    raise RuntimeError('synthetic failure')\n"
    )
    namespace = figure_loader()
    namespace["MODELS"] = models
    old_common = ModuleType("common")
    monkeypatch.setitem(sys.modules, "common", old_common)
    original_path = sys.path[:]
    with pytest.raises(RuntimeError, match="synthetic failure"):
        namespace["_build_model"]("broken")
    assert sys.modules["common"] is old_common
    assert sys.path == original_path
    with pytest.raises(FileNotFoundError):
        namespace["_build_model"]("missing")


@pytest.mark.parametrize("checked", [False, True])
def test_review_page_escapes_metadata_and_omits_video_directory(tmp_path, monkeypatch, checked):
    build = tmp_path / "build"
    build.mkdir()
    video = tmp_path / "private_directory" / 'clip<&".mp4'
    metadata = {
        "show": '<script>alert("title")</script>',
        "episode": 'Episode & "one"',
        "quality": "<b>preview</b>",
        "seconds_of_film": "<img src=x onerror=alert(1)>",
        "exposures": "<em>24</em>",
    }
    summary = {**metadata, "video": str(video),
               "shots": [{"render": {"seconds": 120}}], "sound": {}}
    (build / "summary.json").write_text(json.dumps(summary))
    if checked:
        (build / "render_check.json").write_text(json.dumps([{"checked": 12, "repaired": []}]))
    # Synthetic bytes exercise HTML assembly, not codecs or any private film.
    payload = b"synthetic review bytes"
    calls = []

    def fake_run(args, *, check):
        assert check
        calls.append(args)
        Path(args[-1]).write_bytes(payload)

    audio = ModuleType("stopmo.audio")
    audio._ffmpeg = lambda: "synthetic-ffmpeg"
    monkeypatch.setitem(sys.modules, "stopmo.audio", audio)
    monkeypatch.setattr(subprocess, "run", fake_run)
    output = tmp_path / "review.html"
    monkeypatch.setattr(sys, "argv", ["review_page.py", str(output), str(build)])
    monkeypatch.setattr(sys, "path", sys.path[:])
    runpy.run_path(str(ROOT / "tools" / "review_page.py"), run_name="__main__")
    html = output.read_text()
    assert len(calls) == 1 and str(video) in calls[0]
    assert str(video.parent) not in html and "private_directory" not in html
    assert escape(video.name) in html
    for value in metadata.values():
        assert escape(value) in html
        assert value not in html
    assert base64.b64encode(payload).decode() in html
    assert "API cost $0" not in html
    assert ("Render check recorded:" if checked else "Render check unavailable:") in html
    assert "Sound not measured" in html
    assert "Nobody has watched" not in html