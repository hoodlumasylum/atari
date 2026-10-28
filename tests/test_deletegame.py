"""Delete game: asks first (default No), only inside the games folders, Steam is never deleted by CodeAque, saves kept by default."""
import os
import subprocess
from pathlib import Path

import pytest

from atarilauncher import config, gamedelete, windows
from atarilauncher.library import Game, build_library

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt  # noqa: E402
from tests.test_features_ui import conf, wait_for  # noqa: E402
from tests.test_ui_keys import Ui, app, pump  # noqa: E402,F401


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "Games" / "Atari").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("ATARI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ATARI_CONFIG_DIR", str(tmp_path / "conf"))
    return home


def cfg_for():
    cfg = config.default_config()
    cfg.steam_enabled = False
    return cfg


def put(path, data=b"x" * 1000):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def game_for(home, system, path, cfg=None):
    """The Game the library builds for this file."""
    res = build_library(cfg or cfg_for(), home=home, metadata={})
    return next(g for g in res.games if g.platform == system and g.rom_path == str(path))


# ------------------------------------------------------------------ a ROM file
def test_rom_file_plan_shows_name_size_and_deletes_only_that_file(env):
    rom = put(env / "Games/Atari/snes/Super Thing.sfc", b"r" * 2048)
    other = put(env / "Games/Atari/snes/Other.sfc")
    cfg = cfg_for()
    g = game_for(env, "snes", rom)
    pl = gamedelete.plan_for(g, cfg, env)
    assert pl.deletable and pl.title == "Super Thing" and pl.size == 2048 and pl.nfiles == 1 and not pl.folder
    assert "2.0 KB" in pl.size_text() or "2 KB" in pl.size_text() or "KB" in pl.size_text()
    res = gamedelete.delete(pl, cfg, home=env)
    assert res.ok and not rom.exists() and other.exists() and (env / "Games/Atari/snes").is_dir()
    assert "Deleted Super Thing" in res.text and "freed" in res.text


def test_saves_are_kept_by_default_and_only_neighbours_with_the_same_name_go_when_asked(env):
    rom = put(env / "Games/Atari/gba/Quest.gba")
    sav = put(env / "Games/Atari/gba/Quest.srm")
    st = put(env / "Games/Atari/gba/Quest.state1")
    mine = put(env / "Games/Atari/gba/Quest Two.srm")
    notes = put(env / "Games/Atari/gba/Quest.txt")
    cfg = cfg_for()
    pl = gamedelete.plan_for(game_for(env, "gba", rom), cfg, env)
    assert sorted(p.name for p in pl.saves) == ["Quest.srm", "Quest.state1"]
    res = gamedelete.delete(pl, cfg, home=env)
    assert not rom.exists() and sav.exists() and st.exists() and "Saves were kept" in res.text
    # again, asking for the saves too
    rom = put(env / "Games/Atari/gba/Quest.gba")
    pl = gamedelete.plan_for(game_for(env, "gba", rom), cfg, env)
    res = gamedelete.delete(pl, cfg, with_saves=True, home=env)
    assert not rom.exists() and not sav.exists() and not st.exists()
    assert mine.exists() and notes.exists() and "save files" in res.text


def test_cover_picture_is_optional(env, tmp_path):
    rom = put(env / "Games/Atari/snes/Game.sfc")
    cfg = cfg_for()
    g = game_for(env, "snes", rom)
    from atarilauncher import covers
    cov = put(covers.dest_for_game(g), b"\x89PNG....")
    pl = gamedelete.plan_for(g, cfg, env)
    assert pl.cover == cov
    gamedelete.delete(pl, cfg, home=env)
    assert cov.exists()
    rom = put(env / "Games/Atari/snes/Game.sfc")
    pl = gamedelete.plan_for(game_for(env, "snes", rom), cfg, env)
    gamedelete.delete(pl, cfg, with_cover=True, home=env)
    assert not cov.exists() and not rom.exists()


def test_cue_sheet_takes_its_tracks_along(env):
    cue = put(env / "Games/Atari/ps1/Disc.cue", b'FILE "Disc.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
    track = put(env / "Games/Atari/ps1/Disc.bin", b"b" * 5000)
    other = put(env / "Games/Atari/ps1/Other.bin")
    cfg = cfg_for()
    pl = gamedelete.plan_for(game_for(env, "ps1", cue), cfg, env)
    assert pl.size >= 5000 and pl.nfiles == 2
    gamedelete.delete(pl, cfg, home=env)
    assert not cue.exists() and not track.exists() and other.exists()


# ------------------------------------------------------------------ folder games
def test_unpacked_xbox_game_deletes_its_own_folder_only(env):
    xbe = put(env / "Games/Atari/xbox/Shenmue II/default.xbe", b"XBEH")
    put(env / "Games/Atari/xbox/Shenmue II/media/a.bin", b"m" * 3000)
    keep = put(env / "Games/Atari/xbox/Halo.iso")
    cfg = cfg_for()
    pl = gamedelete.plan_for(game_for(env, "xbox", xbe), cfg, env)
    assert pl.deletable and pl.folder and pl.nfiles == 2 and pl.size == 3004
    res = gamedelete.delete(pl, cfg, home=env)
    assert res.ok and not (env / "Games/Atari/xbox/Shenmue II").exists() and keep.exists() and (env / "Games/Atari/xbox").is_dir()


def test_a_folder_game_sitting_straight_in_the_system_folder_is_refused(env):
    xbe = put(env / "Games/Atari/xbox/default.xbe", b"XBEH")
    put(env / "Games/Atari/xbox/other.iso")
    cfg = cfg_for()
    pl = gamedelete.plan_for(game_for(env, "xbox", xbe), cfg, env)
    assert not pl.deletable and not pl.removable and "will not delete the whole folder" in pl.message
    res = gamedelete.delete(pl, cfg, home=env)
    assert not res.ok and xbe.exists()


def test_ps3_game_folder(env):
    eb = put(env / "Games/Atari/ps3/Demons/PS3_GAME/USRDIR/EBOOT.BIN", b"e" * 10)
    put(env / "Games/Atari/ps3/Demons/PS3_GAME/PARAM.SFO")
    put(env / "Games/Atari/ps3/Keep/PS3_GAME/USRDIR/EBOOT.BIN")
    cfg = cfg_for()
    pl = gamedelete.plan_for(game_for(env, "ps3", eb), cfg, env)
    assert pl.deletable and pl.targets == [env / "Games/Atari/ps3/Demons"]
    gamedelete.delete(pl, cfg, home=env)
    assert not (env / "Games/Atari/ps3/Demons").exists() and (env / "Games/Atari/ps3/Keep").is_dir()


# ------------------------------------------------------------------ never outside the games folders
def test_game_outside_every_games_folder_is_not_deletable(env, tmp_path):
    elsewhere = put(tmp_path / "elsewhere" / "Precious.sfc")
    cfg = cfg_for()
    g = Game(gid="rom:snes:" + str(elsewhere), title="Precious", platform="snes", platform_name="Super Nintendo", rom_path=str(elsewhere))
    pl = gamedelete.plan_for(g, cfg, env)
    assert not pl.deletable and "not one of your games folders" in pl.message
    res = gamedelete.delete(pl, cfg, home=env)
    assert not res.ok and elsewhere.exists()


def test_a_folder_set_in_settings_counts_but_home_or_system_folders_never_do(env, tmp_path):
    usb = tmp_path / "usbstick" / "roms"
    rom = put(usb / "Disk.sfc")
    cfg = cfg_for()
    cfg.systems["snes"].roms = [str(usb)]
    g = game_for(env, "snes", rom, cfg)
    pl = gamedelete.plan_for(g, cfg, env)
    assert pl.deletable and pl.root == usb.resolve()
    # a "games folder" that is the home folder, or / , or a system folder is ignored as a root
    for bad in (str(env), str(env.parent), "/", "/usr", "/etc", "/home", "/media"):
        cfg2 = cfg_for()
        cfg2.systems["snes"].roms = [bad]
        assert gamedelete.allowed_roots(cfg2, env) == [env.resolve() / "Games" / "Atari"] or \
            all(r not in (Path(bad).resolve(),) for r in gamedelete.allowed_roots(cfg2, env)), bad
    f = put(env / "Documents" / "thesis.sfc")
    cfg3 = cfg_for()
    cfg3.systems["snes"].roms = [str(env)]
    g = Game(gid="rom:snes:x", title="thesis", platform="snes", platform_name="SNES", rom_path=str(f))
    assert not gamedelete.plan_for(g, cfg3, env).deletable and f.exists()


def test_symlinks_cannot_lead_the_delete_outside(env, tmp_path):
    outside = tmp_path / "outside"
    keep = put(outside / "precious.txt")
    cfg = cfg_for()
    # a symlinked sub folder: a game "inside" it really lives outside
    (env / "Games/Atari/snes").mkdir(parents=True)
    (env / "Games/Atari/snes/link").symlink_to(outside, target_is_directory=True)
    sneaky = outside / "Sneaky.sfc"
    put(sneaky)
    g = Game(gid="rom:snes:s", title="Sneaky", platform="snes", platform_name="SNES", rom_path=str(env / "Games/Atari/snes/link/Sneaky.sfc"))
    pl = gamedelete.plan_for(g, cfg, env)
    assert not pl.deletable and sneaky.exists()
    # a game folder holding a link to an outside folder: the link goes, the target stays
    xbe = put(env / "Games/Atari/xbox/G/default.xbe", b"XBEH")
    (env / "Games/Atari/xbox/G/outlink").symlink_to(outside, target_is_directory=True)
    pl = gamedelete.plan_for(game_for(env, "xbox", xbe), cfg, env)
    assert gamedelete.delete(pl, cfg, home=env).ok
    assert not (env / "Games/Atari/xbox/G").exists() and keep.exists() and outside.is_dir()


def test_the_plan_is_checked_again_at_delete_time(env, tmp_path):
    outside = tmp_path / "outside"
    keep = put(outside / "precious.txt")
    xbe = put(env / "Games/Atari/xbox/G/default.xbe", b"XBEH")
    cfg = cfg_for()
    pl = gamedelete.plan_for(game_for(env, "xbox", xbe), cfg, env)
    # between asking and pressing Yes the folder is swapped for a link to somewhere else
    import shutil
    shutil.rmtree(env / "Games/Atari/xbox/G")
    (env / "Games/Atari/xbox/G").symlink_to(outside, target_is_directory=True)
    gamedelete.delete(pl, cfg, home=env)
    assert keep.exists() and outside.is_dir()
    # a tampered plan pointing outside, or at a games folder itself, is refused
    pl.targets = [keep, env / "Games/Atari", env / "Games/Atari/xbox"]
    res = gamedelete.delete(pl, cfg, home=env)
    assert not res.ok and keep.exists() and (env / "Games/Atari/xbox").is_dir()
    assert len(res.errors) == 3 and "games folder itself" in res.errors[2]


def test_safe_root_rules(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    assert gamedelete.safe_root(home / "Games", home)
    assert not gamedelete.safe_root(home, home) and not gamedelete.safe_root(tmp_path, home)
    assert not gamedelete.safe_root(Path("/"), home) and not gamedelete.safe_root(Path("/usr/share"), home)
    assert not gamedelete.safe_root(Path("/media"), home) and not gamedelete.safe_root(Path("/media/someone"), home)
    assert gamedelete.safe_root(Path("/media/someone/USB"), home) and not gamedelete.safe_root(Path("/home"), home)


# ------------------------------------------------------------------ Steam and others
def test_steam_games_are_never_deleted_by_code(env):
    g = Game(gid="steam:620", title="Portal 2", platform="steam", platform_name="Steam", steam_appid="620")
    pl = gamedelete.plan_for(g, cfg_for(), env)
    assert pl.kind == "steam" and not pl.deletable and not pl.removable and pl.appid == "620"
    res = gamedelete.delete(pl, cfg_for(), home=env)
    assert not res.ok and res.deleted == 0


def test_open_steam_uninstall_with_stand_in_steam(env):
    calls = []

    def popen(cmd, **kw):
        calls.append(cmd)
    cfg = cfg_for()
    cfg.steam_command = "steam"
    ok, text = gamedelete.open_steam_uninstall(cfg, "620", env, popen=popen, running=lambda: True, sleep=lambda s: None)
    assert ok and calls == [["steam", "steam://uninstall/620"]] and "uninstall window" in text
    calls.clear()
    state = {"n": 0}

    def running():
        state["n"] += 1
        return state["n"] > 2
    gamedelete.open_steam_uninstall(cfg, "620", env, popen=popen, running=running, sleep=lambda s: None, big_picture=True)
    assert calls == [["steam", "-gamepadui"], ["steam", "steam://uninstall/620"]]
    assert gamedelete.open_steam_uninstall(cfg, "6;rm", env, popen=popen, running=lambda: True)[0] is False

    def broken(cmd, **kw):
        raise FileNotFoundError(2, "No such file")
    ok, text = gamedelete.open_steam_uninstall(cfg, "620", env, popen=broken, running=lambda: True)
    assert not ok and "Install Steam" in text


def test_apps_and_other_launchers_are_not_deletable(env):
    for gid in ("app:steam", "heroic:abc", "lutris:3", "free:minecraft", "studio:open", "tool:record"):
        g = Game(gid=gid, title="x", platform="x", platform_name="X")
        assert gamedelete.kind_of(g) == "none"
        assert "CodeAque can only delete games" in gamedelete.plan_for(g, cfg_for(), env).message


# ------------------------------------------------------------------ Windows games
def test_windows_game_folder_made_by_code_is_deleted_and_forgotten(env):
    exe = put(windows.games_dir(env) / "Cool Game" / "bin" / "cool.exe", b"MZ")
    put(windows.games_dir(env) / "Cool Game" / "data.pak", b"d" * 4000)
    keep = put(windows.games_dir(env) / "Other" / "other.exe", b"MZ")
    w = windows.add_game("Cool Game", str(exe))
    cfg = cfg_for()
    g = next(x for x in build_library(cfg, home=env, metadata={}).games if x.gid == w.gid)
    pl = gamedelete.plan_for(g, cfg, env)
    assert pl.kind == "windows" and pl.deletable and pl.folder and pl.nfiles == 2
    res = gamedelete.delete(pl, cfg, home=env)
    assert res.ok and not (windows.games_dir(env) / "Cool Game").exists() and keep.exists()
    assert not any(x.gid == w.gid for x in windows.load_games())


def test_windows_game_elsewhere_is_only_removed_from_the_library(env, tmp_path):
    exe = put(tmp_path / "mygames" / "Thing" / "thing.exe", b"MZ")
    w = windows.add_game("Thing", str(exe))
    cfg = cfg_for()
    g = next(x for x in build_library(cfg, home=env, metadata={}).games if x.gid == w.gid)
    pl = gamedelete.plan_for(g, cfg, env)
    assert pl.kind == "winref" and not pl.deletable and pl.removable
    res = gamedelete.delete(pl, cfg, home=env)
    assert res.ok and exe.exists() and "files were left" in res.text
    assert not windows.load_games()


# ------------------------------------------------------------------ the screen
def make_ui(app, tmp_path, monkeypatch, env):
    conf(tmp_path)
    return Ui(app, tmp_path, monkeypatch, config_exists=True, home=env)


def select(ui, system, title):
    b = ui.backend
    b.setFilter(system)
    pump(ui.app, 100)
    for row in range(200):
        g = b.model.game_at(row)
        if g is None:
            break
        if g.title == title:
            return row
    raise AssertionError("game not in the list")


def test_page_asks_first_defaults_to_no_and_deleting_removes_the_game(app, tmp_path, monkeypatch, env):
    rom = put(env / "Games/Atari/snes/Super Thing.sfc", b"r" * 4096)
    put(env / "Games/Atari/snes/Super Thing.srm")
    ui = make_ui(app, tmp_path, monkeypatch, env)
    b = ui.backend
    row = select(ui, "snes", "Super Thing")
    assert b.games.get(row)["canDelete"] is True
    b.toggleFavorite(row)
    assert b.openDeleteGame(row)
    rows = b.pageRows("deletegame")
    text = " ".join(r["title"] for r in rows)
    assert 'Delete "Super Thing"' in text and "4.0 KB" in text and str(rom) in text
    selectable = [r for r in rows if r["kind"] != "info"]
    assert selectable[0]["id"] == "delno" and selectable[-1]["id"] == "delyes"      # the highlight starts on "No"
    saves = [r for r in rows if r.get("id") == "delsaves"][0]
    assert "KEEP" in saves["title"]
    # No: nothing changes
    assert b.pageActivate("deletegame", "delno") == "close" and rom.exists()
    # Yes
    assert b.openDeleteGame(row)
    assert b.pageActivate("deletegame", "delyes") == "refresh"
    assert wait_for(app, lambda: b._del_result is not None, 10)
    assert not rom.exists() and (env / "Games/Atari/snes/Super Thing.srm").exists()          # saves kept
    done = b.pageRows("deletegame")
    assert done[0]["title"].startswith("DONE:") and "Deleted Super Thing" in done[0]["title"] and "Saves were kept" in done[0]["title"]
    assert not any(g.title == "Super Thing" for g in b._all)
    assert "Deleted Super Thing" in b.toast
    assert not b.store.is_favorite("rom:snes:" + os.path.realpath(rom))


def test_toggle_saves_and_cover_then_delete_everything_asked(app, tmp_path, monkeypatch, env):
    rom = put(env / "Games/Atari/gba/Quest.gba")
    sav = put(env / "Games/Atari/gba/Quest.srm")
    ui = make_ui(app, tmp_path, monkeypatch, env)
    b = ui.backend
    row = select(ui, "gba", "Quest")
    b.openDeleteGame(row)
    assert b.pageActivate("deletegame", "delsaves") == "refresh"
    assert "DELETE them too" in [r for r in b.pageRows("deletegame") if r.get("id") == "delsaves"][0]["title"]
    b.pageActivate("deletegame", "delyes")
    assert wait_for(app, lambda: b._del_result is not None, 10)
    assert not rom.exists() and not sav.exists()


def test_steam_game_page_offers_steam_not_deletion(app, tmp_path, monkeypatch, env):
    ui = make_ui(app, tmp_path, monkeypatch, env)
    b = ui.backend
    g = Game(gid="steam:620", title="Portal 2", platform="steam", platform_name="Steam", steam_appid="620")
    monkeypatch.setattr(b.model, "game_at", lambda row: g)
    monkeypatch.setenv("ATARI_NO_STEAM_SPAWN", "1")
    assert b.openDeleteGame(0)
    rows = b.pageRows("deletegame")
    assert [r["id"] for r in rows if r["kind"] != "info"] == ["delno", "delsteam"]
    assert any("CodeAque will not delete" in r["title"] for r in rows)
    assert not any(r.get("id") == "delyes" for r in rows)
    called = []
    monkeypatch.setattr(gamedelete, "open_steam_uninstall", lambda cfg, appid, **kw: called.append(appid) or (True, "opening"))
    monkeypatch.delenv("ATARI_NO_STEAM_SPAWN")
    assert b.pageActivate("deletegame", "delsteam") == "refresh" and called == ["620"]
    assert b.pageActivate("deletegame", "delyes") == ""                 # no way to delete a Steam game through the page
    assert b.pageActivate("deletegame", "back") == "back"


def test_things_that_cannot_be_deleted_say_so(app, tmp_path, monkeypatch, env):
    ui = make_ui(app, tmp_path, monkeypatch, env)
    b = ui.backend
    b.setFilter("tools")
    pump(app, 100)
    row = next(r for r in range(300) if b.model.game_at(r) is not None and b.model.game_at(r).gid.startswith(("studio:", "tool:")))
    assert b.games.get(row)["canDelete"] is False
    assert b.openDeleteGame(row) is False and "CodeAque can only delete games" in b.toast


def test_outside_game_page_says_nothing_was_changed(app, tmp_path, monkeypatch, env, tmp_path_factory):
    ui = make_ui(app, tmp_path, monkeypatch, env)
    b = ui.backend
    f = put(tmp_path / "elsewhere" / "Precious.sfc")
    g = Game(gid="rom:snes:" + str(f), title="Precious", platform="snes", platform_name="Super Nintendo", rom_path=str(f))
    monkeypatch.setattr(b.model, "game_at", lambda row: g)
    assert b.openDeleteGame(0)
    rows = b.pageRows("deletegame")
    assert any("not one of your games folders" in r["title"] for r in rows)
    assert not any(r.get("id") == "delyes" for r in rows)
    assert b.pageActivate("deletegame", "delyes") == "" and f.exists()


def test_keyboard_and_controller_path_to_the_page(app, tmp_path, monkeypatch, env):
    put(env / "Games/Atari/snes/Super Thing.sfc")
    ui = make_ui(app, tmp_path, monkeypatch, env)
    b = ui.backend
    select(ui, "snes", "Super Thing")
    win = ui.win
    win.setProperty("area", "grid")
    win.setProperty("mode", "library")
    pump(app, 200)
    # the Delete key on the grid
    ui.key(Qt.Key_Delete, 120)
    assert ui.mode == "page" and win.property("pageName") == "deletegame"
    # the highlight is on "No": Enter keeps the game
    ui.key(Qt.Key_Return, 120)
    assert ui.mode == "library" and any(g.title == "Super Thing" for g in b._all)
    # D-pad: Right to the panel, Down to DELETE GAME, A opens the page; B (Esc) goes back without deleting
    win.setProperty("area", "grid")
    ui.key(Qt.Key_Right, 80)
    assert win.property("area") == "detail" and win.property("detailIndex") == 0
    ui.key(Qt.Key_Down, 80)
    assert win.property("detailIndex") == 2
    ui.key(Qt.Key_Return, 120)
    assert ui.mode == "page" and win.property("pageName") == "deletegame"
    ui.key(Qt.Key_Escape, 120)
    assert ui.mode == "library" and any(g.title == "Super Thing" for g in b._all)
    assert not [w for w in ui.warnings if "DetailPanel" in w]
