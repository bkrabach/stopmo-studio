"""Installer/launcher contracts using tiny fake commands; never install models."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "tools/install_voice_tools.sh"


def run_script(path, *args, env=None):
    return subprocess.run(["/bin/bash", str(path), *args], capture_output=True, text=True,
                          env=env, timeout=10)


@pytest.mark.parametrize("args", [(), ("--help",), ("--acting", "--help")])
def test_help_has_no_effects(args, tmp_path):
    # Copy to a new tree with no venv: help must precede all installation checks.
    installer = tmp_path / "install.sh"
    shutil.copyfile(INSTALLER, installer)
    result = run_script(installer, *args)
    assert result.returncode == 0
    assert "--kokoro" in result.stdout and "--accept-model-licenses" in result.stdout
    assert "no arguments installs nothing" in result.stdout
    assert sorted(p.name for p in tmp_path.iterdir()) == ["install.sh"]


@pytest.mark.parametrize("args,expected", [
    (("--acting",), "--acting requires --accept-model-licenses"),
    (("--accept-model-licenses",), "only meaningful with --acting"),
    (("--no-acting",), "Unknown option"),
])
def test_flags_fail_before_any_effect(args, expected):
    result = run_script(INSTALLER, *args)
    assert result.returncode == 2
    assert expected in result.stderr


@pytest.fixture
def fake_install(tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    installer = tools / "install_voice_tools.sh"
    shutil.copyfile(INSTALLER, installer)
    bins = tmp_path / "fake-bin"
    bins.mkdir()
    log = tmp_path / "calls"

    def script(name, text):
        path = bins / name
        path.write_text("#!/bin/bash\n" + text)
        path.chmod(0o755)

    script("uname", 'if [[ "$1" == -s ]]; then echo Darwin; else echo arm64; fi\n')
    script("uv", 'printf "uv %s\\n" "$*" >> "$TEST_CALLS"\n')
    # Produce corrupt bytes instead of contacting a network. Hash checks must stop us.
    script("curl", 'echo curl >> "$TEST_CALLS"\n'
           'while [[ $# -gt 0 ]]; do if [[ "$1" == --output ]]; then printf bad > "$2"; exit 0; fi; shift; done\nexit 99\n')
    venv = tmp_path / ".venv/bin"
    venv.mkdir(parents=True)
    (venv / "python").symlink_to(sys.executable)
    env = {**os.environ, "PATH": f"{bins}:/usr/bin:/bin", "TEST_CALLS": str(log)}
    return installer, env, log, script


def test_acting_installs_packages_only_with_explicit_flags(fake_install):
    installer, env, log, _ = fake_install
    result = run_script(installer, "--acting", "--accept-model-licenses", env=env)
    assert result.returncode == 0, result.stderr
    calls = log.read_text()
    assert calls.count("uv ") == 2
    assert "mlx-audio==0.6.5" in calls and "curl" not in calls
    assert "no model weights downloaded" in result.stdout


def test_kokoro_verifies_checksum_before_installing_model(fake_install):
    installer, env, log, _ = fake_install
    result = run_script(installer, "--kokoro", env=env)
    assert result.returncode != 0 and "Checksum mismatch" in result.stderr
    assert not (installer.parent.parent / "vendor/kokoro/kokoro-v1.0.onnx").exists()
    assert "kokoro-onnx==0.6.1" in log.read_text()
    assert "mlx-audio" not in log.read_text()


def test_platform_errors_before_network_or_package_changes(fake_install):
    installer, env, log, script = fake_install
    script("uname", 'echo Linux\n')
    result = run_script(installer, "--kokoro", env=env)
    assert result.returncode == 1 and "macOS only" in result.stderr
    assert not log.exists()
    script("uname", 'if [[ "$1" == -s ]]; then echo Darwin; else echo x86_64; fi\n')
    result = run_script(installer, "--acting", "--accept-model-licenses", env=env)
    assert result.returncode == 1 and "Apple Silicon" in result.stderr
    assert not log.exists()


def test_shell_syntax_and_no_security_bypass_or_latest_downloads():
    for path in (INSTALLER, ROOT / "tools/bl.sh"):
        result = subprocess.run(["/bin/bash", "-n", str(path)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    text = INSTALLER.read_text()
    assert "xattr" not in text and "releases/latest" not in text and "/resolve/main/" not in text


def test_blender_shell_launcher_uses_path_or_override(tmp_path):
    binary = tmp_path / "blender"
    binary.write_text('#!/bin/bash\nprintf "%s\\n" "$STOPMO_SRC" "$@"\n')
    binary.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:/usr/bin:/bin"}
    env.pop("BLENDER", None)
    for override in (None, str(binary)):
        if override:
            env["BLENDER"] = override
        result = run_script(ROOT / "tools/bl.sh", "scene.py", "a b", env=env)
        assert result.returncode == 0, result.stderr
        assert str(ROOT / "src") in result.stdout
        assert "--python\nscene.py\n--\na b\n" in result.stdout
        assert "--enable-autoexec" not in result.stdout


def test_base_dependencies_and_source_packages():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert any(dep.startswith("imageio-ffmpeg") for dep in config["project"]["dependencies"])
    assert config["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == [
        "src/stopmo", "src/stopmo_bl", "src/stopmo_voice"]