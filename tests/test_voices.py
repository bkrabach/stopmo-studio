import json
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner

from stopmo import audio, build, transcribe, voices
from stopmo.cli import main
from stopmo.ledger import Ledger


@pytest.mark.parametrize("script,heard", [
    ("Four o'clock, friend!", "4 o’clock friend."),
    ("You didn't. I'm here!", "you did not, I am here"),
    ("It’s 121, and 1.1 times faster.", "It is one hundred and twenty-one and one point one times faster"),
    ("Don't say we can't.", "do not say we can not"),
    ("That's £1,000!", "that is one thousand"),
])
def test_compare_equivalent_words(script, heard):
    assert transcribe.compare(script, heard) == {"match": True, "missing": [], "extra": []}


def test_compare_flags_dropped_changed_reordered_and_repeated_words():
    assert transcribe.compare("Oh friend", "Oh") == {"match": False, "missing": ["friend"], "extra": []}
    result = transcribe.compare("Colorful little tools", "Color your little tools")
    assert not result["match"] and "colorful" in result["missing"]
    assert "color" in result["extra"]
    assert not transcribe.compare("one two", "two one")["match"]
    assert not transcribe.compare("very very good", "very good")["match"]


def test_duck_envelope_merges_short_gaps_and_recovers():
    knots = audio.duck_envelope([(1, 2), (2.6, 3), (5, 6)], 8, -10)
    t, y = np.asarray(knots).T
    low = 10 ** (-10 / 20)
    assert np.all(np.diff(t) > 0)
    assert np.interp(0.7, t, y) == 1
    assert np.interp(.95, t, y) == pytest.approx(low)
    assert np.interp(2.3, t, y) == pytest.approx(low)
    assert np.interp(3.15, t, y) == pytest.approx(low)
    assert np.interp(3.75, t, y) == pytest.approx(1)
    assert np.interp(7, t, y) == 1


def test_duck_overlapping_ramps_and_boundary_speech():
    knots = audio.duck_envelope([(0, 2), (2.8, 4)], 4, -10)
    t, y = np.asarray(knots).T
    assert np.all(np.diff(t) > 0)
    assert np.all((y >= 10 ** (-10 / 20)) & (y <= 1))
    assert y[0] == y[-1] == pytest.approx(10 ** (-10 / 20))
    assert np.interp(2.8, t, y) == pytest.approx(10 ** (-10 / 20))
    assert audio.duck_envelope([], 4, -10) == [(0, 1), (4, 1)]


def test_per_line_rate_override_does_not_mutate_character(tmp_path, monkeypatch):
    calls = []
    def record(text, voice, *args):
        calls.append(voice.copy())
        return {"wav": "test.wav", "seconds": 1, "frames": 12, "cues": []}
    monkeypatch.setattr(build, "record_line", record)
    monkeypatch.setattr(audio, "acting_available", lambda: False)
    show = {"style": {"fps": 12}, "characters": {"actor": {"voice": {"kokoro": "bm_george", "rate": 1.1}}}}
    shot = {"beats": [{"who": "actor", "say": "One", "rate": .95}, {"who": "actor", "say": "Two"}]}
    plan = build.make_plan(show, {}, shot, {}, tmp_path, Ledger())
    assert [voice["rate"] for voice in calls] == [.95, 1.1]
    assert show["characters"]["actor"]["voice"]["rate"] == 1.1
    assert plan["shot"]["beats"][0]["line"]["seconds"] == 1
    assert "line" not in shot["beats"][0]


def _show(tmp_path):
    ref = tmp_path / "ref.wav"
    audio._write_wav(ref, np.ones(480) * .1)
    voice = {"engine": "dramabox", "event_engine": "higgs", "fallback": "voxcpm", "ref_audio": "ref.wav",
             "ref_text": "Good  morning.", "who": "An older Englishman", "kokoro": "bm_george"}
    return {"dir": str(tmp_path), "style": {"fps": 12}, "characters": {"actor": {"voice": voice}}}


def test_line_voice_picks_engine_and_refuses_missing_acting(tmp_path, monkeypatch):
    show = _show(tmp_path)
    monkeypatch.setattr(audio, "acting_available", lambda: True)
    plain = build.line_voice(show, {"who": "actor", "say": "Hello.", "acting": {"direction": "Brightly."}})
    assert plain["engine"] == "dramabox" and plain["fallback"] == "voxcpm" and plain["line"] == {"direction": "Brightly."}
    assert plain["ref_audio"] == str(tmp_path / "ref.wav") and plain["ref_text"] == "Good morning." and plain["ref_sha"]
    sigh = build.line_voice(show, {"who": "actor", "say": "Oh.", "acting": {"event": "sigh"}})
    assert sigh["engine"] == "higgs"                                   # lines with a sound go to the event engine
    named = build.line_voice(show, {"who": "actor", "say": "Oh.", "acting": {"engine": "voxcpm", "take": 2}})
    assert named["engine"] == "voxcpm" and "fallback" not in named and named["line"] == {"take": 2}
    assert build._line_paths("Oh.", plain, 12, "auto", tmp_path) != build._line_paths("Oh.", named, 12, "auto", tmp_path)
    with pytest.raises(ValueError, match="unknown acting fields"):
        build.line_voice(show, {"who": "actor", "say": "Oh.", "acting": {"mood": "sad"}})
    monkeypatch.setattr(audio, "acting_available", lambda: False)
    with pytest.raises(RuntimeError, match="(?i)acting"):
        build.line_voice(show, {"who": "actor", "say": "Oh.", "acting": {"event": "sigh"}})


def test_take_lines_retakes_then_falls_back_and_batches_per_engine(tmp_path, monkeypatch):
    show = _show(tmp_path)
    monkeypatch.setattr(audio, "acting_available", lambda: True)
    batches = []
    def act(engine, jobs, workdir):
        batches.append((engine, [job["line"]["text"] for job in jobs], [job["seed"] for job in jobs]))
        done = {}
        for job in jobs:
            audio._write_wav(Path(job["out"]), 0.05 * np.sin(np.arange(48000) / 20))
            done[job["out"]] = {"seconds": 1.0, "generate_seconds": 0.1}
        return done
    monkeypatch.setattr(audio, "act", act)
    monkeypatch.setattr(transcribe, "available", lambda: True)
    heard = iter(["Good line.", "Bad lime.",            # round 1 (dramabox): first passes, second misheard
                  "Bad lime.", "Bad lime.",             # dramabox takes 2 and 3 of the second line
                  "Bad line."])                         # voxcpm take 1 passes
    monkeypatch.setattr(transcribe, "transcribe", lambda wav: {"text": next(heard), "words": []})
    items = [(text, build.line_voice(show, {"who": "actor", "say": text}), tmp_path / f"{n}.wav")
             for n, text in enumerate(["Good line.", "Bad line."])]
    result = build.take_lines(items, Ledger())
    assert [(engine, texts) for engine, texts, _ in batches] == [
        ("dramabox", ["Good line.", "Bad line."]), ("dramabox", ["Bad line."]), ("dramabox", ["Bad line."]),
        ("voxcpm", ["Bad line."])]
    assert batches[1][2] != batches[2][2]                               # each re-take uses another seed
    good, bad = result[tmp_path / "0.wav"]["take"], result[tmp_path / "1.wav"]["take"]
    assert (good["engine"], good["take"], good["attempts"], good["accepted"]) == ("dramabox", 1, 1, True)
    assert (bad["engine"], bad["take"], bad["attempts"], bad["accepted"]) == ("voxcpm", 1, 4, True)
    assert (tmp_path / "0.wav").is_file() and (tmp_path / "1.wav").is_file()
    assert not list(tmp_path.glob("*.r*.wav"))                          # trial files are cleaned up


def test_take_lines_keeps_closest_take_when_none_passes(tmp_path, monkeypatch):
    show = _show(tmp_path)
    show["characters"]["actor"]["voice"].pop("fallback")
    monkeypatch.setattr(audio, "acting_available", lambda: True)
    def act(engine, jobs, workdir):
        for job in jobs:
            audio._write_wav(Path(job["out"]), 0.05 * np.sin(np.arange(48000) / 20))
        return {job["out"]: {} for job in jobs}
    monkeypatch.setattr(audio, "act", act)
    monkeypatch.setattr(transcribe, "available", lambda: True)
    heard = iter(["One two tree extra words.", "One two tree.", "Nothing alike at all here."])
    monkeypatch.setattr(transcribe, "transcribe", lambda wav: {"text": next(heard), "words": []})
    wav = tmp_path / "x.wav"
    take = build.take_lines([("One two three.", build.line_voice(show, {"who": "actor", "say": "One two three."}), wav)],
                            Ledger())[wav]["take"]
    assert (take["take"], take["attempts"], take["accepted"]) == (2, 3, False)   # fewest wrong words wins


def test_record_line_cache_version_and_transcript(tmp_path, monkeypatch):
    calls = []
    def speak(text, path, **kwargs):
        calls.append(text)
        audio._write_wav(path, np.ones(4800) * .1)
        return .1
    monkeypatch.setattr(audio, "synthesize", speak)
    monkeypatch.setattr(build.lipsync, "mouth_cues", lambda *args, **kwargs: [])
    monkeypatch.setattr(transcribe, "available", lambda: True)
    monkeypatch.setattr(transcribe, "transcribe", lambda wav: {"text": "Hello friend", "words": []})
    first = build.record_line("Hello friend", {}, 12, tmp_path, Ledger())
    assert first["heard"] == "Hello friend" and first["match"] is True
    second = build.record_line("Hello friend", {}, 12, tmp_path, Ledger())
    assert second == first and len(calls) == 1
    twice = build.record_lines([("New line", {}), ("New line", {}), ("Hello friend", {})], 12, tmp_path, Ledger())
    assert len(calls) == 2 and twice[0] == twice[1] and twice[2] == first    # duplicates recorded once
    monkeypatch.setattr(audio, "HANDLING_VERSION", "next")
    third = build.record_line("Hello friend", {}, 12, tmp_path, Ledger())
    assert third["wav"] != first["wav"] and len(calls) == 3


def test_mix_program_common_gain_duck_sfx_and_master(tmp_path, monkeypatch):
    t = np.arange(48000) / 48000
    source = tmp_path / "voice.wav"
    bed = tmp_path / "bed.wav"
    fx = tmp_path / "fx.wav"
    audio._write_wav(source, .1 * np.sin(2 * np.pi * 500 * t))
    audio._write_wav(bed, .2 * np.sin(2 * np.pi * 220 * np.arange(6 * 48000) / 48000))
    audio._write_wav(fx, .01 * np.sin(2 * np.pi * 1000 * t[:2400]))
    original_mix, fx_gains = audio._mix_samples, []
    def capture(tracks, duration=None):
        fx_gains.extend(track["gain"] for track in tracks if track["path"] == fx)
        return original_mix(tracks, duration)
    monkeypatch.setattr(audio, "_mix_samples", capture)
    report = audio.mix_program([
        {"path": source, "start": 1, "text": "one", "match": True},
        {"path": source, "start": 3, "text": "two", "heard": "too", "match": False},
    ], [{"path": fx, "start": 1.5, "gain": .5}, {"path": fx, "start": 2.5, "gain": .5}],
        {"path": bed}, tmp_path / "mixed.wav", duration=6)
    assert report["voice_lufs_after"] == pytest.approx(-17, abs=.3)
    assert report["integrated_lufs"] == pytest.approx(-15, abs=.3)
    assert report["true_peak_db"] <= -1.5
    assert report["voice_over_music_db"] >= 12
    assert report["music_gap_db"] == pytest.approx(-24, abs=.01)
    assert fx_gains == [.325, .5]
    assert report["minimum_line_gap"] == 1
    assert report["mismatched_lines"][0]["text"] == "two"
    assert report["lines"][0]["voice_db"] == report["lines"][1]["voice_db"]
    assert -14 <= report["duck_depth_db"] <= -3.5
    assert audio.wav_duration(tmp_path / "mixed.wav") == 6
    json.dumps(report, allow_nan=False)


def test_build_sound_frame_offsets_and_sfx_reduction(tmp_path, monkeypatch):
    wav = tmp_path / "line.wav"
    audio._write_wav(wav, np.zeros(48000))
    observed = {}
    def mix(lines, effects, music, out_wav, **kwargs):
        observed.update(lines=lines, effects=effects, duration=kwargs["duration"])
        audio._write_wav(out_wav, np.zeros(48000))
        return {}
    monkeypatch.setattr(audio, "mix_program", mix)
    monkeypatch.setattr(transcribe, "available", lambda: False)
    ep = {"shots": [{"id": "a", "beats": [{"say": "One"}]}, {"id": "b", "beats": [{"say": "Two"}]}]}
    timing = [{"shot": "a", "fps": 12, "frames": 24, "audio": [{"wav": str(wav), "frame": 7}]},
              {"shot": "b", "fps": 24, "frames": 48, "audio": [{"wav": str(wav), "frame": 13}]}]
    path, report = build.build_sound(ep, {}, timing, tmp_path / "sound.wav", tmp_path, Ledger())
    assert path.exists()
    assert [line["start"] for line in observed["lines"]] == [.5, 2.5]
    assert [line["text"] for line in observed["lines"]] == ["One", "Two"]
    assert observed["duration"] == 4
    assert report["finished_transcript"] is None


def test_optional_transcriber_missing(monkeypatch):
    monkeypatch.setattr(transcribe, "_tools", lambda: (None, Path("missing.bin")))
    assert not transcribe.available()
    with pytest.raises(RuntimeError, match="install_voice_tools"):
        transcribe.transcribe(Path("no.wav"))


def test_voices_cli_is_thin_and_existing_commands_remain(tmp_path, monkeypatch):
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    for command in ("build", "voices", "sweep", "info", "report"):
        assert command in result.output
    called = []
    monkeypatch.setattr(voices, "audition", lambda *args, **kwargs: called.append((args, kwargs)) or {"lines": [], "page": "test.html"})
    result = CliRunner().invoke(main, ["voices", str(tmp_path),
                                     "check", "--engine", "breeze", "--takes", "2"])
    assert result.exit_code == 0, result.output
    assert called[0][0][2] == ["breeze"] and called[0][1] == {"takes": 2}


def test_page_is_self_contained_and_escapes_script(tmp_path):
    wav = tmp_path / "one.wav"
    audio._write_wav(wav, 0.1 * np.sin(np.arange(4800) / 10))
    version = {"label": "as cast", "engine": "dramabox", "take": 1, "wav": str(wav), "seconds": 0.1, "match": False,
               "heard": "<heard>", "attempts": 2, "accepted": True}
    page = voices._page("show / ep", [{"who": "actor", "text": "<script>", "acting": {"direction": "Low & slow."},
                                       "versions": [version, {**version, "label": "breeze, take 1", "match": True}]}])
    assert page.count("data:audio/mp4;base64,") == 2
    assert "&lt;script&gt;" in page and "<script>" not in page and "&lt;heard&gt;" in page and "Low &amp; slow." in page


def test_engine_table_matches_the_acting_package():
    source = (Path(__file__).resolve().parents[1] / "src/stopmo_voice/engines.py").read_text()
    for engine in audio.ENGINES:
        assert f'"{engine}": (' in source
    assert source.count('": ("') == len(audio.ENGINES) or source.count("ENGINES = {") == 1


def test_build_episode_persists_sound_report_without_blender(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "load_show", lambda path: {"style": {}})
    monkeypatch.setattr(build, "load_episode", lambda show, ep: {"shots": [{"id": "one"}]})
    monkeypatch.setattr(build, "make_plan", lambda show, ep, shot, *args: {"shot": shot})
    monkeypatch.setattr(build, "render_shot", lambda *args, **kwargs: {
        "shot": "one", "frames": 12, "fps": 12, "stats": {"render": {"frames": 12, "seconds": 0}}})
    sound = {"integrated_lufs": -15, "true_peak_db": -1.5}
    monkeypatch.setattr(build, "build_sound", lambda ep, show, timings, wav, *args: (wav, sound))
    monkeypatch.setattr(build.encode, "frames_to_video", lambda frames, out, **kwargs: out)
    monkeypatch.setattr(build.encode, "concat", lambda videos, out: out)
    received = []
    def mux(video, wav, out):
        received.append(wav)
        return out
    monkeypatch.setattr(build.encode, "mux", mux)
    summary = build.build_episode(Path("test-show"), "ep", out_root=tmp_path)
    assert summary["sound"] == sound
    assert received == [tmp_path / "test-show/ep/preview/sound.wav"]
    saved = json.loads((tmp_path / "test-show/ep/preview/summary.json").read_text())
    assert saved["sound"] == sound


def test_music_envelope_cuts_and_returns():
    env = build.music_envelope([(5.0, False), (8.0, True), (9.0, True), (12.0, False)], 14.0)
    t, y = zip(*env)
    assert list(t) == sorted(t) and len(set(t)) == len(t)
    for when, level in ((0, 1), (4.99, 1), (5.2, 0), (7.9, 0), (8.6, 1), (11.9, 1), (12.5, 0), (14, 0)):
        assert np.interp(when, t, y) == pytest.approx(level, abs=0.02)
    assert build.music_envelope([], 3.0) == [(0.0, 1.0), (3.0, 1.0)]
