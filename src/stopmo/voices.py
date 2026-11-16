"""Record an episode's lines and lay them out for listening: which engine, which take.

No Blender involved. The lines are recorded exactly as a build would record them (same cache), so
running this first also means the build finds every line already recorded.
"""
from __future__ import annotations

import base64
import html
import json
from pathlib import Path

from . import audio, build
from .ledger import Ledger


def _player(wav: Path) -> str:
    """An <audio> element with the wav embedded as AAC."""
    m4a = wav.with_suffix(".m4a")
    audio._run([audio._ffmpeg(), "-v", "error", "-y", "-i", str(wav), "-c:a", "aac", "-b:a", "96k", str(m4a)])
    data = base64.b64encode(m4a.read_bytes()).decode("ascii")
    m4a.unlink()
    return f'<audio controls preload="none" src="data:audio/mp4;base64,{data}"></audio>'


def audition(show_dir: Path, episode: str, engines: list[str] | tuple[str, ...] = (), takes: int = 1,
             out_root: Path | None = None) -> dict:
    """Record every spoken line of an episode as cast, plus `takes` takes with each extra engine.

    Writes out/<show>/<episode>/voices/audition.html (one block per line, a player per version) and
    returns {"page", "lines": [{who, text, versions: [{label, engine, take, wav, seconds, match, heard, ...}]}]}.
    To use a version in the film, put `engine: NAME` and/or `take: N` in that line's `acting:` block.
    """
    for engine in engines:
        if engine not in audio.ENGINES:
            raise ValueError(f"unknown engine {engine!r}; use {', '.join(audio.ENGINES)}")
    if engines and not audio.acting_available():
        raise RuntimeError("Acting voices are not installed. On Apple Silicon, review model licenses, then run "
                           "tools/install_voice_tools.sh --acting --accept-model-licenses.")
    ledger = Ledger()
    show_dir = Path(show_dir).resolve()
    show = build.load_show(show_dir)
    ep = build.load_episode(show, episode)
    root = Path(out_root or build.ROOT / "out")
    out = root / show_dir.name / episode / "voices"
    cache = root / "cache"
    out.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    fps = float(show["style"].get("fps", 12))

    wanted = []  # (beat, label, voice)
    for beat in build.say_beats(ep["shots"]):
        cast = build.line_voice(show, beat)
        wanted.append((beat, "as cast", cast))
        for engine in engines:
            for take in range(1, takes + 1):
                single = {k: v for k, v in cast.items() if k != "fallback"}
                single.update(engine=engine, takes=1, line={**cast.get("line", {}), "take": take})
                wanted.append((beat, f"{engine}, take {take}", single))
    recorded = build.record_lines([(beat["say"], voice) for beat, _label, voice in wanted], fps, cache, ledger)

    lines: list[dict] = []
    for (beat, label, voice), line in zip(wanted, recorded):
        if label == "as cast":
            lines.append({"who": beat["who"], "text": beat["say"], "acting": beat.get("acting", {}), "versions": []})
        take = line.get("take") or {}
        lines[-1]["versions"].append({
            "label": label, "engine": take.get("engine", "kokoro"), "take": take.get("take"), "wav": line["wav"],
            "seconds": round(line["seconds"], 2), "match": line.get("match"), "heard": line.get("heard"),
            "attempts": take.get("attempts", 1), "accepted": take.get("accepted", True)})
    page = out / "audition.html"
    page.write_text(_page(f"{show_dir.name} / {episode}", lines))
    result = {"show": show_dir.name, "episode": episode, "page": str(page), "lines": lines, "ledger": ledger.summary()}
    (out / "audition.json").write_text(json.dumps(result, indent=1))
    return result


def _page(title: str, lines: list[dict]) -> str:
    blocks = []
    for n, line in enumerate(lines, 1):
        rows = []
        for v in line["versions"]:
            notes = [f"{v['seconds']} s"]
            if v["label"] == "as cast":
                notes.append(f"{v['engine']}, take {v['take']}" if v["take"] else v["engine"])
                if v["attempts"] > 1:
                    notes.append(f"{v['attempts']} takes tried")
            if v["match"] is False:
                notes.append(f"<span class=bad>recogniser heard: {html.escape(v['heard'] or '')}</span>")
            if not v["accepted"]:
                notes.append("<span class=bad>no take passed the checks; closest kept</span>")
            rows.append(f"<tr><td class=e><b>{html.escape(v['label'])}</b></td><td>{_player(Path(v['wav']))}"
                        f"<div class=m>{' · '.join(notes)}</div></td></tr>")
        acting = line["acting"]
        direction = acting.get("direction") or acting.get("stage") or "no direction given"
        extras = ", ".join(f"{k}: {acting[k]}" for k in ("emotion", "pace", "event", "style") if acting.get(k))
        blocks.append(f"<section><h2>{n}. {html.escape(line['who'])}: “{html.escape(line['text'])}”</h2>"
                      f"<p class=d><b>Direction:</b> {html.escape(direction)}{' (' + html.escape(extras) + ')' if extras else ''}</p>"
                      f"<table>{''.join(rows)}</table></section>")
    return f"""<!doctype html><meta charset="utf-8"><title>Voices: {html.escape(title)}</title>
<style>
 body {{ font: 15px/1.45 system-ui, sans-serif; margin: 20px auto; max-width: 900px; padding: 0 16px; color: #222; background: #f6f3ee; }}
 h1 {{ font-size: 21px; }} h2 {{ font-size: 17px; margin: 24px 0 2px; }} .d {{ color: #555; margin: 2px 0 8px; }}
 table {{ border-collapse: collapse; width: 100%; background: #fff; }} td {{ border: 1px solid #ddd6ca; padding: 6px 9px; vertical-align: top; }}
 .e {{ width: 170px; }} .m {{ color: #777; font-size: 12px; }} .bad {{ color: #a33; }} audio {{ width: 100%; height: 34px; }}
</style>
<h1>Voices: {html.escape(title)}</h1>
<p>Every spoken line as it is in the film (“as cast”), then any other engines and takes asked for. To use a different version
in the film, add <code>engine: NAME</code> and/or <code>take: N</code> to that line's <code>acting:</code> block in the episode file
and rebuild; only that line is re-recorded and only its shot is re-rendered.</p>
{''.join(blocks)}"""
