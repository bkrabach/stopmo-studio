"""Episode builder: script -> voices -> lip-sync -> Blender shots -> sound mix -> video.

Layout of a show on disk:

    shows/<show>/show.yaml               title, style, default set, music
    shows/<show>/characters/<name>.yaml  puppet spec + voice
    shows/<show>/episodes/<ep>.yaml      shots and beats
    styles/<style>.yaml                  style packs shared by every show

Everything is cached by content hash under out/, so changing one line of
dialogue re-records one line and re-renders one shot.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from . import audio, encode, lipsync, overlay, sfx, transcribe
from .ledger import Ledger
from .setup import blender_executable, safe_component

ROOT = Path(__file__).resolve().parents[2]


def _hash(*parts) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(json.dumps(part, sort_keys=True, default=str).encode())
    return h.hexdigest()[:16]


def code_hash() -> str:
    """Hash of the Blender-side source: any change there invalidates rendered shots."""
    h = hashlib.sha256()
    for path in sorted((ROOT / "src" / "stopmo_bl").rglob("*.py")):
        h.update(path.read_bytes())
    return h.hexdigest()[:16]


def _merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for key, val in (extra or {}).items():
        out[key] = _merge(out[key], val) if isinstance(val, dict) and isinstance(out.get(key), dict) else val
    return out


# ------------------------------------------------------------------ load ----
def load_show(show_dir: Path) -> dict:
    """Read show.yaml, its style pack and every character file."""
    show_dir = Path(show_dir).resolve()
    safe_component(show_dir.name, "show name")
    show = yaml.safe_load((show_dir / "show.yaml").read_text())
    style = show.get("style", "clay")
    if isinstance(style, str):
        safe_component(style, "style name")
        style = yaml.safe_load((ROOT / "styles" / f"{style}.yaml").read_text())
    elif "extends" in style:
        safe_component(style["extends"], "style name")
        style = _merge(yaml.safe_load((ROOT / "styles" / f"{style['extends']}.yaml").read_text()), style)
    show["style"] = style
    show["characters"] = {
        path.stem: yaml.safe_load(path.read_text()) for path in sorted((show_dir / "characters").glob("*.yaml"))
    }
    show["dir"] = str(show_dir)
    return show


def load_episode(show: dict, episode: str) -> dict:
    safe_component(episode, "episode")
    path = Path(show["dir"]) / "episodes" / f"{episode}.yaml"
    ep = yaml.safe_load(path.read_text())
    ep["id"] = episode
    for i, shot in enumerate(ep["shots"]):
        shot.setdefault("id", f"s{i + 1:02d}")
        safe_component(shot["id"], "shot id")
        if "set" not in shot and "title" not in shot:
            shot["set"] = show.get("set", "studio")
    return ep


# ----------------------------------------------------------------- voice ----
ACTING_FIELDS = ("direction", "stage", "emotion", "pace", "event", "style")  # how a line is to be played
VOICE_FIELDS = ("engine", "event_engine", "fallback", "ref_audio", "ref_text", "who", "kokoro", "rate", "pitch", "takes")


def line_voice(show: dict, beat: dict) -> dict:
    """Everything that decides how one `say` beat sounds (and so its cache key).

    The character's `voice:` block names the acting engine and the reference clip it copies; the
    beat's `acting:` block is the direction for this line and may name another engine or a take
    number. Explicit acting engines require the acting environment; a missing engine
    never silently changes the cast to a Kokoro stand-in.
    """
    voice = dict(show["characters"][beat["who"]].get("voice") or {})
    unknown = set(voice) - set(VOICE_FIELDS)
    if unknown:
        raise ValueError(f"{beat['who']}: unknown voice settings {sorted(unknown)}; use {', '.join(VOICE_FIELDS)}")
    acting = dict(beat.get("acting") or {})
    unknown = set(acting) - {*ACTING_FIELDS, "engine", "take"}
    if unknown:
        raise ValueError(f"line {beat['say']!r}: unknown acting fields {sorted(unknown)}; "
                         f"use {', '.join(ACTING_FIELDS)}, engine, take")
    if "rate" in beat:
        voice["rate"] = beat["rate"]
    if acting.get("engine"):
        voice["engine"] = acting.pop("engine")
    elif acting.get("event") and voice.get("event_engine"):
        voice["engine"] = voice["event_engine"]
    if not voice.get("engine"):
        return {"kokoro": voice.get("kokoro", "bm_george"), "rate": voice.get("rate", 1.0), "pitch": voice.get("pitch", 0.0)}
    if voice["engine"] not in audio.ENGINES:
        raise ValueError(f"Unknown acting engine {voice['engine']!r}; use {', '.join(audio.ENGINES)}")
    if not audio.acting_available():
        raise RuntimeError("Configured acting engine is unavailable. Review model licenses, then run "
                           "tools/install_voice_tools.sh --acting --accept-model-licenses on Apple Silicon. "
                           "Or explicitly remove engine/event_engine and acting.engine to choose Kokoro "
                           "(tools/install_voice_tools.sh --kokoro). No substitute voice was generated.")
    if not voice.get("ref_audio") or not voice.get("ref_text"):
        raise ValueError("An acting voice needs ref_audio and ref_text. Supply a permitted reference "
                         "recording, or install Kokoro to synthesize the missing reference.")
    ref = Path(voice["ref_audio"])
    ref = ref if ref.is_absolute() else Path(show["dir"]) / ref
    if not ref.is_file():  # first use of a character: make the clip the engines will copy
        audio.synthesize(" ".join(voice["ref_text"].split()), ref, voice=voice.get("kokoro", "bm_george"))
    voice["ref_audio"] = str(ref)
    voice["ref_sha"] = hashlib.sha256(ref.read_bytes()).hexdigest()[:16]  # a new clip means new takes
    voice["ref_text"] = " ".join(str(voice["ref_text"]).split())
    voice.pop("event_engine", None)
    if voice.get("fallback") == voice["engine"]:
        voice.pop("fallback")
    voice["line"] = acting
    return voice


def _line_paths(text: str, voice: dict, fps: float, lip_backend: str, cache: Path) -> tuple[Path, Path]:
    key = _hash(audio.HANDLING_VERSION, text, voice, fps, lip_backend)
    return cache / f"line_{key}.wav", cache / f"line_{key}.json"


def take_lines(items: list[tuple[str, dict, Path]], ledger: Ledger) -> dict[Path, dict]:
    """Record acted lines the way a session does: a take of every line, check, re-take the misses.

    items: (text, voice, wav to write). A take is accepted when the recogniser hears the scripted
    words (when one is installed) and the line is not implausibly long. Each line gets up to
    `voice["takes"]` (default 3) tries with its engine, then 2 with `voice["fallback"]`; if nothing
    passes, the closest take is kept and reported. All lines waiting on the same engine are spoken
    in one batch, so each model loads once per round.
    Returns {wav: {seconds, take: {engine, take, attempts, accepted, tried: [...]}}}.
    """
    state = []
    for text, voice, wav in items:
        line = dict(voice["line"])
        first = int(line.pop("take", 1))
        line.update(text=text, seconds=audio.expected_seconds(text, line.get("pace", "medium"), line.get("event")))
        plan = [(voice["engine"], first + n) for n in range(int(voice.get("takes", 3)))]
        plan += [(voice["fallback"], n) for n in (1, 2)] if voice.get("fallback") else []
        state.append({"text": text, "voice": voice, "wav": Path(wav), "line": line, "plan": plan, "tried": [], "best": None,
                      "character": {k: voice[k] for k in ("ref_audio", "ref_text", "who") if voice.get(k)}})
    pending = list(state)
    round_no = 0
    while pending:
        batches: dict[str, list] = {}
        for item in pending:
            batches.setdefault(item["plan"][len(item["tried"])][0], []).append(item)
        for engine, group in batches.items():
            jobs = []
            for item in group:
                take = item["plan"][len(item["tried"])][1]
                # named by engine and take, so a recording session that was interrupted picks its takes up again
                item["raw"] = item["wav"].with_name(f"{item['wav'].stem}.{engine}.t{take}.raw.wav")
                jobs.append({"out": str(item["raw"]), "line": item["line"], "character": item["character"],
                             "seed": 1000 * take + len(item["text"])})
            with ledger.stage("acting", engine=engine, lines=len(jobs)):
                done = audio.act(engine, jobs, group[0]["wav"].parent)
            for item in group:
                _judge_take(item, engine, done.get(str(item["raw"])), round_no)
                ledger.count("takes")
        pending = [i for i in pending if i["tried"][-1]["problems"] and len(i["tried"]) < len(i["plan"])]
        round_no += 1
    out = {}
    for item in state:
        best = item["best"]
        best["file"].replace(item["wav"])
        for leftover in [*item["wav"].parent.glob(f"{item['wav'].stem}.r*.wav"),
                         *item["wav"].parent.glob(f"{item['wav'].stem}.*.raw.wav")]:
            leftover.unlink()
        out[item["wav"]] = {"seconds": best["seconds"], "take": {
            "engine": best["engine"], "take": best["take"], "attempts": len(item["tried"]),
            "accepted": not best["problems"], "tried": item["tried"]}}
    return out


def _judge_take(item: dict, engine: str, info: dict | None, round_no: int) -> None:
    """Finish one raw take, check it, and remember it if it is the best so far."""
    take = item["plan"][len(item["tried"])][1]
    trial = item["wav"].with_name(f"{item['wav'].stem}.r{round_no}.wav")
    problems, seconds, wrong = [], 0.0, 99
    if info is None or not item["raw"].is_file():
        problems.append("the engine produced no audio")
    else:
        seconds = audio.finish_take(item["raw"], trial, rate=item["voice"].get("rate", 1.0), pitch=item["voice"].get("pitch", 0.0))
        limit = item["line"]["seconds"] * 2.0 + 1.0
        if seconds > limit:
            problems.append(f"{seconds:.1f} s long (limit {limit:.1f} s)")
        wrong = 0
        if transcribe.available():
            heard = transcribe.transcribe(trial)["text"]
            check = transcribe.compare(item["text"], heard)
            wrong = len(check["missing"]) + len(check["extra"])
            if not check["match"]:
                problems.append(f"heard {heard!r}")
    item["tried"].append({"engine": engine, "take": take, "seconds": round(seconds, 2), "problems": problems})
    score = (bool(problems), wrong, seconds)
    if seconds and (item["best"] is None or score < item["best"]["score"]):
        item["best"] = {"score": score, "file": trial, "seconds": seconds, "engine": engine, "take": take, "problems": problems}
    if item["best"] is None:
        raise RuntimeError(f"no usable take of {item['text']!r} from {engine}; see the acting environment's errors")


def _finish_line(text: str, wav: Path, meta: Path, seconds: float, take: dict | None, fps: float,
                 lip_backend: str, ledger: Ledger) -> dict:
    """Mouth cues + transcript for a recorded line; writes and returns its metadata."""
    with ledger.stage("lipsync", text=text[:40]):
        cues = lipsync.quantize(lipsync.mouth_cues(wav, text, backend=lip_backend), fps, min_hold=1)
    frames = int(math.ceil(seconds * fps))
    if not cues or cues[-1][1] != "X":
        cues = list(cues) + [(frames, "X")]  # always close the mouth at the end of the line
    line = {"wav": str(wav), "text": text, "seconds": seconds, "frames": frames, "cues": [list(c) for c in cues],
            "heard": None, "match": None}
    if take:
        line["take"] = take
    if transcribe.available():
        with ledger.stage("transcribe", text=text[:40]):
            _check_line(line, text, wav)
    meta.write_text(json.dumps(line))
    ledger.count("lines")
    return line


def record_lines(items: list[tuple[str, dict]], fps: float, cache: Path, ledger: Ledger, lip_backend="auto") -> list[dict]:
    """Speech + mouth cues for a set of lines (cached per line). -> [{wav, seconds, frames, cues, ...}]

    Lines that are not in the cache are recorded together: acted lines in batches per engine
    (see take_lines), Kokoro lines one by one.
    """
    paths = [_line_paths(text, voice, fps, lip_backend, cache) for text, voice in items]
    todo = {}
    for (text, voice), (wav, meta) in zip(items, paths):
        if wav.exists() and meta.exists():
            ledger.hit("line")
        elif wav not in todo:
            todo[wav] = (text, voice, meta)
    acted = take_lines([(t, v, wav) for wav, (t, v, _m) in todo.items() if v.get("engine")], ledger)
    for wav, (text, voice, meta) in todo.items():
        if voice.get("engine"):
            _finish_line(text, wav, meta, acted[wav]["seconds"], acted[wav]["take"], fps, lip_backend, ledger)
        else:
            with ledger.stage("tts", text=text[:40]):
                seconds = audio.synthesize(text, wav, voice=voice.get("kokoro", "bm_george"),
                                           rate=voice.get("rate", 1.0), pitch=voice.get("pitch", 0.0))
            _finish_line(text, wav, meta, seconds, None, fps, lip_backend, ledger)
    return [json.loads(meta.read_text()) for _wav, meta in paths]


def record_line(text: str, voice: dict, fps: float, cache: Path, ledger: Ledger, lip_backend="auto") -> dict:
    """One line; see record_lines."""
    return record_lines([(text, voice)], fps, cache, ledger, lip_backend)[0]


def _check_line(line: dict, text: str, wav: Path) -> None:
    """Attach recognition and wall time to cached line metadata."""
    started = time.monotonic()
    heard = transcribe.transcribe(wav)
    line.update(heard=heard["text"], words=heard["words"],
                match=transcribe.compare(text, heard["text"])["match"],
                transcribe_seconds=round(time.monotonic() - started, 3))


def say_beats(shots: list[dict]) -> list[dict]:
    return [beat for shot in shots for beat in shot.get("beats", []) if "say" in beat]


# ------------------------------------------------------------------ plan ----
def make_plan(show: dict, ep: dict, shot: dict, opts: dict, cache: Path, ledger: Ledger) -> dict:
    """Everything Blender needs for one shot, with dialogue already recorded and timed."""
    style = show["style"]
    fps = float(style.get("fps", 12))
    shot = json.loads(json.dumps(shot))  # deep copy
    for beat in shot.get("beats", []):
        if "say" in beat:
            beat["line"] = record_line(beat["say"], line_voice(show, beat), fps, cache, ledger, opts.get("lipsync", "auto"))
            beat.pop("acting", None)  # direction for the voice; Blender does not need it
    cast = shot.get("cast", {})
    characters = {}
    for name, entry in cast.items():
        spec = dict(show["characters"][name])
        spec.pop("voice", None)
        extra = (entry or {}).pop("decor", None)  # per-shot additions: a smudge of chocolate, a hat
        if extra:
            spec["decor"] = list(spec.get("decor", [])) + list(extra)
        characters[name] = spec
    return {
        "shot": shot,
        "style": style,
        "characters": characters,
        "quality": opts.get("quality", "preview"),
        "resolution": opts.get("resolution", [1920, 1080]),
        "samples": opts.get("samples"),
        "seed": ep.get("seed", 0),
        "frames": opts.get("frames"),
        "save_blend": opts.get("save_blend", False),
    }


def render_shot(plan: dict, shot_dir: Path, ledger: Ledger, force=False, reuse=False) -> dict:
    """Run Blender for one shot unless an identical plan was already rendered.

    reuse=True accepts whatever finished render is on disk, even if the script or code changed
    since: use it to re-grade, re-mix or re-encode without spending render time.
    """
    key = _hash(plan, code_hash())
    done = shot_dir / "done.json"
    if done.exists() and not force:
        info = json.loads(done.read_text())
        if info.get("key") == key or reuse:
            ledger.hit("shot")
            return json.loads((shot_dir / "timing.json").read_text())
    if shot_dir.exists():
        shutil.rmtree(shot_dir)
    shot_dir.mkdir(parents=True)
    (shot_dir / "plan.json").write_text(json.dumps(plan, indent=1))
    env = {**os.environ, "STOPMO_SRC": str(ROOT / "src")}
    cmd = [blender_executable(), "--background", "--factory-startup", "--python-exit-code", "1",
           "--python", str(ROOT / "src" / "stopmo_bl" / "director.py"), "--", str(shot_dir / "plan.json")]
    with ledger.stage("blender", shot=plan["shot"]["id"]) as entry:
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
        (shot_dir / "blender.log").write_text(proc.stdout[-200000:] + "\n--- stderr ---\n" + proc.stderr[-20000:])
        if proc.returncode != 0 or not (shot_dir / "timing.json").exists():
            tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-25:])
            raise RuntimeError(f"Blender failed on shot {plan['shot']['id']} (log: {shot_dir / 'blender.log'}):\n{tail}")
        timing = json.loads((shot_dir / "timing.json").read_text())
        entry.update(frames=timing["frames"], **timing["stats"])
    done.write_text(json.dumps({"key": key}))
    ledger.count("shots_rendered")
    ledger.count("frames_rendered", timing["stats"]["render"]["frames"])
    return timing


# ----------------------------------------------------------------- sound ----
def music_envelope(events: list[tuple[float, bool]], duration: float, down: float = 0.12, up: float = 0.5) -> list[tuple[float, float]]:
    """Gain curve for the music from (seconds, on?) events: it cuts out in `down` s and returns over `up` s."""
    points, level = [(0.0, 1.0)], 1.0
    for when, on in sorted(events):
        target = 1.0 if on else 0.0
        if target == level:
            continue
        start = max(when, points[-1][0] + 0.001)
        points += [(start, level), (start + (up if on else down), target)]
        level = target
    end = max(duration, points[-1][0] + 0.001)
    return points + [(end, level)]


def build_sound(ep: dict, show: dict, timings: list[dict], out_wav: Path, cache: Path,
                ledger: Ledger) -> tuple[Path, dict]:
    """Assemble the rendered shot timings and return WAV plus measured sound report."""
    lines, effects, music_events = [], [], []
    offset = 0.0
    cache.mkdir(parents=True, exist_ok=True)
    shots = {shot["id"]: shot for shot in ep["shots"]}
    with ledger.stage("sound"):
        for timing in timings:
            fps = timing["fps"]
            beats = [beat for beat in shots.get(timing.get("shot"), {}).get("beats", []) if "say" in beat]
            for i, line in enumerate(timing.get("audio", [])):
                path = Path(line["wav"])
                meta_path = path.with_suffix(".json")
                meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
                lines.append({**meta, **line, "path": path, "start": offset + (line["frame"] - 1) / fps,
                              "gain": line.get("gain", 1),
                              "text": line.get("text", meta.get("text", beats[i]["say"] if i < len(beats) else ""))})
            for fx in timing.get("sfx", []):
                if fx["kind"] in ("music_off", "music_on"):  # comic silence: the band stops, and starts again
                    music_events.append((offset + (fx["frame"] - 1) / fps, fx["kind"] == "music_on"))
                    continue
                seed = int(fx.get("seed", 0)) % 7
                pitch = float(fx.get("pitch", 0))  # semitones: the same effect a little higher or lower
                wav = cache / (f"sfx_{fx['kind']}_{seed}.wav" if not pitch else f"sfx_{fx['kind']}_{seed}_p{pitch:g}.wav")
                if not wav.exists():
                    sfx.sfx(fx["kind"], wav, seed=seed, pitch=pitch)
                effects.append({"path": wav, "start": offset + (fx["frame"] - 1) / fps, "gain": fx.get("gain", 0.7)})
            offset += timing["frames"] / fps
        music = _merge(show.get("music") or {}, ep.get("music") or {})
        music_track = None
        if music and music.get("style"):
            key = _hash(music, round(offset, 2))
            wav = cache / f"music_{key}.wav"
            if not wav.exists():
                sfx.music(wav, duration=offset, style=music["style"], tempo=music.get("tempo", 108),
                          key=music.get("key", "C"), seed=music.get("seed", 0))
            music_track = {"path": wav, "start": 0.0, "gain": music.get("gain", 0.2)}
            if music_events:
                music_track["envelope"] = music_envelope(music_events, offset)
        report = audio.mix_program(lines, effects, music_track, out_wav, duration=offset, settings=show.get("mix"))
        report["has_dialogue"] = bool(lines)
        report["transcriber_available"] = transcribe.available()
        report["finished_transcript"] = None
        if lines and transcribe.available():
            started = time.monotonic()
            heard = transcribe.transcribe(out_wav)
            script = " ".join(line["text"] for line in sorted(lines, key=lambda line: line["start"]))
            report["finished_transcript"] = {**heard, **transcribe.compare(script, heard["text"]),
                                              "seconds": round(time.monotonic() - started, 3)}
    return Path(out_wav), report


# ----------------------------------------------------------------- build ----
def build_episode(show_dir: Path, episode: str, *, quality="preview", only: list[str] | None = None,
                  jobs: int = 2, force=False, frames=None, out_root: Path | None = None,
                  resolution=None, save_blend=False, reuse=False, overrides: dict | None = None,
                  tag: str | None = None) -> dict:
    """Build an episode end to end. Returns the summary (also written next to the video)."""
    show_dir = Path(show_dir).resolve()
    safe_component(quality, "quality")
    if quality not in ("draft", "preview", "final"):
        raise ValueError("quality must be draft, preview or final")
    if tag is not None:
        safe_component(tag, "tag")
    ledger = Ledger()
    show = load_show(Path(show_dir))
    for dotted, value in (overrides or {}).items():  # e.g. characters.hero.voice.rate = 0.95
        target = show
        *parents, last = dotted.split(".")
        for key in parents:
            target = target.setdefault(key, {})
        target[last] = value
    ep = load_episode(show, episode)
    out = Path(out_root or ROOT / "out") / Path(show_dir).name / episode / (f"{quality}-{tag}" if tag else quality)
    cache = Path(out_root or ROOT / "out") / "cache"
    out.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    opts = {"quality": quality, "frames": frames, "save_blend": save_blend}
    if resolution:
        opts["resolution"] = list(resolution)
    shots = [s for s in ep["shots"] if not only or s["id"] in only]

    with ledger.stage("voices"):
        fps = float(show["style"].get("fps", 12))  # every line of the episode in one session, then the plans
        record_lines([(beat["say"], line_voice(show, beat)) for beat in say_beats(shots)], fps, cache, ledger)
        plans = [make_plan(show, ep, shot, opts, cache, ledger) for shot in shots]

    def run(plan):
        return render_shot(plan, out / plan["shot"]["id"], ledger, force=force, reuse=reuse)

    with ledger.stage("render_all", jobs=jobs):
        with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
            timings = list(pool.map(run, plans))

    summary = {"show": Path(show_dir).name, "episode": episode, "quality": quality, "out": str(out)}
    if frames is None:
        style = show["style"]
        with ledger.stage("encode"):
            videos = []
            for plan, timing in zip(plans, timings):
                shot_dir = out / plan["shot"]["id"]
                frames_dir = shot_dir / "frames"
                if plan["shot"].get("overlay"):  # lettering laid over the picture, as a title is in an edit
                    frames_dir = overlay.apply(frames_dir, shot_dir / "frames_titled", overlay.resolve(plan["shot"]["overlay"], timing), timing["fps"])
                videos.append(encode.frames_to_video(
                    frames_dir, shot_dir / "shot.mp4", fps=timing["fps"], grade=style.get("grade"),
                    out_fps=int(style.get("out_fps", 24))))
            silent = encode.concat(videos, out / "silent.mp4")
        wav, summary["sound"] = build_sound(ep, show, timings, out / "sound.wav", cache, ledger)
        with ledger.stage("mux"):
            final = encode.mux(silent, wav, out / f"{episode}.mp4")
        summary["video"] = str(final)
        summary["seconds_of_film"] = round(sum(t["frames"] / t["fps"] for t in timings), 2)
    summary["exposures"] = sum(t["frames"] for t in timings)
    summary["shots"] = [{"id": t["shot"], "frames": t["frames"], **t["stats"]} for t in timings]
    summary["ledger"] = ledger.summary()
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    return summary
