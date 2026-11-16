import json
from pathlib import Path
import subprocess
import sys

from click.testing import CliRunner
import pytest
import yaml

from stopmo import audio, build, lipsync, setup, sweep, transcribe
from stopmo.cli import main


@pytest.fixture
def ready_doctor(tmp_path, monkeypatch):
    root = tmp_path / "checkout"
    for relative in setup.CHECKOUT_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder")
    monkeypatch.setattr(setup, "ROOT", root)
    monkeypatch.setattr(setup, "blender_executable", lambda: "blender")
    monkeypatch.setattr(audio, "_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(audio, "kokoro_available", lambda: False)
    monkeypatch.setattr(audio, "acting_available", lambda: False)
    monkeypatch.setattr(lipsync, "_rhubarb", lambda: None)
    monkeypatch.setattr(transcribe, "available", lambda: False)

    def probe(args, **kwargs):
        if args == ["blender", "--version"]:
            return "Blender 5.0.0\nbuild metadata not for disclosure"
        if args == ["ffmpeg", "-hide_banner", "-encoders"]:
            return " V....D libx264 text\n A..... aac text\n A....D pcm_s16le text\n"
        raise AssertionError(f"Unexpected probe: {args}")

    monkeypatch.setattr(setup, "_probe", probe)
    return root


def test_doctor_optional_absence_is_not_fatal_and_report_is_bounded(ready_doctor, monkeypatch):
    monkeypatch.setenv("PRIVATE_TEST_VARIABLE", "do-not-print-this")
    before = sorted(p.relative_to(ready_doctor) for p in ready_doctor.rglob("*"))
    report = setup.doctor()
    assert report["ok"]
    assert not any(c["ok"] for c in report["checks"] if not c["required"])
    output = json.dumps(report)
    assert "do-not-print-this" not in output and str(ready_doctor) not in output
    assert "build metadata" not in output
    assert before == sorted(p.relative_to(ready_doctor) for p in ready_doctor.rglob("*"))


def test_doctor_missing_checkout_is_actionable_and_cli_fails(ready_doctor):
    (ready_doctor / "styles/clay.yaml").unlink()
    result = CliRunner().invoke(main, ["doctor", "--json"])
    assert result.exit_code == 1
    report = json.loads(result.output)
    check = next(c for c in report["checks"] if c["name"] == "checkout")
    assert not check["ok"] and "editable install" in check["fix"]
    assert "styles/clay.yaml" in check["detail"]


@pytest.mark.parametrize("version", ["Blender 4.3.2", "unrecognizable", None])
def test_doctor_fails_for_unsupported_or_missing_blender(ready_doctor, monkeypatch, version):
    old_probe = setup._probe
    monkeypatch.setattr(setup, "_probe", lambda args, **kw:
                        version if args[0] == "blender" else old_probe(args, **kw))
    assert not setup.doctor()["ok"]


def test_doctor_rejects_ffmpeg_without_required_encoders(ready_doctor, monkeypatch):
    old_probe = setup._probe
    monkeypatch.setattr(setup, "_probe", lambda args, **kw:
                        " V....D libx264 H.264\n" if args[0] == "ffmpeg" else old_probe(args, **kw))
    report = setup.doctor()
    check = next(c for c in report["checks"] if c["name"] == "ffmpeg")
    assert not report["ok"] and not check["ok"]
    assert "aac" in check["detail"] and "pcm_s16le" in check["detail"]


def test_doctor_probe_handles_os_error_and_timeout(monkeypatch):
    for error in (OSError("cannot run"), subprocess.TimeoutExpired("probe", 1)):
        def fail(*a, **kw):
            raise error
        monkeypatch.setattr(subprocess, "run", fail)
        assert setup._probe(["not-an-executable"]) is None


def test_blender_resolves_path_or_explicit_executable(monkeypatch):
    requests = []
    monkeypatch.setattr(setup.shutil, "which", lambda value: requests.append(value) or f"/tools/{value}")
    monkeypatch.delenv("BLENDER", raising=False)
    assert setup.blender_executable() == "/tools/blender"
    monkeypatch.setenv("BLENDER", "custom-blender")
    assert setup.blender_executable() == "/tools/custom-blender"
    assert requests == ["blender", "custom-blender"]
    monkeypatch.setattr(setup.shutil, "which", lambda value: None)
    with pytest.raises(RuntimeError, match="Blender not found"):
        setup.blender_executable()


def test_init_new_generic_project(tmp_path):
    path = setup.init_project(tmp_path / "my-film")
    assert sorted(str(p.relative_to(path)) for p in path.rglob("*") if p.is_file()) == [
        ".gitignore", "characters/hero.yaml", "episodes/hello.yaml", "show.yaml"]
    show = build.load_show(path)
    ep = build.load_episode(show, "hello")
    assert show["characters"]["hero"]["archetype"] == "toy"
    assert show["music"]["style"] == "marimba"
    assert build.say_beats(ep["shots"]) == []
    assert "voice" not in show["characters"]["hero"]
    shot = ep["shots"][0]
    assert shot["lead"] == shot["hold"] == 0
    assert 1 + round(shot["beats"][0]["wait"] * 12) == 24
    assert any(b.get("do") == "hop" for b in shot["beats"])
    assert any(b.get("sfx") == "pop" for b in shot["beats"])
    assert "*" in (path / ".gitignore").read_text()


@pytest.mark.parametrize("existing", ["directory", "file", "symlink", "dangling"])
def test_init_never_overwrites(tmp_path, existing):
    path = tmp_path / "existing"
    target = tmp_path / "target"
    target.mkdir()
    (target / "keep").write_text("keep")
    if existing == "directory":
        path.mkdir()
        (path / "keep").write_text("keep")
    elif existing == "file":
        path.write_text("keep")
    else:
        path.symlink_to(target if existing == "symlink" else tmp_path / "missing")
    with pytest.raises(FileExistsError):
        setup.init_project(path)
    assert (target / "keep").read_text() == "keep"
    assert not (target / "show.yaml").exists()


@pytest.mark.parametrize("name", ["../escape", "nested/../../escape", "bad name", ".hidden", "CON", "name."])
def test_init_rejects_unsafe_name_before_writing(tmp_path, name):
    with pytest.raises(ValueError):
        setup.init_project(tmp_path / name)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("name", ["../escape", "/absolute", r"..\escape", ".", "..", "", "two/parts"])
def test_component_rejects_paths(name):
    with pytest.raises(ValueError):
        setup.safe_component(name)


def test_build_rejects_output_traversal_before_render(tmp_path, monkeypatch):
    project = setup.init_project(tmp_path / "film")
    monkeypatch.setattr(build, "render_shot", lambda *a, **kw: pytest.fail("must not render"))
    for kwargs in ({"tag": "../../escape"}, {"quality": "../escape"}):
        with pytest.raises(ValueError):
            build.build_episode(project, "hello", out_root=tmp_path / "out", **kwargs)
    with pytest.raises(ValueError):
        build.build_episode(project, "../hello", out_root=tmp_path / "out")
    episode_path = project / "episodes/hello.yaml"
    ep = yaml.safe_load(episode_path.read_text())
    ep["shots"][0]["id"] = "../escape"
    episode_path.write_text(yaml.safe_dump(ep))
    with pytest.raises(ValueError):
        build.build_episode(project, "hello", out_root=tmp_path / "out")
    assert not (tmp_path / "out").exists()
    with pytest.raises(ValueError):
        sweep.label("boil", "../../escape")


def test_configured_acting_never_silently_substitutes_kokoro(monkeypatch):
    monkeypatch.setattr(audio, "acting_available", lambda: False)
    monkeypatch.setattr(audio, "synthesize", lambda *a, **kw: pytest.fail("must not generate a substitute"))
    for voice, acting in (({"engine": "dramabox"}, {}),
                          ({}, {"engine": "voxcpm"}),
                          ({"event_engine": "higgs"}, {"event": "sigh"})):
        show = {"characters": {"hero": {"voice": voice}}}
        with pytest.raises(RuntimeError, match="No substitute voice"):
            build.line_voice(show, {"who": "hero", "say": "Hello.", "acting": acting})
    assert build.line_voice({"characters": {"hero": {}}}, {"who": "hero", "say": "Hello."}) == {
        "kokoro": "bm_george", "rate": 1.0, "pitch": 0.0}


def test_cli_init_help_and_no_private_cost_command(tmp_path):
    result = CliRunner().invoke(main, ["init", str(tmp_path / "film")])
    assert result.exit_code == 0
    assert "--quality draft" in result.output and "Optional dialogue" in result.output
    assert "llm-cost" not in main.commands
    result = subprocess.run([sys.executable, "-m", "stopmo.cli", "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert all(name in result.stdout for name in ("lineup", "doctor", "init"))
    assert "llm-cost" not in result.stdout


def test_music_only_build_never_runs_asr_or_warns_about_absent_asr(tmp_path, monkeypatch, capsys):
    from stopmo.cli import _sound_report
    from stopmo.ledger import Ledger

    monkeypatch.setattr(audio, "mix_program", lambda *a, **kw: {})
    monkeypatch.setattr(transcribe, "available", lambda: True)
    monkeypatch.setattr(transcribe, "transcribe", lambda *a: pytest.fail("no dialogue to recognize"))
    _, report = build.build_sound({"shots": []}, {}, [], tmp_path / "mix.wav",
                                 tmp_path / "cache", Ledger())
    assert not report["has_dialogue"]
    assert report["finished_transcript"] is None
    report["transcriber_available"] = False
    _sound_report(report)
    assert "WARNING" not in capsys.readouterr().out