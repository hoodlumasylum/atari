"""Start the real Qt Quick UI headlessly (offscreen) and check it comes up without QML errors."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
ROOT = Path(__file__).resolve().parent.parent


def run(tmp_path, home, *args, keys=""):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software", HOME=str(home),
               ATARI_CONFIG_DIR=str(tmp_path / "conf"), ATARI_DATA_DIR=str(tmp_path / "data"),
               PYTHONPATH=str(ROOT), ATARI_NO_GAMEPAD="1")
    extra = ["--screenshot-keys", keys] if keys else []
    return subprocess.run([sys.executable, "-m", "atarilauncher", "--windowed", *args, *extra],
                          env=env, capture_output=True, text=True, timeout=90)


def test_starts_with_no_steam_and_no_roms(tmp_path):
    home = tmp_path / "emptyhome"
    home.mkdir()
    shot = tmp_path / "empty.png"
    r = run(tmp_path, home, "--screenshot", str(shot))
    assert r.returncode == 0, r.stderr
    assert "qml" not in r.stderr.lower() and "Traceback" not in r.stderr
    assert shot.stat().st_size > 5000


def test_starts_with_first_run_setup_and_navigation_keys(tmp_path):
    home = tmp_path / "h"
    home.mkdir()
    keys = "down,accept,accept,up,left,back,menu,down,down,accept,down,accept"  # wander through setup + browser
    r = run(tmp_path, home, "--selftest", keys=keys)
    assert r.returncode == 0, r.stderr
    assert "Traceback" not in r.stderr


def test_starts_with_populated_library(tmp_path, fake_system):
    rom_dir = tmp_path / "roms"
    rom_dir.mkdir()
    for i in range(30):
        (rom_dir / f"Game {i} (USA).nes").write_bytes(b"0")
    conf = tmp_path / "conf"
    conf.mkdir()
    (conf / "config.toml").write_text(f'[systems.nes]\nroms = ["{rom_dir}"]\n')
    shot = tmp_path / "pop.png"
    keys = "right,down,down,favorite,prev,next,search,accept,accept,back,back"
    r = run(tmp_path, fake_system["home"], "--screenshot", str(shot), keys=keys)
    assert r.returncode == 0, r.stderr
    assert "qml" not in r.stderr.lower() and "Traceback" not in r.stderr
    state = (tmp_path / "data" / "state.json")
    assert state.is_file() and '"favorite": true' in state.read_text()


def test_demo_mode(tmp_path):
    r = run(tmp_path, tmp_path, "--demo", "--selftest")
    assert r.returncode == 0, r.stderr


def test_add_games_from_fake_usb_end_to_end(tmp_path, fake_system):
    """Options -> Add Games -> pick the USB stick -> scan -> copy, all through the real UI."""
    media = tmp_path / "media"
    stick = media / "STICK"
    (stick / "NES").mkdir(parents=True)
    (stick / "NES" / "Brick Bash (USA).nes").write_bytes(b"x" * 2048)
    roms = tmp_path / "Games" / "Atari"
    conf = tmp_path / "conf"
    conf.mkdir()
    (conf / "config.toml").write_text(f'[systems.nes]\nroms = ["{roms / "nes"}"]\n')
    env_media = {"ATARI_MEDIA_ROOTS": str(media)}
    old = dict(os.environ)
    os.environ.update(env_media)
    try:
        r = run(tmp_path, fake_system["home"], "--selftest",
                keys="options,down,down,down,accept,wait,accept,wait,accept,wait:1000,accept,wait:2500")
    finally:
        os.environ.clear()
        os.environ.update(old)
    assert r.returncode == 0, r.stderr
    assert "Traceback" not in r.stderr and "qml" not in r.stderr.lower()
    assert (roms / "nes" / "Brick Bash (USA).nes").read_bytes() == b"x" * 2048
    assert not list(roms.rglob("*.part"))
    assert (stick / "NES" / "Brick Bash (USA).nes").read_bytes() == b"x" * 2048  # stick untouched


def test_settings_and_emulators_pages_open(tmp_path):
    home = tmp_path / "h2"
    home.mkdir()
    (tmp_path / "conf").mkdir()
    (tmp_path / "conf" / "config.toml").write_text("[steam]\nenabled = false\n")
    r = run(tmp_path, home, "--selftest", keys="menu,wait,down,down,down,down,accept,wait,back,back,wait")
    assert r.returncode == 0, r.stderr
    assert "Traceback" not in r.stderr and "qml" not in r.stderr.lower()


def test_first_run_escape_goes_to_main_screen_and_saves_config(tmp_path):
    """The 0.2.0 bug: Esc / B on the welcome screen did nothing. Through the real UI (gamepad-style 'back')."""
    home = tmp_path / "h3"
    home.mkdir()
    r = run(tmp_path, home, "--selftest", keys="wait:200,back,wait:300")
    assert r.returncode == 0, r.stderr
    assert "Traceback" not in r.stderr and "qml" not in r.stderr.lower()
    assert (tmp_path / "conf" / "config.toml").is_file()
    r = run(tmp_path, home, "--selftest", keys="wait:200,back,wait:200")   # second start: no setup screen any more
    assert r.returncode == 0, r.stderr
