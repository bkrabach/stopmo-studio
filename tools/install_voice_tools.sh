#!/bin/bash
# Opt-in local tools. No flag means help, not installation.
set -euo pipefail
usage() {
  cat <<'HELP'
Usage: bash tools/install_voice_tools.sh [--kokoro] [--rhubarb] [--whisper]
                                       [--acting --accept-model-licenses]
macOS only. Select only the components you want; no arguments installs nothing.

  --kokoro   CPU speech: Python package + ~337 MB model/voices, plus dependencies.
  --rhubarb  Lip-sync: pinned Intel macOS binary (~83 MB zip, ~200 MB unpacked).
             Apple Silicon needs Rosetta installed/approved by the user.
  --whisper  ASR: CPU-only whisper.cpp build + ~574 MB quantized model.
             Allow ~2 GB disk for source, build and model; CPU inference can be slow.
  --acting   Apple Silicon ONLY: separate Python 3.12/MLX environment, several GB.
             NO weights fetched by this installer. First use of an engine downloads
             multiple GB; trying all engines can use tens of GB (~45 GB or more).
  --accept-model-licenses  Required with --acting. Acknowledges that YOU reviewed
             the upstream terms; it is NOT a license, waiver, or publishing clearance.
  -h, --help Show this help without installation.

Prerequisites: a base editable install in .venv (Python 3.11+); curl for downloads;
uv for Kokoro/acting; cmake, tar and a C/C++ compiler (Xcode Command Line Tools) for
Whisper. Python handles zip extraction; unzip is not required. uv may download
Python 3.12 for acting. No sudo, shell profile changes or quarantine removal.
Use system security controls if a downloaded executable is blocked.

Network: GitHub releases, Hugging Face and the Python package index, depending on
flags. Kokoro/Whisper weights use pinned SHA-256 digests. Rhubarb and whisper.cpp
source use pinned release versions and archive checks, but no upstream checksum
is available here; review those releases before trusting downloaded code.
Python packages pin direct tool versions where practical, not transitive wheels.

License decisions: Kokoro weights are Apache-2.0; review its voice/model card.
Dramabox uses LTX-2 community terms with separate eligibility/use conditions;
being below a revenue threshold does not establish commercial rights.
VoxCPM2 declares Apache-2.0. Breeze and Higgs have additional research /
non-commercial restrictions. Review BOTH conversion and original model terms:
  https://huggingface.co/hexgrad/Kokoro-82M
  https://huggingface.co/mlx-community/ResembleAI-Dramabox
  https://huggingface.co/mlx-community/VoxCPM2-bf16
  https://huggingface.co/mlx-community/Breeze-TTS-2-mlx-8bit
  https://huggingface.co/bosonai/higgs-audio-v3-tts-4b
Only use reference voices you have permission to use. Consult docs before release.
HELP
}
KOKORO=0; RHUBARB=0; WHISPER=0; ACTING=0; ACCEPT=0
if [[ $# -eq 0 ]]; then usage; exit 0; fi
for arg in "$@"; do
  case "$arg" in
    --kokoro) KOKORO=1 ;;
    --rhubarb) RHUBARB=1 ;;
    --whisper) WHISPER=1 ;;
    --acting) ACTING=1 ;;
    --accept-model-licenses) ACCEPT=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; usage >&2; exit 2 ;;
  esac
done
if [[ "$ACTING" == 1 && "$ACCEPT" != 1 ]]; then
  echo 'Read the upstream model terms first. --acting requires --accept-model-licenses; it grants no rights.' >&2
  exit 2
fi
if [[ "$ACCEPT" == 1 && "$ACTING" != 1 ]]; then
  echo '--accept-model-licenses is only meaningful with --acting.' >&2; exit 2
fi
if [[ "$(uname -s)" != Darwin ]]; then
  echo 'This installer supports macOS only. See docs for manual Linux setup.' >&2; exit 1
fi
if [[ "$ACTING" == 1 && "$(uname -m)" != arm64 ]]; then
  echo '--acting requires Apple Silicon/MLX; no acting environment was installed.' >&2; exit 1
fi
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$ROOT/.venv/bin/python"
VENDOR="$ROOT/vendor"
if [[ ! -x "$PYTHON" ]]; then
  echo 'First create .venv and install this checkout: uv venv --python 3.12 && uv pip install -e .' >&2; exit 1
fi
need() { command -v "$1" >/dev/null || { echo "Missing prerequisite: $1" >&2; exit 1; }; }
if [[ "$KOKORO" == 1 || "$ACTING" == 1 ]]; then need uv; fi
if [[ "$KOKORO" == 1 || "$RHUBARB" == 1 || "$WHISPER" == 1 ]]; then need curl; fi
if [[ "$WHISPER" == 1 ]]; then need cmake; need tar; need cc; need c++; fi
verify() {
  "$PYTHON" - "$1" "$2" <<'PY'
import hashlib, pathlib, sys
p, expected = pathlib.Path(sys.argv[1]), sys.argv[2]
if not p.is_file() or not p.stat().st_size:
    raise SystemExit('Download is empty or missing')
if expected:
    with p.open('rb') as f:
        actual = hashlib.file_digest(f, 'sha256').hexdigest()
    if actual != expected:
        raise SystemExit('Checksum mismatch; file was NOT installed. Inspect/remove the cached download before retrying.')
PY
}
fetch() {
  local url="$1" dest="$2" sha="$3"
  mkdir -p "$(dirname "$dest")"
  if [[ -f "$dest" ]]; then verify "$dest" "$sha"; return; fi
  curl --proto '=https' --proto-redir '=https' --fail --location --retry 3 \
    --connect-timeout 30 --output "$dest.part" "$url"
  verify "$dest.part" "$sha"
  mv "$dest.part" "$dest"
}
# Digests: the model-files-v1.1 GitHub release asset listing; Whisper HF LFS metadata.
if [[ "$KOKORO" == 1 ]]; then
  uv pip install --python "$PYTHON" 'kokoro-onnx==0.6.1'
  BASE=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1
  fetch "$BASE/kokoro-v1.0.onnx" "$VENDOR/kokoro/kokoro-v1.0.onnx" \
    beb0d1848dee9a49da392cc3df26958d46cfa35d321edf434f52949153f0df3a
  fetch "$BASE/voices-v1.0.bin" "$VENDOR/kokoro/voices-v1.0.bin" \
    bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d
  echo 'Kokoro files installed. No synthesis performed; run stopmo doctor.'
fi
if [[ "$RHUBARB" == 1 ]]; then
  fetch https://github.com/DanielSWolf/rhubarb-lip-sync/releases/download/v1.14.0/Rhubarb-Lip-Sync-1.14.0-macOS.zip \
    "$VENDOR/rhubarb/release-1.14.0.zip" ''
  "$PYTHON" - "$VENDOR/rhubarb" <<'PY'
import pathlib, shutil, sys, zipfile
root = pathlib.Path(sys.argv[1])
with zipfile.ZipFile(root / 'release-1.14.0.zip') as archive:
    if archive.testzip() is not None:
        raise SystemExit('Rhubarb archive integrity check failed')
    for item in archive.infolist():
        name = pathlib.PurePosixPath(item.filename)
        if name.is_absolute() or '..' in name.parts or '\\' in item.filename:
            raise SystemExit('Unsafe Rhubarb archive path')
        parts = name.parts[1:]  # discard the release's top-level folder
        if not parts or item.is_dir():
            continue
        dest = root.joinpath(*parts)
        if not dest.resolve().is_relative_to(root.resolve()):
            raise SystemExit('Unsafe Rhubarb extraction destination')
        dest.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(item) as src, dest.open('wb') as out:
            shutil.copyfileobj(src, out)
PY
  chmod +x "$VENDOR/rhubarb/rhubarb"
  echo 'Rhubarb extracted. Security settings were not changed; run stopmo doctor.'
fi
if [[ "$WHISPER" == 1 ]]; then
  fetch https://huggingface.co/ggerganov/whisper.cpp/resolve/5359861c739e955e79d9a303bcbc70fb988958b1/ggml-large-v3-turbo-q5_0.bin \
    "$VENDOR/whisper/ggml-large-v3-turbo-q5_0.bin" \
    394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2
  fetch https://github.com/ggml-org/whisper.cpp/archive/refs/tags/v1.9.4.tar.gz \
    "$VENDOR/whisper/source-v1.9.4.tar.gz" ''
  "$PYTHON" - "$VENDOR/whisper" <<'PY'
import pathlib, shutil, sys, tarfile
root = pathlib.Path(sys.argv[1])
dest = root / 'source-v1.9.4'
dest.mkdir(exist_ok=True)
with tarfile.open(root / 'source-v1.9.4.tar.gz', 'r:gz') as archive:
    for item in archive:
        name = pathlib.PurePosixPath(item.name)
        if name.is_absolute() or '..' in name.parts or not (item.isfile() or item.isdir()):
            raise SystemExit('Unsafe whisper.cpp archive entry')
        parts = name.parts[1:]
        if not parts:
            continue
        path = dest.joinpath(*parts)
        if not path.resolve().is_relative_to(dest.resolve()):
            raise SystemExit('Unsafe whisper.cpp extraction destination')
        if item.isdir():
            path.mkdir(parents=True, exist_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(item) as src, path.open('wb') as out:
                shutil.copyfileobj(src, out)
            path.chmod(item.mode & 0o777)
PY
  cmake -S "$VENDOR/whisper/source-v1.9.4" -B "$VENDOR/whisper/cpu" \
    -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF \
    -DGGML_METAL=OFF -DGGML_BACKEND_DL=OFF -DGGML_OPENMP=OFF \
    -DWHISPER_COREML=OFF -DWHISPER_BUILD_TESTS=OFF -DWHISPER_BUILD_SERVER=OFF
  cmake --build "$VENDOR/whisper/cpu" --target whisper-cli --parallel 4
  echo 'Whisper CPU build and model installed. No transcription performed.'
fi
if [[ "$ACTING" == 1 ]]; then
  if [[ ! -x "$VENDOR/acting/venv/bin/python" ]]; then
    uv venv --python 3.12 "$VENDOR/acting/venv"
  fi
  uv pip install --python "$VENDOR/acting/venv/bin/python" 'mlx-audio==0.6.5' soundfile torch
  echo 'Acting packages installed; no model weights downloaded. First use needs disk/network approval.'
  echo 'License acknowledgement is not publishing clearance; check each chosen engine and reference voice.'
fi
