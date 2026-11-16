"""Parameter sweeps: one shot rendered at several values of one style setting, to judge side by side.

Everything except the swept setting is identical between clips (same poses, blinks, camera drift,
light flicker, render seed), so any difference seen is that setting.
"""
from __future__ import annotations

import base64
import copy
import html
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from . import build, encode
from .audio import _ffmpeg, _run
from .ledger import Ledger
from .setup import safe_component

PAGE_VIDEO_BYTES = 12_000_000  # embedded review copies in total; keeps the page under 20 MB as base64


def parse_setting(text: str) -> tuple[str, list]:
    """'boil=0,0.15,1' -> ('boil', [0, 0.15, 1]). The key may be dotted, e.g. 'grade.grain'."""
    key, _, raw = text.partition("=")
    values = [yaml.safe_load(v) for v in raw.split(",") if v.strip()]
    if not key.strip() or not values:
        raise ValueError(f"expected KEY=V1,V2,... but got {text!r}")
    return key.strip(), values


def set_path(data: dict, dotted: str, value) -> None:
    """Set data['a']['b'] = value for dotted 'a.b', creating levels as needed."""
    keys = dotted.split(".")
    for key in keys[:-1]:
        data = data.setdefault(key, {})
    data[keys[-1]] = value


def label(key: str, value) -> str:
    """File-safe name of one variant, e.g. 'boil_0.15'."""
    return safe_component(f"{key.replace('.', '-')}_{value}", "sweep variant")


def sweep(show_dir: Path, episode: str, shot_id: str, key: str, values: list, *, seconds: float = 5.0,
          quality: str = "preview", jobs: int = 2, force: bool = False, out_root: Path | None = None) -> dict:
    """Render the first `seconds` of one shot once per value of style setting `key`.

    Writes silent clips and compare.html into out/<show>/<episode>/sweeps/<shot>__<key>/<quality>/.
    """
    ledger = Ledger()
    show_dir = Path(show_dir).resolve()
    safe_component(shot_id, "shot id")
    safe_component(key, "sweep key")
    safe_component(quality, "quality")
    for value in values:
        label(key, value)  # reject path-shaped values before creating any output
    show = build.load_show(show_dir)
    ep = build.load_episode(show, episode)
    shots = {s["id"]: s for s in ep["shots"]}
    if shot_id not in shots:
        raise KeyError(f"no shot {shot_id!r} in {episode}; have {', '.join(shots)}")
    count = max(1, round(seconds * float(show["style"].get("fps", 12))))
    root = Path(out_root or build.ROOT / "out")
    out = root / show_dir.name / episode / "sweeps" / f"{shot_id}__{key.replace('.', '-')}" / quality
    cache = root / "cache"
    out.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    opts = {"quality": quality, "frames": {"first": count}}

    variants = []
    for value in values:
        variant = copy.deepcopy(show)
        set_path(variant["style"], key, value)
        variants.append((value, variant, build.make_plan(variant, ep, shots[shot_id], opts, cache, ledger)))

    def run(item):
        value, _variant, plan = item
        return build.render_shot(plan, out / label(key, value), ledger, force=force)

    with ledger.stage("render_all", jobs=jobs):
        with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
            timings = list(pool.map(run, variants))

    clips = []
    with ledger.stage("encode"):
        for (value, variant, _plan), timing in zip(variants, timings):
            name = label(key, value)
            clip = encode.frames_to_video(out / name / "frames", out / f"{name}.mp4", fps=timing["fps"],
                                          grade=variant["style"].get("grade"))
            render = timing["stats"]["render"]
            clips.append({"value": value, "video": str(clip), "exposures": render["frames"],
                          "seconds": round(render["frames"] / timing["fps"], 2), "fps": timing["fps"],
                          "render_seconds": render["seconds"], "frames_dir": str(out / name / "frames")})
    title = f"{show_dir.name} / {episode} / {shot_id}: {key}"
    with ledger.stage("page"):
        page = write_page(out / "compare.html", title, key, clips)
    summary = {"show": show_dir.name, "episode": episode, "shot": shot_id, "key": key, "quality": quality,
               "out": str(out), "page": str(page), "clips": clips, "ledger": ledger.summary()}
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    return summary


def write_page(path: Path, title: str, key: str, clips: list[dict]) -> Path:
    """Self-contained page: the clips in a grid, playing in sync, with exposure-by-exposure stepping."""
    total = sum(c["seconds"] for c in clips) or 1.0
    kbps = int(min(3200, PAGE_VIDEO_BYTES * 8 / total / 1000))
    tiles = []
    for clip in clips:
        small = Path(clip["video"]).with_name(Path(clip["video"]).stem + "_720p.mp4")
        _run([_ffmpeg(), "-v", "error", "-y", "-i", clip["video"], "-vf", "scale=1280:-2:flags=lanczos",
              "-c:v", "libx264", "-preset", "slow", "-b:v", f"{kbps}k", "-maxrate", f"{int(kbps * 1.4)}k",
              "-bufsize", f"{kbps * 2}k", "-an", "-movflags", "+faststart", str(small)], timeout=900)
        data = base64.b64encode(small.read_bytes()).decode()
        value = clip["value"]
        shown = f"{value} ({value * 100:g}%)" if isinstance(value, (int, float)) and 0 <= value <= 1 else str(value)
        tiles.append(f"""<figure><div class="frame"><video muted playsinline preload="auto"
 src="data:video/mp4;base64,{data}"></video></div>
<figcaption><b>{html.escape(key)} = {html.escape(shown)}</b><span>{html.escape(clip['video'])}</span></figcaption></figure>""")
    step = 1.0 / (clips[0]["fps"] if clips else 12)
    path.write_text(f"""<!doctype html><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>
 body {{ font: 15px/1.45 system-ui, sans-serif; margin: 16px; color: #222; background: #f6f3ee; }}
 h1 {{ font-size: 19px; margin: 0 0 4px; }} p {{ margin: 4px 0 10px; color: #555; }}
 .bar {{ display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin: 10px 0 14px; position: sticky; top: 0;
        background: #f6f3ee; padding: 6px 0; z-index: 2; }}
 button, select {{ font: inherit; padding: 5px 11px; border: 1px solid #b9b2a6; border-radius: 6px; background: #fff; cursor: pointer; }}
 .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap: 12px; }}
 .grid.solo {{ grid-template-columns: 1fr; }} .grid.solo figure:not(.picked) {{ display: none; }}
 figure {{ margin: 0; background: #fff; border-radius: 8px; overflow: hidden; border: 1px solid #ddd6ca; cursor: zoom-in; }}
 .grid.solo figure {{ cursor: zoom-out; }}
 .frame {{ overflow: hidden; aspect-ratio: 16 / 9; background: #000; }}
 video {{ width: 100%; height: 100%; display: block; transform-origin: 50% 32%; }}
 .zoom video {{ transform: scale(2.2); }}
 figcaption {{ padding: 6px 10px 8px; }} figcaption span {{ display: block; color: #777; font-size: 12px; word-break: break-all; }}
</style>
<h1>{html.escape(title)}</h1>
<p>Same shot, same performance, same render seed: only <b>{html.escape(key)}</b> differs. Silent, {step * 1000:.0f} ms per
exposure. Click a clip to view it alone; click again for the grid. Embedded copies are 720p; full-size files are listed under each clip.</p>
<div class="bar">
 <button id="play">Play / pause</button><button id="restart">Restart</button>
 <button id="back">&#9664; one exposure</button><button id="fwd">one exposure &#9654;</button>
 <label>Speed <select id="speed"><option value="1">1x</option><option value="0.5">0.5x</option><option value="0.25">0.25x</option></select></label>
 <label><input type="checkbox" id="zoom"> Zoom 2.2x</label>
</div>
<div class="grid" id="grid">{''.join(tiles)}</div>
<script>
 const vids = [...document.querySelectorAll('video')], grid = document.getElementById('grid'), STEP = {step};
 const all = f => vids.forEach(f);
 const seek = t => all(v => {{ v.currentTime = Math.max(0, Math.min(t, v.duration - 0.001 || t)); }});
 const playAll = () => all(v => v.play());
 document.getElementById('play').onclick = () => vids[0].paused ? playAll() : all(v => v.pause());
 document.getElementById('restart').onclick = () => {{ seek(0); playAll(); }};
 const stepBy = d => {{ all(v => v.pause()); seek(Math.round(vids[0].currentTime / STEP + d) * STEP + STEP / 2); }};
 document.getElementById('back').onclick = () => stepBy(-1);
 document.getElementById('fwd').onclick = () => stepBy(1);
 document.getElementById('speed').onchange = e => all(v => {{ v.playbackRate = +e.target.value; }});
 document.getElementById('zoom').onchange = e => grid.classList.toggle('zoom', e.target.checked);
 vids[0].addEventListener('ended', () => {{ seek(0); playAll(); }});   // loop together, stay in sync
 document.querySelectorAll('figure').forEach(f => f.onclick = () => {{
   const on = grid.classList.contains('solo') && f.classList.contains('picked');
   document.querySelectorAll('figure').forEach(x => x.classList.remove('picked'));
   grid.classList.toggle('solo', !on); if (!on) f.classList.add('picked');
 }});
 playAll();
</script>""")
    return path
