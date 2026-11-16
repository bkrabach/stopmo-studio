import json
from pathlib import Path

import pytest
import yaml

from stopmo import build, encode
from stopmo.ledger import Ledger

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("style", ["clay", "felt", "toybox", "vinyl"])
def test_shows_load_and_reference_real_things(tmp_path, style):
    show_dir = tmp_path / "fixture"
    (show_dir / "characters").mkdir(parents=True)
    (show_dir / "episodes").mkdir()
    (show_dir / "show.yaml").write_text(yaml.safe_dump({"title": "Test", "style": style, "set": "studio"}))
    (show_dir / "characters/actor.yaml").write_text("height: 0.2\n")
    (show_dir / "episodes/check.yaml").write_text(yaml.safe_dump({
        "shots": [{"cast": {"actor": {}}, "beats": [{"who": "actor", "do": "nod"}]}],
    }))
    show = build.load_show(show_dir)
    assert show["style"]["name"] and show["characters"]
    for path in sorted((show_dir / "episodes").glob("*.yaml")):
        ep = build.load_episode(show, path.stem)
        ids = [s["id"] for s in ep["shots"]]
        assert len(ids) == len(set(ids)), "shot ids must be unique"
        for shot in ep["shots"]:
            assert "title" in shot or "set" in shot
            for name in shot.get("cast", {}):
                assert name in show["characters"], f"{path.name}: unknown character {name}"
            for beat in shot.get("beats", []):
                assert True not in beat, f"{path.name}: a YAML key parsed as boolean (quote 'on'/'yes'/'no'): {beat}"
                if "who" in beat:
                    assert beat["who"] in show["characters"]
                    assert "say" in beat or "do" in beat, beat


def test_style_files_parse():
    for path in (ROOT / "styles").glob("*.yaml"):
        style = yaml.safe_load(path.read_text())
        assert style["name"] == path.stem
        assert True not in json.loads(json.dumps(style, default=str)).keys()


def test_hash_is_stable_and_sensitive():
    assert build._hash({"a": 1, "b": [1, 2]}) == build._hash({"b": [1, 2], "a": 1})
    assert build._hash({"a": 1}) != build._hash({"a": 2})


def test_merge_is_deep():
    assert build._merge({"a": {"x": 1, "y": 2}, "b": 1}, {"a": {"y": 3}}) == {"a": {"x": 1, "y": 3}, "b": 1}


def test_grade_filter():
    f = encode.grade_filter({"grain": 0.0, "vignette": 0.0})
    assert "noise" not in f and "vignette" not in f and f.startswith("eq=")
    assert "noise=alls=5" in encode.grade_filter({"grain": 0.02})


def test_concat_apostrophe_path_and_cleanup(tmp_path, monkeypatch):
    video = tmp_path / "a filmmaker's clip.mp4"
    out = tmp_path / "joined.mp4"
    observed = []
    monkeypatch.setattr(encode, "_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(encode, "_run", lambda *args, **kwargs: observed.append(out.with_suffix(".txt").read_text()))
    assert encode.concat([video], out) == out
    assert "filmmaker'\\''s" in observed[0]
    assert not out.with_suffix(".txt").exists()


def test_concat_rejects_empty_or_multiline_paths(tmp_path):
    with pytest.raises(ValueError):
        encode.concat([], tmp_path / "empty.mp4")
    with pytest.raises(ValueError):
        encode.concat([tmp_path / "new\nline.mp4"], tmp_path / "out.mp4")


def test_ledger_totals(tmp_path):
    ledger = Ledger()
    with ledger.stage("a"):
        pass
    with ledger.stage("a", shot="s1"):
        pass
    ledger.count("frames", 3)
    ledger.hit("line")
    data = ledger.write(tmp_path / "l.json")
    assert set(data["by_stage"]) == {"a"} and data["counts"] == {"frames": 3} and data["cache_hits"] == {"line": 1}
    assert data["api_cost_usd"] == 0.0 and len(data["stages"]) == 2
