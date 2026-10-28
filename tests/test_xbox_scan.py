"""Games put by hand into ~/Games/Atari/<system> (Shenmue 2 in ~/Games/Atari/xbox) must show up; unknown folders get a hint."""
import os

import pytest

from atarilauncher import bios, config, gamesroot
from atarilauncher.library import build_library

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from tests.test_features_ui import conf  # noqa: E402
from tests.test_ui_keys import Ui, app, pump  # noqa: E402,F401

XBOX_MAGIC = b"MICROSOFT*XBOX*MEDIA"


def xbox_iso(path):
    data = bytearray(0x10000 + 64)
    data[0x10000:0x10000 + 20] = XBOX_MAGIC
    path.write_bytes(bytes(data))


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    (h / "Games" / "Atari").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("ATARI_CONFIG_DIR", str(tmp_path / "conf"))
    monkeypatch.setenv("ATARI_DATA_DIR", str(tmp_path / "data"))
    return h


def cfg_for(home):
    cfg = config.default_config() if hasattr(config, "default_config") else config.load_config()
    cfg.steam_enabled = False
    return cfg


def titles(res, system):
    return sorted(g.title for g in res.games if g.platform == system)


def test_a_game_dropped_into_games_atari_xbox_is_shown_without_any_setting(home):
    (home / "Games/Atari/xbox").mkdir()
    xbox_iso(home / "Games/Atari/xbox/Shenmue II.iso")
    cfg = cfg_for(home)
    assert not cfg.systems["xbox"].roms        # nothing saved in Settings: this is what failed before
    res = build_library(cfg, home=home, metadata={})
    assert titles(res, "xbox") == ["Shenmue II"]
    assert res.rom_counts["xbox"] == 1
    assert res.auto_folders["xbox"] == [str(home / "Games/Atari/xbox")]
    assert res.unknown == []


@pytest.mark.parametrize("name", ["xbox", "Xbox", "XBOX", "xbox-classic", "Xbox Classic", "originalxbox", "xiso"])
def test_every_spelling_of_the_xbox_folder_is_found(home, name):
    d = home / "Games/Atari" / name
    d.mkdir()
    xbox_iso(d / "Shenmue II.xiso")
    res = build_library(cfg_for(home), home=home, metadata={})
    assert titles(res, "xbox") == ["Shenmue II"] and res.unknown == []


def test_xbox_extensions_and_unpacked_folders(home):
    d = home / "Games/Atari/xbox"
    d.mkdir()
    for n in ("A.iso", "B.ISO", "C.xiso", "D.xiso.iso"):
        xbox_iso(d / n)
    (d / "Unpacked Game").mkdir()
    (d / "Unpacked Game" / "default.xbe").write_bytes(b"XBEH")
    (d / "readme.txt").write_text("x")
    res = build_library(cfg_for(home), home=home, metadata={})
    got = titles(res, "xbox")
    assert len(got) == 5 and "Unpacked Game" in got


def test_games_code_folder_also_works_and_a_symlinked_copy_is_not_doubled(home):
    (home / "Games/Atari/xbox").mkdir()
    xbox_iso(home / "Games/Atari/xbox/G.iso")
    (home / "Games/Code").symlink_to(home / "Games/Atari", target_is_directory=True)
    res = build_library(cfg_for(home), home=home, metadata={})
    assert titles(res, "xbox") == ["G"]
    (home / "Games/Code").unlink()
    (home / "Games/Code").mkdir()
    (home / "Games/Code/snes").mkdir()
    (home / "Games/Code/snes/Mario.sfc").write_bytes(b"x" * 600)
    assert "Mario" in titles(build_library(cfg_for(home), home=home, metadata={}), "snes")


def test_a_configured_folder_still_works_and_is_not_scanned_twice(home, tmp_path):
    (home / "Games/Atari/xbox").mkdir()
    xbox_iso(home / "Games/Atari/xbox/G.iso")
    cfg = cfg_for(home)
    cfg.systems["xbox"].roms = [str(home / "Games/Atari/xbox")]
    res = build_library(cfg, home=home, metadata={})
    assert titles(res, "xbox") == ["G"] and "xbox" not in res.auto_folders


def test_unrecognised_folder_is_flagged_with_a_guess(home):
    a = home / "Games/Atari/Xbox Games"
    a.mkdir()
    xbox_iso(a / "Shenmue II.iso")
    b = home / "Games/Atari/stuff"      # no hint in the name: guessed from inside the disc image
    b.mkdir()
    xbox_iso(b / "Halo.iso")
    c = home / "Games/Atari/Pictures"   # nothing game-like: ignored
    c.mkdir()
    (c / "a.png").write_bytes(b"x")
    loose = home / "Games/Atari/Loose.iso"
    xbox_iso(loose)
    cfg = cfg_for(home)
    res = build_library(cfg, home=home, metadata={})
    by = {u.name: u for u in res.unknown}
    assert set(by) == {"Xbox Games", "stuff", "Loose.iso"}
    assert by["Xbox Games"].guess == "xbox" and by["stuff"].guess == "xbox" and by["Loose.iso"].guess == "xbox"
    assert titles(res, "xbox") == []
    text = gamesroot.hint_text(cfg, by["Xbox Games"])
    assert "Xbox Games" in text and '"xbox"' in text and "not shown" in text


def test_fix_renames_or_moves_and_never_overwrites(home):
    a = home / "Games/Atari/Xbox Games"
    a.mkdir()
    xbox_iso(a / "Shenmue II.iso")
    loose = home / "Games/Atari/Loose.iso"
    xbox_iso(loose)
    cfg = cfg_for(home)
    ok, msg = gamesroot.fix(cfg, str(a), home)
    assert ok and (home / "Games/Atari/xbox/Shenmue II.iso").is_file() and not a.exists()
    ok, msg = gamesroot.fix(cfg, str(loose), home)
    assert ok and (home / "Games/Atari/xbox/Loose.iso").is_file() and not loose.exists()
    # a second folder cannot replace the first
    d = home / "Games/Atari/my xbox"
    d.mkdir()
    xbox_iso(d / "x.iso")
    ok, msg = gamesroot.fix(cfg, str(d), home)
    assert not ok and "already exists" in msg and (d / "x.iso").is_file()
    # collision of a loose file
    again = home / "Games/Atari/Loose.iso"
    xbox_iso(again)
    ok, msg = gamesroot.fix(cfg, str(again), home)
    assert not ok and again.is_file()
    # nothing outside the games folder can be touched
    assert gamesroot.fix(cfg, str(home), home)[0] is False


def test_unknown_folder_without_any_clue_gets_the_generic_hint(home):
    d = home / "Games/Atari/misc"
    d.mkdir()
    (d / "thing.zzz").write_bytes(b"x")
    cfg = cfg_for(home)
    (u,) = gamesroot.unknown_items(cfg, home)
    assert u.guess == ""
    assert "named after the system" in gamesroot.hint_text(cfg, u)
    assert gamesroot.fix(cfg, u.path, home)[0] is False


def test_xbox_guide_lists_what_the_user_must_supply(home):
    lines = bios.xbox_guide(home, which=lambda n: None)
    text = "\n".join(lines)
    for n in ("mcpx_1.0.bin", "Complex_4627v1.03.bin", "xbox_hdd.qcow2", "eeprom.bin", "default.xbe", "~/Games/Atari/xbox"):
        assert n in text
    assert "[needed] mcpx_1.0.bin" in text and "never includes" in text
    xemu = home / ".var/app/app.xemu.xemu/data/xemu/xemu"
    xemu.mkdir(parents=True)
    (xemu / "mcpx_1.0.bin").write_bytes(b"x")
    text = "\n".join(bios.xbox_guide(home, which=lambda n: None))
    assert "[found] mcpx_1.0.bin" in text and "[needed] xbox_hdd.qcow2" in text


def test_settings_and_emulators_pages_show_the_hint_folder_and_guide(app, tmp_path, monkeypatch, home):
    conf(tmp_path)
    (home / "Games/Atari/xbox").mkdir()
    xbox_iso(home / "Games/Atari/xbox/Shenmue II.iso")
    (home / "Games/Atari/PS Two").mkdir()
    (home / "Games/Atari/PS Two/G.iso").write_bytes(b"x" * 100)
    (home / "Games/Atari/Xbox Games").mkdir()
    xbox_iso(home / "Games/Atari/Xbox Games/Halo.iso")
    ui = Ui(app, tmp_path, monkeypatch, config_exists=True, home=home)
    try:
        b = ui.backend
        assert any(g.title == "Shenmue II" for g in b._all)
        rows = b.setupRows()
        xrow = [r for r in rows if r.get("kind") == "system" and r["id"] == "xbox"][0]
        assert xrow["value"] == "1 game" and str(home / "Games/Atari/xbox") in xrow["detail"]
        fix = [r for r in rows if r.get("kind") == "fixfolder"]
        assert {r["title"] for r in fix} >= {"Not recognised: Xbox Games"}
        assert [r for r in fix if r["title"].endswith("Xbox Games")][0]["value"] == "Fix"
        emu = b.emulatorRows()
        assert any("xbox_hdd.qcow2" in r["title"] for r in emu)
        # "xbox" exists already: the Fix button refuses to merge or overwrite and says what to do
        b.fixGamesFolder(str(home / "Games/Atari/Xbox Games"))
        assert (home / "Games/Atari/Xbox Games/Halo.iso").is_file() and "already exists" in b.toast
        # without a clash it renames and rescans
        (home / "Games/Atari/xbox/Shenmue II.iso").rename(home / "Games/Atari/Shenmue II.iso")
        (home / "Games/Atari/xbox").rmdir()
        b.fixGamesFolder(str(home / "Games/Atari/Xbox Games"))
        assert (home / "Games/Atari/xbox/Halo.iso").is_file()
        assert any(g.title == "Halo" for g in b._all)
    finally:
        ui.close() if hasattr(ui, "close") else None
