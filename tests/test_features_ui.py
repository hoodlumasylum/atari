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


MENU_ORDER = ["resume", "sort", "add", "bios", "rescan", "emus", "controls", "update", "settings", "full", "quit"]


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
        open_menu_item(ui, "controls")
        assert ui.mode == "controls"
        ui.key(Qt.Key_Down)
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
        assert "install" in ekinds and "bios" in ekinds and "controls" in ekinds and ekinds.count("app") == 8
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
            ui.key(Qt.Key_Return)                                           # RESTART ATARI NOW
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
    """While a ROM game runs Atari steps aside (so the emulator gets the keyboard) and comes back afterwards."""
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
