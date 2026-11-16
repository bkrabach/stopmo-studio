#!/bin/bash
# Run a Python script inside headless Blender with stopmo_bl importable.
#   tools/bl.sh script.py [args...]; only run scripts you trust.
set -euo pipefail
if [[ $# -lt 1 ]]; then
  echo "Usage: tools/bl.sh script.py [args...]; set BLENDER or put blender on PATH." >&2
  exit 2
fi
HERE="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$1"; shift
if ! command -v "${BLENDER:-blender}" >/dev/null; then
  echo "Install Blender 5.0+ and put blender on PATH, or set BLENDER to its executable." >&2
  exit 1
fi
STOPMO_SRC="$HERE/src" exec "${BLENDER:-blender}" --background --factory-startup \
  --python-exit-code 1 --python "$SCRIPT" -- "$@"
