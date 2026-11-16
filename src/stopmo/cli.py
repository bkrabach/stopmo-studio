"""`stopmo` command line: a thin wrapper over the stopmo library."""
from __future__ import annotations

import json
from pathlib import Path

import click

from . import build as build_mod
from . import setup as setup_mod


@click.group()
def main() -> None:
    """Scripted stop-motion-style films, rendered with headless Blender."""


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Machine-readable readiness report.")
def doctor(as_json: bool) -> None:
    """Check the source checkout and local tools; never install or download."""
    report = setup_mod.doctor()
    if as_json:
        click.echo(json.dumps(report, indent=2))
    else:
        for check in report["checks"]:
            status = "OK" if check["ok"] else ("MISSING" if check["required"] else "OPTIONAL")
            click.echo(f"{status:8s} {check['name']}: {check['detail']}")
            if check["fix"]:
                click.echo(f"         {check['fix']}")
        click.echo("Ready for a base render." if report["ok"] else "Fix the required checks before rendering.")
    if not report["ok"]:
        raise click.exceptions.Exit(1)


@main.command("init")
@click.argument("path", type=click.Path(path_type=Path))
def init_project(path: Path) -> None:
    """Create a NEW 2-second toy project: motion, music and SFX, no dialogue."""
    try:
        created = setup_mod.init_project(path)
    except (ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    import shlex
    click.echo(f"Created {created}")
    click.echo(f"Next: stopmo build {shlex.quote(str(created))} hello --quality draft --jobs 1")
    click.echo("No speech models needed. Optional dialogue: install --kokoro with "
               "tools/install_voice_tools.sh, add voice: {kokoro: bm_george} to "
               "characters/hero.yaml, then a who: hero / say: ... beat.")
    click.echo("The project's .gitignore excludes its contents; review it before publishing anything.")


def _overrides(settings: tuple[str, ...]) -> dict:
    """('a.b=1', ...) -> {'a.b': 1}; values are read as YAML, so numbers and true/false work."""
    import yaml

    out = {}
    for item in settings:
        key, sep, value = item.partition("=")
        if not sep or not key.strip():
            raise click.BadParameter(f"expected KEY=VALUE, got {item!r}", param_hint="--set")
        out[key.strip()] = yaml.safe_load(value)
    return out


@main.command()
@click.argument("show_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument("episode")
@click.option("--quality", type=click.Choice(["draft", "preview", "final"]), default="preview", show_default=True)
@click.option("--shot", "only", multiple=True, help="Build only these shot ids (repeatable).")
@click.option("--jobs", default=2, show_default=True, help="Shots rendered in parallel.")
@click.option("--force", is_flag=True, help="Ignore the shot cache.")
@click.option("--stills", type=int, default=None, help="Render only every Nth exposure (no video): a fast look at a shot.")
@click.option("--save-blend", is_flag=True, help="Keep a .blend per shot for inspection in the Blender UI.")
@click.option("--reuse", is_flag=True, help="Re-assemble from finished renders on disk, even if stale (re-grade, re-mix, re-encode).")
@click.option("--set", "settings", multiple=True, metavar="KEY=VALUE",
              help="Override a show setting for this build, e.g. characters.hero.voice.rate=0.95.")
@click.option("--tag", default=None, help="Build into out/<show>/<episode>/<quality>-TAG/ (keeps comparison builds apart).")
def build(show_dir: Path, episode: str, quality: str, only: tuple[str, ...], jobs: int, force: bool,
          stills: int | None, save_blend: bool, reuse: bool, settings: tuple[str, ...], tag: str | None) -> None:
    """Build EPISODE of the show in SHOW_DIR into out/<show>/<episode>/<quality>/."""
    summary = build_mod.build_episode(
        show_dir, episode, quality=quality, only=list(only) or None, jobs=jobs, force=force,
        frames={"every": stills} if stills else None, save_blend=save_blend, reuse=reuse,
        overrides=_overrides(settings), tag=tag,
    )
    ledger = summary["ledger"]
    click.echo(f"exposures: {summary['exposures']}   wall: {ledger['wall_seconds']} s   api cost: $0.00")
    for name, seconds in ledger["by_stage"].items():
        click.echo(f"  {name:12s} {seconds:8.1f} s")
    for shot in summary["shots"]:
        render = shot["render"]
        click.echo(f"  shot {shot['id']}: {shot['frames']} exposures, bake {shot.get('bake_s')} s, "
                   f"render {render['seconds']} s ({render.get('per_frame', 0)} s/frame)")
    if "video" in summary:
        click.echo(f"film: {summary['seconds_of_film']} s -> {summary['video']}")
        _sound_report(summary.get("sound", {}))
    else:
        click.echo(f"stills in {summary['out']}/<shot>/frames")


def _sound_report(sound: dict) -> None:
    """Print measured delivery levels and every recognition warning."""
    if not sound:
        return
    def value(key: str) -> str:
        number = sound.get(key)
        return "n/a" if number is None else f"{number:.1f}"
    click.echo(f"sound: {value('integrated_lufs')} LUFS  {value('true_peak_db')} dBTP  "
               f"voice/music >= {value('voice_over_music_db')} dB")
    for line in sound.get("mismatched_lines", []):
        click.echo(f"WARNING a recogniser misheard {line['text']!r} as {line.get('heard')!r}")
    if sound.get("duck_at_limit"):
        click.echo("WARNING music duck reached max_db; inspect the measured margin.")
    if sound.get("has_dialogue", True) and not sound.get("transcriber_available"):
        click.echo("WARNING local transcription not installed; script checks skipped.")
    finished = sound.get("finished_transcript")
    if finished and not finished["match"]:
        click.echo(f"WARNING finished mix transcript: {finished['text']!r}")


@main.command()
@click.argument("show_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument("episode")
@click.option("--engine", "engines", multiple=True, help="Also record every line with this engine "
              "(dramabox, voxcpm, breeze, higgs); repeatable.")
@click.option("--takes", default=1, show_default=True, help="Takes per extra engine.")
def voices(show_dir: Path, episode: str, engines: tuple[str, ...], takes: int) -> None:
    """Record an episode's lines (as cast, plus other engines to compare) into a listening page. No rendering."""
    from .voices import audition

    try:
        summary = audition(show_dir, episode, list(engines), takes=takes)
    except ValueError as exc:
        raise click.BadParameter(str(exc), param_hint="--engine") from exc
    for line in summary["lines"]:
        cast = line["versions"][0]
        flag = "" if cast["match"] is not False else f"   <- recogniser heard {cast['heard']!r}"
        click.echo(f"  {line['who']}: {line['text']!r}  [{cast['engine']}, take {cast['take']}, {cast['seconds']} s]{flag}")
    click.echo(f"listen: {summary['page']}")


@main.command()
@click.argument("show_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument("episode")
@click.option("--shot", required=True, help="Shot id to render.")
@click.option("--set", "setting", required=True, metavar="KEY=V1,V2,...",
              help="Style setting and the values to try, e.g. boil=0,0.3,1 or grade.grain=0,0.02.")
@click.option("--seconds", default=5.0, show_default=True, help="Length of each clip, from the start of the shot.")
@click.option("--quality", type=click.Choice(["draft", "preview", "final"]), default="preview", show_default=True)
@click.option("--jobs", default=2, show_default=True, help="Variants rendered in parallel.")
@click.option("--force", is_flag=True, help="Ignore the shot cache.")
def sweep(show_dir: Path, episode: str, shot: str, setting: str, seconds: float, quality: str, jobs: int,
          force: bool) -> None:
    """Render one shot at several values of one style setting: silent clips plus a comparison page."""
    from . import sweep as sweep_mod

    try:
        key, values = sweep_mod.parse_setting(setting)
    except ValueError as exc:
        raise click.BadParameter(str(exc), param_hint="--set") from exc
    summary = sweep_mod.sweep(show_dir, episode, shot, key, values, seconds=seconds, quality=quality,
                              jobs=jobs, force=force)
    for clip in summary["clips"]:
        click.echo(f"  {key}={clip['value']}: {clip['exposures']} exposures, render {clip['render_seconds']} s"
                   f" -> {clip['video']}")
    click.echo(f"wall: {summary['ledger']['wall_seconds']} s   api cost: $0.00")
    click.echo(f"compare: {summary['page']}")


@main.command()
@click.argument("show_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
def info(show_dir: Path) -> None:
    """List a show's characters and episodes."""
    show = build_mod.load_show(show_dir)
    click.echo(f"{show.get('title', show_dir.name)}  (style: {show['style'].get('name')})")
    click.echo("characters: " + ", ".join(show["characters"]))
    click.echo("episodes:   " + ", ".join(p.stem for p in sorted((show_dir / "episodes").glob("*.yaml"))))


@main.command()
@click.argument("summary_json", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def report(summary_json: Path) -> None:
    """Print the time/cost ledger of a finished build."""
    click.echo(json.dumps(json.loads(summary_json.read_text())["ledger"], indent=1))


@main.command()
@click.argument("show_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument("out", type=click.Path(dir_okay=False, path_type=Path))
@click.argument("names", nargs=-1)
def lineup(show_dir: Path, out: Path, names: tuple[str, ...]) -> None:
    """Render the show's characters standing in a row, in the show's style, to OUT (a png)."""
    import subprocess
    import tempfile

    show = build_mod.load_show(show_dir)
    with tempfile.TemporaryDirectory(prefix="stopmo-lineup-") as folder:
        plan = Path(folder) / "show.json"
        plan.write_text(json.dumps(show))
        subprocess.run([str(build_mod.ROOT / "tools" / "bl.sh"), str(build_mod.ROOT / "tools" / "lineup.py"), str(plan),
                        str(out.resolve()), *names], check=True, capture_output=True, text=True)
    click.echo(str(out))


if __name__ == "__main__":
    main()
