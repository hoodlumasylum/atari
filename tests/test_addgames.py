"""The Add Games wizard: big buttons, Back everywhere, Esc/B, keyboard + mouse, the folder picker's starting places, the final result."""
import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt  # noqa: E402

from tests.test_features_ui import conf, open_menu_item, wait_for  # noqa: E402
from tests.test_studio_click import click_text, texts  # noqa: E402
from tests.test_ui_keys import Ui, app, pump  # noqa: E402,F401


def page(ui):
    return ui.win.property("pageName")


def on_screen(ui):
    return [t for t, _ in texts(ui)]


@pytest.fixture
def stick(tmp_path, monkeypatch):
    media = tmp_path / "media"
    s = media / "STICK"
    (s / "NES").mkdir(parents=True)
    (s / "NES" / "Brick Bash (USA).nes").write_bytes(b"x" * 2048)
    roms = tmp_path / "Games" / "Atari" / "nes"
    monkeypatch.setenv("ATARI_MEDIA_ROOTS", str(media))
    conf(tmp_path, f'[steam]\nenabled = false\n[systems.nes]\nroms = ["{roms}"]\n')
    return roms


def test_add_games_opens_a_wizard_with_three_big_buttons_and_back(app, tmp_path, monkeypatch, stick):
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        open_menu_item(ui, "add")
        assert ui.mode == "page" and page(ui) == "addgames"
        rows = ui.backend.pageRows("addgames")
        assert [r.get("id") for r in rows if r["kind"] != "info"] == [x for x in ["usb", "folder", "findgames", "biosfind", "windows", "bios", "downloads", "finish", "back"]]
        shown = on_screen(ui)
        for label in ("From a USB stick", "From a folder on this computer", "PC Games Installer (a PC game: .exe, setup.exe or .zip)", "Back"):
            assert label in shown, shown
        assert "Found: STICK" in " ".join(shown)                   # it says the stick was seen
        ui.key(Qt.Key_Escape)                                      # Esc / B = back out of the wizard
        assert ui.mode == "library" and not ui.warnings, ui.warnings
        open_menu_item(ui, "add")
        click_text(ui, "Back")                                     # the visible Back button
        assert ui.mode == "library"
    finally:
        ui.close()


def test_keyboard_path_into_the_folder_picker_and_back_out(app, tmp_path, monkeypatch, stick):
    (tmp_path / "home" / "Downloads").mkdir(parents=True)
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        open_menu_item(ui, "add")
        ui.key(Qt.Key_Down)                                        # USB -> folder
        ui.key(Qt.Key_Return)
        assert ui.mode == "browse"
        shown = on_screen(ui)
        assert shown.count("\u25c0  Back") == 1                    # a visible Back row
        assert "Home" in shown and any(t.startswith("USB / drive: STICK") for t in shown) and "Downloads" in shown
        ui.key(Qt.Key_Escape)
        assert ui.mode == "page" and page(ui) == "addgames"        # Esc returns to the wizard, not the library
        ui.key(Qt.Key_Down)
        ui.key(Qt.Key_Return)
        assert ui.mode == "browse"
        ui.key(Qt.Key_Return)                                      # focus starts on the first real place, not on Back
        assert ui.mode == "browse"
        ui.key(Qt.Key_Up)
        ui.key(Qt.Key_Return)                                      # Back row
        assert ui.mode == "page" and page(ui) == "addgames"
    finally:
        ui.close()


def test_windows_game_button_opens_the_file_picker_and_back_returns(app, tmp_path, monkeypatch, stick):
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        open_menu_item(ui, "add")
        click_text(ui, "PC Games Installer (a PC game: .exe, setup.exe or .zip)")
        assert ui.mode == "browse" and ui.win.property("browseTarget").toVariant()["files"] == "exe"
        ui.key(Qt.Key_Escape)
        assert ui.mode == "page" and page(ui) == "addgames"
    finally:
        ui.close()


def test_usb_to_done_with_mouse_clicks_and_a_clear_result(app, tmp_path, monkeypatch, stick):
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        open_menu_item(ui, "add")
        click_text(ui, "From a USB stick")
        assert ui.mode == "import" and ui.backend.importState == "drives"
        click_text(ui, "STICK", contains=True)
        assert wait_for(app, lambda: ui.backend.importState == "list"), ui.backend.importState
        assert ui.backend.importItems.rowCount() == 1
        click_text(ui, "COPY", contains=True)
        assert wait_for(app, lambda: ui.backend.importState == "done", 15), ui.backend.importState
        assert ui.backend.importMessage.startswith("Done - 1 game added")
        assert any(t.startswith("Done - 1 game added") for t in on_screen(ui))
        assert (stick / "Brick Bash (USA).nes").read_bytes() == b"x" * 2048
        click_text(ui, "DONE")
        assert ui.mode == "page" and page(ui) == "addgames"
        assert any("Last result:  Done - 1 game added" in t for t in on_screen(ui))
        click_text(ui, "Finished - show my games")
        assert ui.mode == "library" and not ui.warnings, ui.warnings
    finally:
        ui.close()


def test_every_add_games_entry_point_uses_the_wizard():
    from pathlib import Path
    qml = (Path(__file__).resolve().parent.parent / "atarilauncher" / "qml" / "Main.qml").read_text()
    assert qml.count('openImport("library")') == 0
    assert qml.count('openPage("addgames")') >= 5
