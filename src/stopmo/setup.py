"""Read-only environment checks and a small, asset-free project scaffold."""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
# The renderer uses modern layered actions. Older Blender releases are unsupported.
MIN_BLENDER = (5, 0, 0)
CHECKOUT_FILES = (
    "pyproject.toml", "styles/clay.yaml", "tools/bl.sh",
    "src/stopmo_bl/director.py", "src/stopmo_bl/archetypes/toy.py",
    "src/stopmo_voice/speak.py",
)


def safe_component(value: str, label: str = "name") -> str:
    """Validate one portable output component, never a path or traversal."""
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                *(f"LPT{i}" for i in range(1, 10))}
    if (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value)
            or value.endswith(".") or value.split(".")[0].upper() in reserved):
        raise ValueError(f"{label} must be 1-64 letters, digits, underscores, hyphens or dots, "
                         "start with a letter or digit, and not be a reserved filename")
    return value


def blender_executable() -> str:
    """Resolve BLENDER (one executable, not a shell command), otherwise PATH."""
    requested = os.environ.get("BLENDER") or "blender"
    found = shutil.which(requested)
    if not found:
        raise RuntimeError("Blender not found. Install Blender 5.0+ and put blender on PATH, "
                           "or set BLENDER to its executable (not the .app directory).")
    return found


def _probe(args: list[str], timeout: float = 15) -> str | None:
    """Only callers' fixed, read-only probes; never expose arbitrary process output."""
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def doctor() -> dict:
    """Check local readiness without installing, importing models or rendering.

    Optional tools are checked for presence (and their small CLI/import probes),
    not inference quality. No environment dump, hostname, username or local paths
    are included in the report.
    """
    from . import audio, lipsync, transcribe

    checks = []

    def add(name: str, required: bool, ok: bool, detail: str, fix: str) -> None:
        checks.append({"name": name, "required": required, "ok": bool(ok),
                       "detail": detail, "fix": "" if ok else fix})

    add("python", True, sys.version_info >= (3, 11),
        f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "Create .venv with Python 3.11+ and install this checkout with: uv pip install -e .")
    missing = [name for name in CHECKOUT_FILES if not (ROOT / name).is_file()]
    add("checkout", True, not missing, "Source resources present" if not missing else
        "Missing source resources: " + ", ".join(missing),
        "Use a complete source checkout and an editable install: uv pip install -e . "
        "A standalone wheel does not include styles/ or tools/.")
    try:
        version_text = _probe([blender_executable(), "--version"])
    except RuntimeError:
        version_text = None
    match = re.search(r"Blender (\d+)\.(\d+)\.(\d+)", version_text or "")
    version = tuple(map(int, match.groups())) if match else ()
    add("blender", True, bool(version and version >= MIN_BLENDER),
        "Blender " + ".".join(map(str, version)) if version else "Blender version probe failed",
        "Install Blender 5.0+; put blender on PATH or set BLENDER to the executable. "
        "doctor checks the version, not GPU/render compatibility.")
    try:
        ffmpeg = audio._ffmpeg()
        encoders = _probe([ffmpeg, "-hide_banner", "-encoders"])
        found = set(re.findall(r"^\s*[VAS][A-Z.]{5}\s+(\S+)", encoders or "", re.M))
        missing_encoders = sorted({"libx264", "aac", "pcm_s16le"} - found)
        ffmpeg_ok = encoders is not None and not missing_encoders
        detail = "H.264, AAC and PCM encoders present" if ffmpeg_ok else (
            "Missing encoders: " + ", ".join(missing_encoders))
    except (RuntimeError, OSError, ImportError):
        ffmpeg_ok, detail = False, "FFmpeg executable probe failed"
    add("ffmpeg", True, ffmpeg_ok, detail,
        "Install the base dependencies (uv pip install -e .). If your system FFmpeg lacks "
        "libx264/aac/pcm_s16le, set STOPMO_FFMPEG to a compatible executable.")
    add("kokoro", False, audio.kokoro_available(),
        "Python wrapper and model-file presence check; no synthesis attempted",
        "Optional macOS setup: bash tools/install_voice_tools.sh --kokoro. "
        "Not needed for projects without dialogue.")
    acting_ok = audio.acting_available() and _probe([
        str(audio.ACTING_PYTHON), "-B", "-c",
        "import importlib.util; "
        "print(all(importlib.util.find_spec(n) is not None for n in "
        "('mlx_audio', 'mlx', 'soundfile', 'torch')))"]) == "True\n"
    add("acting", False, acting_ok,
        "Environment/package presence check only; model weights are not loaded or downloaded",
        "Optional Apple Silicon setup: review the upstream licenses, then "
        "bash tools/install_voice_tools.sh --acting --accept-model-licenses. "
        "Weights download on first engine use; permission and disk budget are still required.")
    rhubarb = lipsync._rhubarb()
    rhubarb_ok = bool(rhubarb and _probe([rhubarb, "--version"]) is not None)
    add("rhubarb", False, rhubarb_ok, "Rhubarb CLI probe; built-in energy lip-sync is always available",
        "Optional macOS setup: bash tools/install_voice_tools.sh --rhubarb. "
        "Apple Silicon needs Rosetta for the upstream Intel binary; use system approval controls.")
    whisper_ok = transcribe.available()
    if whisper_ok:
        binary, _ = transcribe._tools()
        whisper_ok = _probe([str(binary), "--help"]) is not None
    add("whisper", False, whisper_ok, "ASR CLI/model presence check; no transcription attempted",
        "Optional macOS setup: bash tools/install_voice_tools.sh --whisper, "
        "or configure STOPMO_WHISPER and STOPMO_WHISPER_MODEL manually.")
    return {"ok": all(c["ok"] for c in checks if c["required"]), "checks": checks}


def init_project(path: Path) -> Path:
    """Create a NEW local-only project. No copies of previous shows or media."""
    import yaml

    path = Path(path).expanduser()
    if ".." in path.parts:
        raise ValueError("Project path must not contain '..'")
    safe_component(path.name, "project name")
    # mkdir is the non-overwrite fence, including existing files and symlinks.
    path.mkdir(parents=True, exist_ok=False)
    (path / ".gitignore").write_text("# Local project; opt in explicitly before publishing any of it.\n*\n")
    (path / "characters").mkdir()
    (path / "episodes").mkdir()
    show = {
        "title": "A Little Hello", "style": "clay", "set": "studio",
        "music": {"style": "marimba", "tempo": 90, "key": "C", "seed": 1, "gain": 0.08},
        "mix": {"target_lufs": -23},
    }
    character = {"archetype": "toy", "height": 0.20, "body": "#547D8A", "skin": "#E6C8A8"}
    # The director counts inclusive exposures: wait 23/12 at frame 1 ends at
    # frame 24, i.e. exactly two seconds at the clay pack's 12 exposures/s.
    episode = {"seed": 1, "shots": [{
        "id": "hello", "lead": 0, "hold": 0, "camera": "wide",
        "cast": {"hero": {"at": "center", "facing": "camera"}},
        "beats": [
            {"t": 0, "wait": 23 / 12},
            {"t": 0.25, "who": "hero", "do": "hop", "height": 0.025},
            {"t": 0.75, "sfx": "pop", "gain": 0.08},
        ],
    }]}
    for relative, data in (("show.yaml", show), ("characters/hero.yaml", character),
                           ("episodes/hello.yaml", episode)):
        with (path / relative).open("x") as handle:
            yaml.safe_dump(data, handle, sort_keys=False)
    return path.resolve()