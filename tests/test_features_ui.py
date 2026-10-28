"""0.3.0 features through the real QML window (offscreen): Controls, BIOS import, update screen, covers, PC apps."""
import os
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt  # noqa: E402

from tests.fakeserver import Fake, PNG  # noqa: E402
from tests.test_ui_keys import Ui, app, pump  # noqa: E402,F401
from tests.test_updater import make_package, publish  # noqa: E402


def wait_for(app, cond, seconds=10):
    end = time.time() + seconds
    while time.time() < end:
        pump(app, 50)
        if cond():
            return True
    return False


def conf(tmp_path, text="[steam]\nenabled = false\n"):
    (tmp_path / "conf").mkdir(exist_ok=True)
    (tmp_path / "conf" / "config.toml").write_text(text)


MENU_ORDER = ["resume", "sort", "add", "bios", "studio", "winadd", "pickcover", "record", "recordings", "fix", "help", "rescan", "emus", "update", "settings", "full", "quit"]


def open_menu_item(ui, item_id):
    ui.key(Qt.Key_F10)
    assert ui.mode == "menu"
    for _ in range(MENU_ORDER.index(item_id)):
        ui.key(Qt.Key_Down, 20)
    ui.key(Qt.Key_Return)


def test_controls_screen_opens_and_closes(app, tmp_path, monkeypatch):
    conf(tmp_path)
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        open_menu_item(ui, "help")
        assert ui.mode == "page" and ui.win.property("pageName") == "help"
        rows = ui.win.property("pageName") and ui.backend.pageRows("help")
        idx = [r.get("id") for r in rows].index("controls")
        for _ in range(sum(1 for r in rows[:idx] if r["kind"] != "info")):
            ui.key(Qt.Key_Down, 20)
        ui.key(Qt.Key_Return)
        assert ui.mode == "controls"
        ui.key(Qt.Key_Down)
        ui.key(Qt.Key_Escape)
        assert ui.mode == "page"          # Back from Controls returns to the Help page
        ui.key(Qt.Key_Escape)
        assert ui.mode == "library" and not ui.warnings, ui.warnings
    finally:
        ui.close()


def test_settings_and_emulator_rows_for_030(app, tmp_path, monkeypatch):
    conf(tmp_path)
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        kinds = {r["kind"] for r in ui.backend.setupRows()}
        assert {"bios", "covers", "coversauto", "update", "updateauto", "emulators"} <= kinds
        rows = ui.backend.emulatorRows()
        ekinds = [r["kind"] for r in rows]
        assert "install" in ekinds and "bios" in ekinds and "controls" in ekinds and ekinds.count("app") == 16
        ps1 = next(r for r in rows if r.get("id") == "ps1")
        assert "BIOS" in ps1["detail"] and "your own console" in ps1["detail"]
        assert "apps" in [t["key"] for t in ui.backend.tiles]       # the PC Apps tile is always there
    finally:
        ui.close()


def test_add_bios_files_from_fake_usb_through_the_ui(app, tmp_path, monkeypatch):
    conf(tmp_path)
    media = tmp_path / "media"
    stick = media / "STICK"
    stick.mkdir(parents=True)
    (stick / "dc_boot.bin").write_bytes(b"\x01" * 2048)
    (stick / "bios7.bin").write_bytes(b"\x02" * 4096)
    monkeypatch.setenv("ATARI_MEDIA_ROOTS", str(media))
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        open_menu_item(ui, "bios")
        assert ui.mode == "import" and ui.backend.importKind == "bios"
        ui.key(Qt.Key_Return)                                   # the stick
        assert wait_for(app, lambda: ui.backend.importState == "list"), ui.backend.importState
        assert ui.backend.importItems.rowCount() == 2
        assert "consoles you own" in ui.backend.importMessage
        assert ui.backend.importItems.selectedCount() == 0     # unknown-checksum files start unticked ("check it")
        ui.key(Qt.Key_F)                                        # select all
        assert ui.backend.importItems.selectedCount() == 2
        ui.key(Qt.Key_Return)                                   # COPY
        assert wait_for(app, lambda: ui.backend.importState == "done")
        home = tmp_path / "home"
        assert (home / ".var/app/org.flycast.Flycast/data/flycast/dc_boot.bin").is_file()
        assert (home / ".var/app/org.libretro.RetroArch/config/retroarch/system/bios7.bin").is_file()
        assert "Copied" in ui.backend.importMessage
        ui.key(Qt.Key_Return)                                   # DONE
        assert ui.mode == "library" and not ui.warnings, ui.warnings
        # nothing from the stick was changed or removed
        assert (stick / "dc_boot.bin").read_bytes() == b"\x01" * 2048
    finally:
        ui.close()


def test_covers_download_updates_tiles_live(app, tmp_path, monkeypatch):
    f = Fake()
    try:
        folder = "Nintendo - Nintendo Entertainment System"
        f.listing(folder, ["Brick Bash (USA).png"])
        roms = tmp_path / "roms"
        roms.mkdir()
        (roms / "Brick Bash (USA) (Rev 1).nes").write_bytes(b"0")
        (roms / "Unknown Thing.nes").write_bytes(b"0")
        conf(tmp_path, f'[steam]\nenabled = false\n[systems.nes]\nroms = ["{roms}"]\n')
        monkeypatch.delenv("ATARI_NO_COVERS", raising=False)
        monkeypatch.setenv("ATARI_COVERS_THUMBS_URL", f.url)
        monkeypatch.setenv("ATARI_COVERS_STEAM_URL", f.url)
        monkeypatch.setenv("ATARI_COVERS_FAST", "1")
        ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
        try:
            assert ui.backend.totalGames == 2
            seen = []
            ui.backend.coversChanged.connect(lambda: seen.append(ui.backend.coverStatus))
            # the automatic run starts by itself after the scan (2.5 s) - or press the Settings button
            assert wait_for(app, lambda: (tmp_path / "data/covers/nes/Brick Bash (USA) (Rev 1).png").is_file(), 12)
            assert wait_for(app, lambda: not ui.backend.coversBusy)
            assert any(s.startswith("Covers ") for s in seen)
            g = next(g for g in ui.backend._all if g.title.startswith("Brick Bash"))
            assert g.cover.endswith("Brick Bash (USA) (Rev 1).png")
            assert not ui.warnings, ui.warnings
            # the ROM without a picture online stays without; pressing "Download covers" retries without crashing
            ui.backend.downloadCoversNow()
            assert wait_for(app, lambda: not ui.backend.coversBusy)
            assert "not found" in ui.backend.coverStatus or ui.backend.coverStatus.startswith("Downloaded")
        finally:
            ui.close()
    finally:
        f.stop()


def test_covers_offline_is_calm(app, tmp_path, monkeypatch):
    roms = tmp_path / "roms"
    roms.mkdir()
    for i in range(4):
        (roms / f"G{i}.nes").write_bytes(b"0")
    conf(tmp_path, f'[steam]\nenabled = false\n[systems.nes]\nroms = ["{roms}"]\n')
    monkeypatch.delenv("ATARI_NO_COVERS", raising=False)
    monkeypatch.setenv("ATARI_COVERS_THUMBS_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("ATARI_COVERS_STEAM_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("ATARI_COVERS_FAST", "1")
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        ui.backend.downloadCoversNow()
        assert wait_for(app, lambda: not ui.backend.coversBusy and ui.backend.coverStatus.startswith("Offline"), 20)
        assert ui.backend.totalGames == 4 and not ui.warnings
    finally:
        ui.close()


def installed_copy(tmp_path):
    root = tmp_path / "atari-launcher"
    (root / ".venv").mkdir(parents=True)
    (root / "atarilauncher").mkdir()
    (root / "atarilauncher" / "__init__.py").write_text('__version__ = "0.3.0"\n')
    (root / "install.sh").write_text("#!/bin/sh\n")
    return root


def test_update_screen_end_to_end_with_fake_release_server(app, tmp_path, monkeypatch):
    f = Fake()
    try:
        monkeypatch.setenv("ATARI_UPDATE_API", publish(f, "9.9.9", body="Shiny new things."))
        root = installed_copy(tmp_path)
        monkeypatch.setenv("ATARI_UPDATE_ROOT", str(root))
        conf(tmp_path)
        (tmp_path / "conf" / "config.toml").write_text("[steam]\nenabled = false\n")
        mine = (tmp_path / "conf" / "config.toml").read_text()
        ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
        try:
            spawned = []
            ui.backend._restart_spawn = lambda cmd, **kw: spawned.append(cmd)
            quits = []
            monkeypatch.setattr(ui.backend, "quit", lambda: quits.append(1))
            open_menu_item(ui, "update")
            assert ui.mode == "update"
            assert wait_for(app, lambda: ui.backend.updateState == "available")
            assert ui.backend.updateVersion == "9.9.9" and "Shiny" in ui.backend.updateNotes
            assert ui.backend.updateAvailable                               # the top-bar badge shows
            ui.key(Qt.Key_Down)                                             # scroll notes: harmless
            ui.key(Qt.Key_Return)                                           # INSTALL UPDATE
            assert wait_for(app, lambda: ui.backend.updateState in ("done", "error"), 30), ui.backend.updateText
            assert ui.backend.updateState == "done", ui.backend.updateText
            assert (root / "atarilauncher" / "__init__.py").read_text().strip().endswith('"9.9.9"')
            assert (tmp_path / "conf" / "config.toml").read_text() == mine   # settings untouched
            assert not ui.backend.updateAvailable
            ui.key(Qt.Key_Return)                                           # RESTART CODE NOW
            assert spawned and spawned[0][-1] != "" and str(root / "run.sh") in spawned[0] and quits == [1]
            assert not ui.warnings, ui.warnings
        finally:
            ui.close()
    finally:
        f.stop()


def test_update_screen_offline_error_and_escape(app, tmp_path, monkeypatch):
    monkeypatch.setenv("ATARI_UPDATE_API", "http://127.0.0.1:9/none")
    monkeypatch.setenv("ATARI_UPDATE_ROOT", str(installed_copy(tmp_path)))
    conf(tmp_path)
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        open_menu_item(ui, "update")
        assert wait_for(app, lambda: ui.backend.updateState == "error", 15)
        assert "internet" in ui.backend.updateText
        ui.key(Qt.Key_Escape)
        assert ui.mode == "library" and not ui.warnings
    finally:
        ui.close()


def test_silent_daily_check_shows_badge_and_respects_toggle(app, tmp_path, monkeypatch):
    f = Fake()
    try:
        monkeypatch.setenv("ATARI_UPDATE_API", publish(f, "9.9.9"))
        monkeypatch.delenv("ATARI_NO_UPDATE_CHECK", raising=False)
        conf(tmp_path, "[steam]\nenabled = false\n[updates]\ncheck = false\n")
        ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
        try:
            pump(app, 300)
            assert not ui.backend.updateAvailable and ui.backend.updateAuto is False
        finally:
            ui.close()
        conf(tmp_path, "[steam]\nenabled = false\n")
        import atarilauncher.backend as be
        monkeypatch.setattr(be.QTimer, "singleShot", be.QTimer.singleShot)   # (no-op: timer interval is 8 s)
        ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
        try:
            ui.backend._upd_timer.setInterval(50)
            ui.backend._upd_timer.start()
            assert wait_for(app, lambda: ui.backend.updateAvailable, 10)
            assert ui.backend.updateVersion == "9.9.9" and ui.backend.updateState == "idle"     # silent: no screen
            assert ui.backend.store.get_pref("update_last_check", 0) > 0
        finally:
            ui.close()
        # a second start within a day does not even ask (nothing is fetched), but the badge is remembered
        f.hits.clear()
        ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
        try:
            pump(app, 300)
            assert ui.backend.updateAvailable and not ui.backend._upd_timer.isActive() and f.hits == []
        finally:
            ui.close()
    finally:
        f.stop()


def test_minimise_for_game_and_restore(app, tmp_path, monkeypatch):
    """While a ROM game runs Code steps aside (so the emulator gets the keyboard) and comes back afterwards."""
    conf(tmp_path)
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        calls = []
        win = ui.win
        monkeypatch.setattr(win, "showMinimized", lambda: calls.append("min"))
        monkeypatch.setattr(ui.backend, "_window", win)
        monkeypatch.delenv("ATARI_NO_MINIMIZE", raising=False)
        ui.backend._running = True
        ui.backend._running_is_rom = True
        ui.backend._hide_timer.setInterval(20)
        ui.backend._on_session_started()
        assert wait_for(app, lambda: calls == ["min"], 3)
        assert ui.backend._minimized_for_game
        ui.backend._on_session_ended("gid", "t", 0.0, "")
        assert not ui.backend._minimized_for_game
    finally:
        ui.close()


# ----------------------------------------------------------------- 0.3.0: Windows games, Help, Fix my game
def page(ui):
    return ui.win.property("pageName")


def press_row(ui, rows, row_id):
    """Move the cursor to the selectable row with this id (the way a player would) and press Enter."""
    sel = [r for r in rows if r["kind"] != "info"]
    ids = [r.get("id") for r in sel]
    for _ in range(ids.index(row_id)):
        ui.key(Qt.Key_Down, 20)
    ui.key(Qt.Key_Return)


def stub_umu(tmp_path, monkeypatch):
    import stat
    b = tmp_path / "bin"
    b.mkdir(exist_ok=True)
    rec = tmp_path / "ran.txt"
    s = b / "umu-run"
    s.write_text(f'#!/bin/sh\necho "$@ | $WINEPREFIX" > {rec}\nsleep 0.3\n')
    s.chmod(s.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(b) + os.pathsep + os.environ["PATH"])
    return rec


def test_add_a_windows_exe_with_keyboard_only_and_play_it(app, tmp_path, monkeypatch):
    import zipfile  # noqa: F401
    conf(tmp_path)
    rec = stub_umu(tmp_path, monkeypatch)
    dl = tmp_path / "home" / "Downloads"
    dl.mkdir(parents=True)
    (dl / "Dreams_of_Saturn.exe").write_bytes(b"MZ" + b"\0" * 100)
    monkeypatch.setenv("ATARI_NO_MINIMIZE", "1")
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        open_menu_item(ui, "winadd")
        assert ui.mode == "browse"
        ui.key(Qt.Key_Down)                    # past ".. (go up)" onto the file
        ui.key(Qt.Key_Return)
        assert ui.mode == "page" and page(ui) == "winform"
        rows = ui.backend.pageRows("winform")
        assert any(r.get("value") == "Dreams of Saturn" for r in rows)
        # rename it with the on-screen keyboard: Enter on "Name" opens it, type, Enter = done
        press_row(ui, rows, "name")
        assert ui.mode == "search"
        for ch in " 2":
            ui.key(Qt.Key_2 if ch == "2" else Qt.Key_Space)
        ui.key(Qt.Key_Return)
        assert ui.mode == "page" and page(ui) == "winform"
        assert ui.backend.winName() == "Dreams of Saturn 2"
        rows = ui.backend.pageRows("winform")
        press_row(ui, rows, "add")
        assert ui.mode == "library" and not ui.warnings, ui.warnings
        assert ui.backend.currentFilter == "windows"
        assert [g.title for g in ui.backend._all if g.platform == "windows"] == ["Dreams of Saturn 2"]
        ui.backend.launch(0)
        assert wait_for(app, lambda: rec.exists() and not ui.backend.running, 10)
        assert "Dreams_of_Saturn.exe" in rec.read_text() and "prefixes/dreams-of-saturn-2" in rec.read_text()
    finally:
        ui.close()


def test_add_a_zip_with_several_exes_shows_a_pick_list(app, tmp_path, monkeypatch):
    import zipfile
    conf(tmp_path)
    dl = tmp_path / "home" / "Downloads"
    dl.mkdir(parents=True)
    with zipfile.ZipFile(dl / "Fan_Game_v2.zip", "w") as zf:
        zf.writestr("Fan Game/Fan.exe", b"MZ" + b"\0" * 9000)
        zf.writestr("Fan Game/Fan_Data/a.dat", b"1")
        zf.writestr("Fan Game/Config.exe", b"MZ" + b"\0" * 500)
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        open_menu_item(ui, "winadd")
        ui.key(Qt.Key_Down)
        ui.key(Qt.Key_Return)
        assert wait_for(app, lambda: ui.mode == "page" and page(ui) == "winchoose", 10), (ui.mode, page(ui))
        rows = ui.backend.pageRows("winchoose")
        assert rows[0]["title"].endswith("Fan.exe") and "most likely" in rows[0]["detail"]
        ui.key(Qt.Key_Return)                  # the first one
        assert page(ui) == "winform"
        assert ui.backend.winName() == "Fan Game v2"
        assert (tmp_path / "home/Games/Atari/windows/Fan Game v2/Fan Game/Fan.exe").is_file()
        ui.key(Qt.Key_Escape)                  # cancel: nothing is added
        assert ui.mode == "library" and not [g for g in ui.backend._all if g.platform == "windows"]
        assert not ui.warnings, ui.warnings
    finally:
        ui.close()


def test_an_archive_without_a_program_explains_itself(app, tmp_path, monkeypatch):
    import zipfile
    conf(tmp_path)
    dl = tmp_path / "home" / "Downloads"
    dl.mkdir(parents=True)
    with zipfile.ZipFile(dl / "Readme.zip", "w") as zf:
        zf.writestr("readme.txt", b"hello")
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        open_menu_item(ui, "winadd")
        ui.key(Qt.Key_Down)
        ui.key(Qt.Key_Return)
        assert wait_for(app, lambda: ui.mode == "library", 10)
        assert "could not find a Windows program" in ui.backend.toast
    finally:
        ui.close()


def test_help_page_copy_log_and_two_press_reset(app, tmp_path, monkeypatch):
    conf(tmp_path, "[steam]\nenabled = false\n[general]\nfullscreen = false\n")
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        (tmp_path / "data").mkdir(exist_ok=True)
        (tmp_path / "data" / "launch.log").write_text("2026-10-28 10:00:00 error: boom\n")
        before = ui.backend.store.get_pref("sort", "az")
        ui.backend.store.add_playtime("rom:keep", 600)
        open_menu_item(ui, "help")
        assert page(ui) == "help"
        rows = ui.backend.pageRows("help")
        ck = [r["id"] for r in rows if str(r.get("id", "")).startswith("ck_")]
        assert ck == ["ck_emus", "ck_games", "ck_bios", "ck_covers", "ck_steam"]       # the first-run steps
        press_row(ui, rows, "copylog")
        from PySide6.QtGui import QGuiApplication
        assert "error: boom" in QGuiApplication.clipboard().text()
        ui.key(Qt.Key_Escape)
        # Safe mode needs two presses
        open_menu_item(ui, "help")
        rows = ui.backend.pageRows("help")
        press_row(ui, rows, "reset")
        assert any("Press again" in r.get("title", "") for r in ui.backend.pageRows("help"))
        assert (tmp_path / "conf" / "config.toml").exists()
        ui.key(Qt.Key_Return)                           # the cursor stayed on the reset row: this is the second press
        saved = list((tmp_path / "conf").glob("config.toml.before-reset-*"))
        assert saved and "fullscreen = false" in saved[0].read_text()
        assert ui.backend.store.playtime("rom:keep") == 600
        assert not ui.warnings, ui.warnings
    finally:
        ui.close()


def test_fix_my_game_names_the_problem_in_plain_english(app, tmp_path, monkeypatch):
    roms = tmp_path / "roms"
    roms.mkdir()
    conf(tmp_path, f'[steam]\nenabled = false\n[systems.genesis]\nroms = ["{roms}"]\n')
    (roms / "Sonic The Hedgehog (USA).md").write_bytes(b"x" * 600)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        ui.backend.rescan(toast=False)
        pump(app, 100)
        assert [g.title for g in ui.backend._all if g.platform == "genesis"], "the test ROM was not found"
        open_menu_item(ui, "fix")
        assert ui.mode == "page" and page(ui) == "fix"
        rows = ui.backend.pageRows("fix")
        titles = " | ".join(r["title"] for r in rows)
        assert "Sonic" in titles and "Game file" in titles and "Emulator" in titles and "Controller" in titles
        ui.key(Qt.Key_Escape)
        assert ui.mode == "library" and not ui.warnings, ui.warnings
    finally:
        ui.close()
