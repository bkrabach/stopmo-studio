"""Frame-to-frame change per clip of a sweep:  .venv/bin/python tools/sweep_metrics.py <sweep dir> [reference frames dir]

Per variant, on a 0-255 scale over the full frame:
  whole-frame change  mean absolute difference between consecutive exposures (mostly the performance)
  isolated flicker    the same measure after subtracting the first variant exposure by exposure, which
                      removes the shared motion and light flicker and leaves what the setting adds
With a reference frames dir, also reports how far each variant's frames are from it (same exposure).
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def load(path):
    return np.asarray(Image.open(path).convert("L").resize((960, 540), Image.BILINEAR), dtype=np.float32)


sweep_dir = Path(sys.argv[1])
reference = Path(sys.argv[2]) if len(sys.argv) > 2 else None
summary = json.loads((sweep_dir / "summary.json").read_text())
clips = summary["clips"]
stacks = []
for clip in clips:
    files = sorted(Path(clip["frames_dir"]).glob("f_*.png"))
    stacks.append((files, np.stack([load(f) for f in files])))
base = stacks[0][1]  # first variant: everything it shows (motion, light flicker) is in every other clip too
rows = []
for clip, (files, frames) in zip(clips, stacks):
    change = float(np.abs(np.diff(frames, axis=0)).mean())
    # what this variant adds on top of the first one, and how much THAT changes between exposures
    isolated = float(np.abs(np.diff(frames - base, axis=0)).mean())
    ref = None
    if reference:
        pairs = [(fr, reference / f.name) for fr, f in zip(frames, files) if (reference / f.name).exists()]
        ref = float(np.mean([np.abs(fr - load(p)).mean() for fr, p in pairs])) if pairs else None
    rows.append((clip["value"], len(files), change, isolated, ref, clip["render_seconds"]))
top = max(r[3] for r in rows) or 1.0
print(f"{summary['key']:>8}  exposures  whole-frame change  isolated flicker  % of strongest  render s"
      + ("  diff vs reference" if reference else ""))
for value, count, change, isolated, ref, render_s in rows:
    print(f"{value!s:>8}  {count:9d}  {change:18.3f}  {isolated:16.3f}  {100 * isolated / top:13.1f}%  {render_s:8.0f}"
          + (f"  {ref:17.3f}" if ref is not None else ""))
