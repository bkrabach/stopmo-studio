"""Compare finished shots with reference renders, and repair exposures that came out wrong.

    .venv/bin/python tools/check_render.py out/<show>/<episode>/<quality> [--every 8] [--repair] [--resume]

Sequential rendering can produce transient differences without an error. This check detects some
of those differences; it is not a substitute for visual review or full exposure coverage.

A correct render is reproducible to within sampling noise, so this tool re-renders every Nth exposure
of each shot in a fresh process that carries nothing over between frames, and flags exposures that
differ over a visible area. With --repair it then re-renders the stretch around each flagged exposure
and replaces the exposures that differ; run `stopmo build ... --reuse` afterwards to re-assemble.
Exit code 1 if anything differed and was not repaired. --resume continues a check that was interrupted:
shots already repaired keep their recorded result, and finished reference renders are compared again
rather than rendered again.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BLENDER = os.environ.get("BLENDER") or shutil.which("blender") or "blender"
LEVEL, AREA = 40, 0.0001  # a pixel "differs" beyond 40/255; an exposure fails when over 0.01% of it does


def render(plan: dict, frames: list[int], work: Path) -> None:
    """Reference render of `frames` into work/frames (fresh process, nothing kept between frames)."""
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    (work / "plan.json").write_text(json.dumps({**plan, "frames": frames, "save_blend": False}))
    env = {**os.environ, "STOPMO_SRC": str(ROOT / "src")}
    proc = subprocess.run([BLENDER, "--background", "--factory-startup", "--python-exit-code", "1", "--python",
                           str(ROOT / "tools/render_fresh.py"), "--", str(work / "plan.json")],
                          env=env, capture_output=True, text=True)
    if proc.returncode:
        raise RuntimeError(f"reference render failed: {(proc.stdout + proc.stderr).strip().splitlines()[-1]}")


def differs(a: Path, b: Path) -> str | None:
    """None when two exposures match, else a short description of where they differ."""
    x = np.asarray(Image.open(a).convert("L"), dtype=np.float32)
    y = np.asarray(Image.open(b).convert("L"), dtype=np.float32)
    mask = np.abs(x - y) > LEVEL
    if mask.mean() <= AREA:
        return None
    ys, xs = np.where(mask)
    return f"{int(mask.sum())} pixels, x {int(xs.min())}-{int(xs.max())}, y {int(ys.min())}-{int(ys.max())}"


def check(shot_dir: Path, every: int, repair: bool, resume: bool = False) -> dict:
    if every < 1:
        raise ValueError("every must be positive")
    plan = json.loads((shot_dir / "plan.json").read_text())
    last = json.loads((shot_dir / "timing.json").read_text())["frames"]
    if last < 1:
        raise ValueError("Cannot check a shot with no exposures")
    fingerprint = hashlib.sha256((shot_dir / "plan.json").read_bytes())
    for path in sorted((ROOT / "src/stopmo_bl").rglob("*.py")):
        fingerprint.update(path.read_bytes())
    for path in sorted((shot_dir / "frames").glob("f_*.png")):
        fingerprint.update(path.name.encode())
        fingerprint.update(path.read_bytes())
    signature = fingerprint.hexdigest()
    name = lambda f: f"f_{f:05d}.png"  # noqa: E731
    sample = sorted({1, last, *range(max(1, every // 2), last + 1, every)})
    recheck = shot_dir / "recheck"
    if resume and (shot_dir / "repaired.json").exists():  # checked and repaired before the interruption
        result = json.loads((shot_dir / "repaired.json").read_text())
        if result.get("signature") == signature:
            print(f"{shot_dir.name}: checked earlier, differed on {sorted(result['differ'], key=int)}; "
                  f"replaced {len(result['repaired'])} exposures", flush=True)
            return result
    wanted = {**plan, "frames": sample, "save_blend": False}
    marker = recheck / "source_signature.txt"
    finished = ((recheck / "timing.json").exists() and marker.exists()
                and marker.read_text() == signature
                and json.loads((recheck / "plan.json").read_text()) == wanted)
    if not (resume and finished):
        render(plan, sample, recheck)
        marker.write_text(signature)
    bad = {f: d for f in sample if (d := differs(shot_dir / "frames" / name(f), shot_dir / "recheck/frames" / name(f)))}
    result = {"shot": shot_dir.name, "checked": len(sample), "total": last, "signature": signature,
              "differ": bad, "repaired": []}
    if bad and repair:
        stretch = sorted({g for f in bad for g in range(max(1, f - every + 1), min(last, f + every - 1) + 1)})
        render(plan, stretch, shot_dir / "repair")
        for f in stretch:
            if differs(shot_dir / "frames" / name(f), shot_dir / "repair/frames" / name(f)):
                shutil.copyfile(shot_dir / "repair/frames" / name(f), shot_dir / "frames" / name(f))
                result["repaired"].append(f)
        (shot_dir / "repaired.json").write_text(json.dumps(result, indent=1))
    state = "matches" if not bad else f"DIFFERS on {sorted(bad)}" + (f"; replaced {len(result['repaired'])} exposures" if repair else "")
    print(f"{shot_dir.name}: {len(sample)} of {last} exposures checked, {state}", flush=True)
    for f, where in bad.items():
        print(f"    exposure {f}: {where}", flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("build_dir", type=Path)
    parser.add_argument("--every", type=int, default=8, help="check every Nth exposure of each shot")
    parser.add_argument("--repair", action="store_true", help="re-render and replace exposures that differ")
    parser.add_argument("--resume", action="store_true", help="continue an interrupted check without re-rendering finished parts")
    args = parser.parse_args()
    if args.every < 1:
        parser.error("--every must be positive")
    done_files = sorted(args.build_dir.glob("*/done.json"))
    if not done_files:
        parser.error("No completed shots found; zero coverage is not a pass")
    results = [check(done.parent, args.every, args.repair, args.resume) for done in done_files]
    wrong = [r for r in results if r["differ"]]
    fixed = sum(len(r["repaired"]) for r in results)
    (args.build_dir / "render_check.json").write_text(json.dumps(results, indent=1))
    print(f"RENDER_CHECK {sum(r['checked'] for r in results)} exposures checked in {len(results)} shots; "
          f"{len(wrong)} shots differed; {fixed} exposures replaced")
    return 1 if wrong and not args.repair else 0


if __name__ == "__main__":
    sys.exit(main())
