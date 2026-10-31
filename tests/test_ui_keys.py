"""Real key events (QTest) against the real QML window: first-run setup, Esc / B / Enter, focus loss, mouse clicks."""
import os
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ["ATARI_NO_GAMEPAD"] = "1"

from PySide6.QtCore import QPoint, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuick import QQuickItem  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from atarilauncher import backend as be, config  # noqa: E402
from atarilauncher.store import Store  # noqa: E402

QML = Path(__file__).resolve().parent.parent / "atarilauncher" / "qml" / "Main.qml"


@pytest.fixture(scope="module")
def app():
    return QGuiApplication.instance() or QGuiApplication(sys.argv[:1])


def pump(app, ms=60):
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        QTest.qWait(10)


class Ui:
    def __init__(self, app, tmp_path, monkeypatch, config_exists=False, home=None):
        self.app = app
        monkeypatch.setenv("ATARI_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("ATARI_CONFIG_DIR", str(tmp_path / "conf"))
        monkeypatch.setenv("HOME", str(home or tmp_path / "home"))
        (tmp_path / "home").mkdir(exist_ok=True)
        self.tmp = tmp_path
        if config_exists:
            (tmp_path / "conf").mkdir(exist_ok=True)
            (tmp_path / "conf" / "config.toml").write_text("[steam]\nenabled = false\n")
        cfg = config.load_config()
        cfg.steam_enabled = False
        cfg.fullscreen = False
        self.backend = be.Backend(cfg=cfg, store=Store(tmp_path / "data" / "state.json"), enable_gamepad=False)
        self.engine = QQmlApplicationEngine()
        self.warnings = []
        self.engine.warnings.connect(lambda ws: self.warnings.extend(w.toString() for w in ws))
        self.engine.rootContext().setContextProperty("backend", self.backend)
        self.engine.load(QUrl.fromLocalFile(str(QML)))
        assert self.engine.rootObjects(), self.warnings
        self.win = self.engine.rootObjects()[0]
        self.backend.set_window(self.win)
        self.win.resize(1280, 720)
        self.win.show()
        self.win.requestActivate()
        pump(app, 400)

    @property
    def mode(self):
        return self.win.property("mode")

    def key(self, k, ms=60):
        QTest.keyClick(self.win, k)
        pump(self.app, ms)

    def click(self, x, y):
        QTest.mouseClick(self.win, Qt.LeftButton, Qt.NoModifier, QPoint(int(x), int(y)))
        pump(self.app, 120)

    def root(self):
        return self.win.findChild(QQuickItem, "") and next(
            c for c in self.win.contentItem().childItems() if c.property("focus") is not None)

    def steal_focus(self):
        """Give the keyboard focus to some unrelated item (what a stray popup / IME / toolkit bug would do)."""
        from PySide6.QtQml import QQmlComponent
        comp = QQmlComponent(self.engine)
        comp.setData(b"import QtQuick\nItem { objectName: 'thief'; width: 5; height: 5; focus: true }", QUrl())
        thief = comp.create()
        thief.setParentItem(self.win.contentItem())
        thief.forceActiveFocus()
        pump(self.app, 20)
        return thief

    def close(self):
        self.win.close()
        self.engine.deleteLater()
        pump(self.app, 50)


@pytest.fixture
def ui_first_run(app, tmp_path, monkeypatch):
    ui = Ui(app, tmp_path, monkeypatch)
    yield ui
    ui.close()


def test_first_run_shows_setup_with_done_rows_top_and_bottom(ui_first_run):
    ui = ui_first_run
    assert ui.backend.firstRun and ui.mode == "setup"
    rows = ui.backend.setupRows()
    assert rows[0]["kind"] == "done" and rows[-1]["kind"] == "done"
    assert "DONE" in rows[0]["title"]
    assert not ui.warnings, ui.warnings


@pytest.mark.parametrize("k", [Qt.Key_Escape, Qt.Key_B])
def test_escape_or_b_dismisses_first_run_setup_to_empty_main_screen(ui_first_run, k):
    ui = ui_first_run
    ui.key(k)
    assert ui.mode == "library"
    assert not ui.backend.firstRun
    assert ui.backend.totalGames == 0
    assert (ui.tmp / "conf" / "config.toml").is_file()          # first run marked complete
    assert ui.backend.store.get_pref("setup_done") is True
    assert ui.backend.emptyMessage().startswith("No games yet")
    assert not ui.warnings, ui.warnings


def test_enter_on_top_and_bottom_done_row(app, tmp_path, monkeypatch):
    ui = Ui(app, tmp_path / "a", monkeypatch) if (tmp_path / "a").mkdir() is None else None
    try:
        ui.key(Qt.Key_Return)                    # cursor starts on the top DONE row
        assert ui.mode == "library" and not ui.backend.firstRun
    finally:
        ui.close()
    (tmp_path / "b").mkdir()
    ui = Ui(app, tmp_path / "b", monkeypatch)
    try:
        ui.key(Qt.Key_Up)                        # still on the top row
        for _ in range(120):                     # walk to the very bottom
            ui.key(Qt.Key_Down, 15)
        ui.key(Qt.Key_Return)
        assert ui.mode == "library" and not ui.backend.firstRun
    finally:
        ui.close()


def test_setup_only_shows_once(app, tmp_path, monkeypatch):
    ui = Ui(app, tmp_path, monkeypatch)
    ui.key(Qt.Key_Escape)
    ui.close()
    # restart: config now exists -> straight to the main screen
    ui2 = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        assert not ui2.backend.firstRun and ui2.mode == "library"
    finally:
        ui2.close()


def test_setup_once_even_if_config_cannot_be_written(app, tmp_path, monkeypatch):
    ui = Ui(app, tmp_path, monkeypatch)
    monkeypatch.setattr(be, "save_config", lambda cfg: (_ for _ in ()).throw(OSError("read-only")))
    ui.key(Qt.Key_Escape)
    assert ui.mode == "library"
    ui.close()
    monkeypatch.undo()
    ui2 = Ui(app, tmp_path, monkeypatch)
    try:
        assert not ui2.backend.firstRun
    finally:
        ui2.close()


def test_focus_loss_then_keys_still_work(ui_first_run):
    ui = ui_first_run
    # 1) some other item steals the keyboard focus
    ui.steal_focus()
    ui.key(Qt.Key_Down)
    ui.key(Qt.Key_Up)
    # 2) window deactivated / re-activated (alt-tab)
    ui.win.hide()
    pump(ui.app, 100)
    ui.win.show()
    ui.win.requestActivate()
    pump(ui.app, 200)
    ui.key(Qt.Key_Escape)
    assert ui.mode == "library"


def test_focus_taken_back_by_safety_net(ui_first_run):
    ui = ui_first_run
    thief = ui.steal_focus()
    pump(ui.app, 1000)   # the activeFocusItem handler / 700 ms timer restores it
    assert ui.win.activeFocusItem() is not thief
    ui.key(Qt.Key_Escape)
    assert ui.mode == "library"


def test_mouse_click_done_button_and_rows(app, tmp_path, monkeypatch):
    ui = Ui(app, tmp_path, monkeypatch)
    try:
        w = ui.win.width()
        u = min(ui.win.width() / 1920, ui.win.height() / 1080)
        ui.click(w - 48 * u - 150 * u, 34 * u + 30 * u)   # header DONE / CONTINUE button
        assert ui.mode == "library" and not ui.backend.firstRun
    finally:
        ui.close()


def test_mouse_click_rows_and_buttons_everywhere(app, tmp_path, monkeypatch):
    ui = Ui(app, tmp_path, monkeypatch, config_exists=True)
    from PySide6.QtCore import QMetaObject
    try:
        w, h = ui.win.width(), ui.win.height()
        u = min(w / 1920, h / 1080)
        assert ui.mode == "library"
        # Options menu opens with a key and closes by clicking outside it
        ui.key(Qt.Key_F10)
        assert ui.mode == "menu"
        ui.click(8, h / 2)
        assert ui.mode == "library"
        # Settings page: click the top DONE row, then re-open and click the header button
        QMetaObject.invokeMethod(ui.win, "openSetup")
        pump(ui.app, 100)
        assert ui.mode == "setup"
        ui.click(w / 2, 150)           # first row = DONE / CONTINUE (1280x720)
        assert ui.mode == "library"
        QMetaObject.invokeMethod(ui.win, "openSetup")
        pump(ui.app, 100)
        ui.click(w - 48 * u - 150 * u, 64 * u)
        assert ui.mode == "library"
        # a click on a settings row (Steam toggle, 2nd row) works and keeps the page open
        QMetaObject.invokeMethod(ui.win, "openSetup")
        pump(ui.app, 100)
        before = ui.backend.setupRows()[2]["value"]   # row 1 is Theme (kept at the top so it is easy to find)
        ui.click(w / 2, 262)                          # third row = Steam on/off
        assert ui.mode == "setup" and ui.backend.setupRows()[2]["value"] != before
        # the Emulators page and its BACK button
        ui.key(Qt.Key_Escape)
        assert ui.mode == "library"
        assert not ui.warnings, ui.warnings
    finally:
        ui.close()


def test_home_pad_toast_small_dismissable_and_repair_in_controllers(app, tmp_path, monkeypatch):
    """0.6.1: a slim note only for a pad that WAS connected and dropped; X / keyboard / mouse hide it; Settings toggle;
    Remove and re-pair stays in Settings > Controllers."""
    from PySide6.QtQuick import QQuickItem
    ui = Ui(app, tmp_path, monkeypatch, config_exists=True)
    try:
        called = []
        monkeypatch.setattr(ui.backend, "_bt_activate", lambda rid: called.append(rid) or "refresh")
        ui.win.resize(1366, 768)
        pad = {"mac": "AA:BB:CC:DD:EE:01", "name": "Wireless Controller"}
        ui.backend._on_pads_waiting([pad])           # paired but never seen connected: no note
        pump(app, 200)
        ban = ui.win.findChild(QQuickItem, "padWaitBanner")
        assert ban is not None and not ban.property("visible")
        ui.backend._on_pads_waiting([])
        ui.backend._pads_was_connected.add(pad["mac"])  # it was connected ... and drops
        ui.backend._on_pads_waiting([pad])
        pump(app, 300)
        assert ui.mode == "library" and ban.property("visible")
        assert ban.property("height") <= 50 and ban.property("x") + ban.property("width") <= 1366
        monkeypatch.setattr(ui.backend, "keyFromPad", lambda: True)
        ui.key(Qt.Key_Right, 100)                    # a pad press keeps it
        assert ban.property("visible")
        monkeypatch.setattr(ui.backend, "keyFromPad", lambda: False)
        ui.key(Qt.Key_Left, 100)                     # the keyboard hides it
        assert not ban.property("visible")
        rows = ui.backend._controllers_rows()
        assert any(r.get("id") == "btrepair:AA:BB:CC:DD:EE:01" for r in rows)
        # the Settings toggle is remembered
        assert any(r["kind"] == "padreminder" and r["value"] == "ON" for r in ui.backend.setupRows())
        ui.backend.togglePadReminder()
        assert ui.backend.cfg.pad_reminder is False
        from atarilauncher import config as _c
        assert _c.load_config(ui.backend.cfg.path).pad_reminder is False
    finally:
        ui.close()
