"""Compare a film with a reference, frame by frame: numbers, a side-by-side video and a page.

    .venv/bin/python tools/compare_video.py REFERENCE.mp4 OURS.mp4 OUT_DIR [--seconds 10] [--fps 30]

Both are read at the same frame rate and reduced to 96x54. Per frame it records brightness of each,
the mean absolute difference (0-255, lower is closer) and the correlation of the two pictures'
brightness patterns (1 = light and dark in the same places, 0 = unrelated). It writes metrics.json,
side_by_side.mp4 (reference left, with the reference's sound) and compare.html.
"""
import argparse
import base64
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from stopmo.audio import _ffmpeg  # noqa: E402

W, H = 96, 54


def frames(path: Path, fps: float, seconds: float) -> np.ndarray:
    """The film as an array (frames, H, W, 3), resampled to `fps`."""
    raw = subprocess.run([_ffmpeg(), "-v", "error", "-t", str(seconds), "-i", str(path), "-vf", f"fps={fps},scale={W}:{H}:flags=area",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3).astype(np.float32)


def measure(ref: np.ndarray, ours: np.ndarray) -> list[dict]:
    rows = []
    for a, b in zip(ref, ours):
        la, lb = a.mean(2), b.mean(2)
        da, db = la - la.mean(), lb - lb.mean()
        rows.append({"ref_brightness": float(la.mean()), "our_brightness": float(lb.mean()), "difference": float(np.abs(a - b).mean()),
                     "pattern": float((da * db).sum() / (np.sqrt((da ** 2).sum() * (db ** 2).sum()) + 1e-6))})
    return rows


def chart(series: dict[str, list[float]], top: float, title: str, cuts=()) -> str:
    """A small line chart as SVG: one line per named series, 0..top."""
    w, h = 900, 170
    colours = ["#b5552b", "#2f6f8f", "#5a8a3a"]
    parts = [f'<svg viewBox="0 0 {w} {h + 26}" width="100%"><text x="0" y="12" font-size="12">{title}</text>']
    for x in cuts:
        parts.append(f'<line x1="{x * w:.1f}" x2="{x * w:.1f}" y1="18" y2="{h + 18}" stroke="#bbb" stroke-dasharray="3 3"/>')
    for i, (name, values) in enumerate(series.items()):
        n = len(values)
        pts = " ".join(f"{k / max(n - 1, 1) * w:.1f},{h + 18 - min(max(v, 0), top) / top * h:.1f}" for k, v in enumerate(values))
        parts.append(f'<polyline fill="none" stroke="{colours[i % 3]}" stroke-width="1.6" points="{pts}"/>')
        parts.append(f'<text x="{110 + i * 150}" y="12" font-size="12" fill="{colours[i % 3]}">{name}</text>')
    return "".join(parts) + "</svg>"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("reference", type=Path)
    parser.add_argument("ours", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--spans", default="", help="named stretches to average, e.g. 'night=0:2.9,day=5:7.6,close=7.6:10'")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    ref, ours = frames(args.reference, args.fps, args.seconds), frames(args.ours, args.fps, args.seconds)
    n = min(len(ref), len(ours))
    rows = measure(ref[:n], ours[:n])
    spans = {"whole": (0.0, n / args.fps)}
    for item in filter(None, args.spans.split(",")):
        name, span = item.split("=")
        spans[name] = tuple(float(v) for v in span.split(":"))
    summary = {}
    for name, (a, b) in spans.items():
        part = rows[round(a * args.fps):round(b * args.fps)]
        summary[name] = {key: round(float(np.mean([r[key] for r in part])), 3) for key in rows[0]}
    (args.out / "metrics.json").write_text(json.dumps({"frames": n, "fps": args.fps, "summary": summary, "per_frame": rows}))
    side = args.out / "side_by_side.mp4"
    subprocess.run([_ffmpeg(), "-v", "error", "-y", "-t", str(args.seconds), "-i", str(args.reference), "-t", str(args.seconds), "-i", str(args.ours),
                    "-filter_complex", f"[0:v]fps={args.fps},scale=960:540[a];[1:v]fps={args.fps},scale=960:540[b];[a][b]hstack=inputs=2[v]",
                    "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                    "-movflags", "+faststart", str(side)], check=True)
    cuts = [b / (n / args.fps) for name, (a, b) in spans.items() if name != "whole"]
    table = "".join(f"<tr><td>{name}</td><td>{a:g}-{b:g} s</td><td>{summary[name]['difference']:.1f}</td><td>{summary[name]['pattern']:.2f}</td>"
                    f"<td>{summary[name]['ref_brightness']:.0f}</td><td>{summary[name]['our_brightness']:.0f}</td></tr>" for name, (a, b) in spans.items())
    video = base64.b64encode(side.read_bytes()).decode()
    (args.out / "compare.html").write_text(f"""<!doctype html><meta charset="utf-8"><title>Replica compared with the reference</title>
<style>body{{font:15px system-ui;margin:24px;max-width:1100px;color:#222}}video{{width:100%;background:#000}}td,th{{padding:4px 12px;text-align:right}}
td:first-child,th:first-child{{text-align:left}}table{{border-collapse:collapse;margin:12px 0}}tr{{border-bottom:1px solid #ddd}}p{{max-width:820px}}</style>
<h2>Reference (left) and replica (right)</h2>
<video controls loop src="data:video/mp4;base64,{video}"></video>
<p>Sound is the reference's. Step frame by frame with the , and . keys in most browsers.</p>
<table><tr><th>Stretch</th><th>Time</th><th>Difference (0-255)</th><th>Pattern match (0-1)</th><th>Reference brightness</th><th>Replica brightness</th></tr>{table}</table>
<p>Difference: mean absolute difference per colour channel between the two pictures, reduced to 96x54. Pattern match: correlation of the
two pictures' light-and-dark layout; 1 means bright and dark areas are in the same places.</p>
{chart({"reference": [r["ref_brightness"] for r in rows], "replica": [r["our_brightness"] for r in rows]}, 200, "Brightness", cuts)}
{chart({"difference": [r["difference"] for r in rows]}, 100, "Difference", cuts)}
{chart({"pattern match": [r["pattern"] for r in rows]}, 1, "Pattern match", cuts)}
""")
    print(json.dumps(summary, indent=1))
    print(args.out / "compare.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
