"""0.5.0: Find my BIOS files, Find my games, the PC Games Installer."""
import os
import zipfile
from pathlib import Path

import pytest

from atarilauncher import biosfind, findgames, windows, xemuconfig
from atarilauncher.config import default_config


def nowhere(_n):
    return None


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    (h / "Downloads").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("ATARI_DATA_DIR", str(tmp_path / "data"))
    return h


# ------------------------------------------------------------------ BIOS
def test_find_my_bios_looks_in_folders_and_archives_and_copies_with_xemu_settings(home):
    dl = home / "Downloads"
    (dl / "xbox stuff").mkdir()
    (dl / "xbox stuff" / "mcpx_1.0.bin").write_bytes(b"\x01" * 512)
    with zipfile.ZipFile(dl / "my xbox bios.zip", "w") as z:
        z.writestr("bios/Complex 4627.bin", b"\x02" * (256 * 1024))
        z.writestr("readme.txt", "hi")
    res = biosfind.find(home=home, which=nowhere)
    names = {f.item.path.name: f for f in res.found}
    assert "mcpx_1.0.bin" in names and "Complex 4627.bin" in names
    assert "my xbox bios.zip > " in names["Complex 4627.bin"].source and names["Complex 4627.bin"].dest
    assert res.archives_seen == 1 and Path(res.tmp).is_dir()
    out, xemu = biosfind.install(res, None, home, nowhere)
    assert out.copied >= 2 and not out.failed and res.tmp == ""
    toml = next(iter(xemuconfig.config_files(home, nowhere)))
    text = toml.read_text()
    assert "flashrom_path" in text and "Complex_4627v1.03.bin" in text and "mcpx_1.0.bin" in text
    assert any("BIOS" in l or "Boot" in l for l in xemu)
    assert (dl / "my xbox bios.zip").exists()                               # the originals are never touched


def test_find_my_bios_explains_archives_it_cannot_open(home):
    (home / "Downloads" / "pack.7z").write_bytes(b"not really")
    res = biosfind.find(home=home, which=nowhere)
    assert res.found == [] and any("7-Zip" in n for n in res.notes)


# ------------------------------------------------------------------ games
def make_downloads(home):
    dl = home / "Downloads"
    files = {"Plumber (USA).nes": 100, "PS1/Quest (Japan) (Disc 1).bin": 700, "PS1/Quest (Japan) (Disc 2).bin": 710, "notes.txt": 3,
             "MyPCGame/MyPCGame.exe": 5000, "MyPCGame/MyPCGame_Data/level1": 10, "MyPCGame/unins000.exe": 900,
             "MyPCGame/UnityCrashHandler64.exe": 800, "ChromeSetup.exe": 50}
    for rel, size in files.items():
        p = dl / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * size)
    for d in (1, 2):
        (dl / f"PS1/Quest (Japan) (Disc {d}).cue").write_text(f'FILE "Quest (Japan) (Disc {d}).bin" BINARY\n  TRACK 01 MODE2/2352\n')
    with zipfile.ZipFile(dl / "Maze Runner.zip", "w") as z:
        z.writestr("Maze.lnx", b"y" * 64)
    (home / "Desktop").mkdir()
    (home / "Desktop" / "Tiny Tactics.gba").write_bytes(b"z" * 50)


def test_find_my_games_sorts_by_console_keeps_disc_sets_and_finds_pc_games(home):
    make_downloads(home)
    cfg = default_config()
    res = findgames.find(cfg, home=home, which=nowhere, roots=[home / "Downloads", home / "Desktop"])
    kinds = {(e.kind, e.system, e.title) for e in res.entries}
    assert ("rom", "nes", "Plumber (USA)") in kinds and ("rom", "gba", "Tiny Tactics") in kinds
    quest = [e for e in res.entries if "Quest" in e.title]
    assert len(quest) == 1 and len(quest[0].item.companions) == 3                  # disc 1 + 2 together (+ the other sheet / tracks)
    pc = [e for e in res.entries if e.kind == "pc"]
    assert len(pc) == 1 and pc[0].exe == "MyPCGame.exe" and "unins000.exe" not in pc[0].exes
    assert [e.title for e in res.entries if e.kind == "installer"] == ["ChromeSetup"]
    assert any(e.kind == "archive" and e.system == "atarilynx" for e in res.entries)
    assert all(str(home / "Games/CodeAque") in e.dest for e in res.entries if e.kind != "installer")


def test_find_my_games_copy_then_duplicates_are_skipped(home):
    make_downloads(home)
    cfg = default_config()
    res = findgames.find(cfg, home=home, which=nowhere, roots=[home / "Downloads"])
    d = findgames.install(res, cfg, move=False, home=home, which=nowhere)
    g = home / "Games/CodeAque"
    assert (g / "nes" / "Plumber (USA).nes").is_file() and (g / "atarilynx" / "Maze.lnx").is_file()
    assert (g / "pc" / "MyPCGame" / "MyPCGame.exe").is_file()
    assert [w.name for w in windows.load_games()] == ["MyPCGame"]
    assert (home / "Downloads" / "Plumber (USA).nes").is_file()                     # copied, not moved
    assert d.added >= 4 and not d.failed
    again = findgames.install(findgames.find(cfg, home=home, which=nowhere, roots=[home / "Downloads"]), cfg, home=home, which=nowhere)
    assert again.duplicates >= 3 and again.added == 0


def test_find_my_games_move(home):
    make_downloads(home)
    cfg = default_config()
    res = findgames.find(cfg, home=home, which=nowhere, roots=[home / "Downloads"])
    findgames.install(res, cfg, move=True, home=home, which=nowhere)
    assert not (home / "Downloads" / "Plumber (USA).nes").exists() and not (home / "Downloads" / "MyPCGame").exists()
    assert not (home / "Downloads" / "Maze Runner.zip").exists()
    assert (home / "Downloads" / "ChromeSetup.exe").exists()                       # installers are never moved or run
    assert (home / "Downloads" / "notes.txt").exists()


def test_the_games_folder_itself_is_not_scanned(home):
    (home / "Games/CodeAque/nes").mkdir(parents=True)
    (home / "Games/CodeAque/nes/A.nes").write_bytes(b"1")
    assert findgames.find(default_config(), home=home, which=nowhere, roots=[home / "Games"]).entries == []


# ------------------------------------------------------------------ PC Games Installer
def test_pc_games_installer_runs_setup_in_its_own_folder_and_adds_the_installed_game(home, tmp_path, monkeypatch):
    setup = home / "Downloads" / "setup.exe"
    setup.write_bytes(b"MZ")
    ran = {}

    def fake_run(cmd, env=None, **kw):
        ran["cmd"], ran["prefix"] = cmd, env.get("WINEPREFIX")
        game = Path(env["WINEPREFIX"]) / "drive_c/Program Files/Star Pilot"
        game.mkdir(parents=True)
        (game / "StarPilot.exe").write_bytes(b"x" * 5000)
        (game / "uninstall.exe").write_bytes(b"x" * 9000)

        class R:
            returncode = 0
        return R()
    monkeypatch.setattr(windows, "find_runner", lambda cfg=None, home=None, which=None: windows.Runner("wine", ["/usr/bin/wine"], "Wine"))
    g, text = windows.run_installer(None, setup, "Star Pilot", runner=fake_run)
    assert g is not None and g.exe.endswith("StarPilot.exe") and "Installed and added Star Pilot" in text
    assert ran["prefix"].endswith("prefixes/star-pilot") and ran["cmd"][-1] == str(setup)
    _cmd, env, _cwd, _l = windows.build_launch(None, g)
    assert env["WINEPREFIX"] == ran["prefix"]                                       # the game later runs in the same private folder
    g2, text2 = windows.run_installer(None, setup, "Star Pilot", runner=lambda *a, **k: None)
    assert g2 is None and "no game program was found" in text2


def test_pc_games_wording(home):
    assert windows.PLATFORM_NAME == "PC Games" and "Wine" not in windows.UMU_HINT and "anti-cheat" in windows.ANTICHEAT_NOTE
    assert windows.is_installer("Setup.exe") and not windows.is_installer("Game.exe")
