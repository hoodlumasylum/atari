"""DualShock 4 (and other unmapped pads) read as plain joysticks: mocked input."""
import os

from atarilauncher import gamepad_helper as gh


def test_ds4_raw_buttons_map_like_the_layout():
    # Cross, Circle, Triangle, Square, Share, Options (kernel order for hid_playstation / hid_sony)
    acts = [gh.BUTTON_MAP.get(gh.raw_button_name(i)) for i in (0, 1, 2, 3, 8, 9)]
    assert acts == ["accept", "back", "options", "favorite", "search", "system"]
    assert gh.raw_button_name(10) == "guide" and gh.raw_button_name(99) == ""


def test_hat_and_stick_directions():
    assert gh.hat_directions(0, 1) == {"up"} and gh.hat_directions(0, -1) == {"down"}
    assert gh.hat_directions(1, 0) == {"right"} and gh.hat_directions(0, 0) == set()
    assert gh.stick_direction(0.0, -0.9) == "up" and gh.stick_direction(0.9, 0.0) == "right"


def test_input_access_counts_readable_devices(tmp_path):
    for n in ("event0", "event1"):
        (tmp_path / n).write_text("")
    (tmp_path / "event1").chmod(0)
    total, ok = gh.input_access(str(tmp_path))
    assert total == 2 and ok == (2 if os.geteuid() == 0 else 1)


def test_hidraw_readable(tmp_path):
    assert not gh.hidraw_readable(str(tmp_path))
    (tmp_path / "hidraw0").write_text("")
    assert gh.hidraw_readable(str(tmp_path))
