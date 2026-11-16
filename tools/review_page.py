"""One self-contained HTML page with small copies of finished films and their build numbers.

    .venv/bin/python tools/review_page.py out/review.html out/<show>/<ep>/<quality> [more build dirs...]
"""
import base64
from html import escape
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from stopmo.audio import _ffmpeg  # noqa: E402

out, builds = Path(sys.argv[1]), [Path(p) for p in sys.argv[2:]]
cards = []
for build in builds:
    summary = json.loads((build / "summary.json").read_text())
    # Aggregate per-shot time is not wall time: jobs can overlap.
    render_min = sum(shot["render"]["seconds"] for shot in summary["shots"]) / 60
    sound = summary.get("sound") or {}
    heard = (sound.get("finished_transcript") or {}).get("match")
    video = Path(summary["video"])
    small = build / "review_480p.mp4"
    subprocess.run([_ffmpeg(), "-v", "error", "-y", "-i", str(video), "-vf", "scale=854:480:flags=lanczos",
                    "-c:v", "libx264", "-preset", "slow", "-b:v", "620k", "-maxrate", "800k", "-bufsize", "1600k",
                    "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(small)], check=True)
    data = base64.b64encode(small.read_bytes()).decode()
    check_file = build / "render_check.json"
    if check_file.exists():
        results = json.loads(check_file.read_text())
        fixed = sum(len(r["repaired"]) for r in results)
        differing = sum(bool(r.get("differ")) for r in results)
        status = (f"Render check recorded: {sum(r['checked'] for r in results)} exposures compared; "
                  f"{differing} shots differed; {fixed} exposures replaced. "
                  "This report does not establish full-frame or visual acceptance.")
    else:
        status = "Render check unavailable: no comparison report found."
    words = {True: "a speech recogniser heard every scripted word in the finished mix",
             False: "a speech recogniser did NOT hear every scripted word in the finished mix",
             None: "words not checked"}[heard]
    loudness = sound.get("integrated_lufs")
    level = "not measured" if loudness is None else f"{float(loudness):.1f} LUFS"
    cards.append(f"""
<section>
  <h2>{escape(str(summary['show']))} / {escape(str(summary['episode']))} <small>({escape(str(summary['quality']))})</small></h2>
  <video controls preload="metadata" src="data:video/mp4;base64,{data}"></video>
  <p>{escape(str(summary['seconds_of_film']))} s, {escape(str(summary['exposures']))} exposures, {len(summary['shots'])} shots.
     Aggregate shot-render time: {render_min:.1f} min (not elapsed wall time). Sound {level}; {words}. API cost not tracked by this page.</p>
  <p class="status">{escape(status)}</p>
  <p class="path">Full-quality filename: {escape(video.name)}</p>
</section>""")
html = f"""<!doctype html><meta charset="utf-8"><title>stopmo-studio review</title>
<style>
 body {{ font: 15px/1.5 system-ui, sans-serif; margin: 24px auto; max-width: 900px; padding: 0 16px; color: #222; background: #f6f3ee; }}
 video {{ width: 100%; border-radius: 8px; background: #000; }}
 section {{ margin-bottom: 36px; }} h2 {{ margin-bottom: 8px; }} small {{ color: #777; font-weight: normal; }}
 .status {{ font-size: 13px; margin: 2px 0; color: #355; }}
 .path {{ color: #666; font-size: 13px; word-break: break-all; }}
</style>
<h1>stopmo-studio: review copies</h1>
<p>These are 480p review copies embedded in the page. Full-quality filenames are shown without local paths;
share those files separately. Review titles and film content for private information before sharing.
This page does not certify that anyone has watched or listened to the finished film.</p>
{''.join(cards)}"""
out.write_text(html)
print(out, f"{out.stat().st_size / 1e6:.1f} MB")
