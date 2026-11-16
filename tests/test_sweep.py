import pytest

from stopmo import sweep


def test_parse_setting():
    assert sweep.parse_setting("boil=0,0.15,1") == ("boil", [0, 0.15, 1])
    assert sweep.parse_setting(" grade.grain = 0.0, 0.02 ") == ("grade.grain", [0.0, 0.02])
    assert sweep.parse_setting("light_rig=cosy,moody") == ("light_rig", ["cosy", "moody"])
    for bad in ("boil", "boil=", "=1,2"):
        with pytest.raises(ValueError):
            sweep.parse_setting(bad)


def test_set_path_creates_levels_and_overwrites():
    style = {"boil": 1.0, "grade": {"grain": 0.02, "vignette": 0.3}}
    sweep.set_path(style, "boil", 0.3)
    sweep.set_path(style, "grade.grain", 0.0)
    sweep.set_path(style, "materials.skin.boil", 0.1)
    assert style == {"boil": 0.3, "grade": {"grain": 0.0, "vignette": 0.3}, "materials": {"skin": {"boil": 0.1}}}


def test_label_is_file_safe():
    assert sweep.label("boil", 0.15) == "boil_0.15"
    assert sweep.label("grade.grain", 0) == "grade-grain_0"
