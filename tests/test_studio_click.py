"""The Studio's Record button, pressed with real mouse clicks on the real QML window (stub parecord/pactl, no microphone needed)."""
import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QMetaObject, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtQuick import QQuickItem  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from tests.test_features_ui import conf  # noqa: E402
from tests.test_studio import stub_bin  # noqa: E402
from tests.test_ui_keys import Ui, app, pump  # noqa: E402,F401


def texts(ui):
    out = []

    def walk(it):
        for c in it.childItems():
            t = c.property("text")
            if isinstance(t, str) and c.isVisible() and c.width() > 0:
                out.append((t, c))
            walk(c)
    walk(ui.win.contentItem())
    return out


def click_text(ui, text, contains=False):
    """Click the middle of the on-screen text, exactly where a finger or mouse would."""
    for t, it in texts(ui):
        if (text in t) if contains else (t == text):
            p = it.mapToScene(QPointF(it.width() / 2, it.height() / 2))
            QTest.mouseClick(ui.win, Qt.LeftButton, Qt.NoModifier, QPoint(int(p.x()), int(p.y())))
            pump(ui.app, 250)
            return
    raise AssertionError(f"nothing on screen says {text!r}: " + " | ".join(t for t, _ in texts(ui))[:600])


def open_record_page(ui):
    QMetaObject.invokeMethod(ui.win, "openStudio")
    pump(ui.app, 300)
    assert ui.mode == "studio"
    click_text(ui, "Record your voice", contains=True)
    assert ui.backend.studio.pageName == "record"


def make_ui(app, tmp_path, monkeypatch, **stub):
    d, _log = stub_bin(tmp_path, **stub)
    monkeypatch.setenv("PATH", str(d))
    conf(tmp_path)
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    ui.backend._sound_sink = lambda line: None
    return ui


def test_clicking_record_then_stop_saves_a_take(app, tmp_path, monkeypatch):
    ui = make_ui(app, tmp_path, monkeypatch)
    try:
        open_record_page(ui)
        click_text(ui, "Record")
        assert ui.backend.studio.recording, ui.backend.toast
        assert "RECORDING" in " ".join(t for t, _ in texts(ui))            # the red banner is on screen
        pump(app, 600)
        click_text(ui, "Stop recording")
        st = ui.backend.studio
        assert not st.recording and len(st.project.takes) == 1
        assert (st.project.folder / st.project.takes[0].file).is_file()
        assert "Saved Take 1" in ui.backend.toast
        assert not ui.warnings, ui.warnings
    finally:
        ui.close()


def test_a_microphone_that_fails_shows_the_reason_on_screen(app, tmp_path, monkeypatch):
    ui = make_ui(app, tmp_path, monkeypatch, fail=True)
    try:
        open_record_page(ui)
        click_text(ui, "Record")
        assert not ui.backend.studio.recording
        assert "microphone" in ui.backend.toast.lower() and "Connection refused" in ui.backend.toast
    finally:
        ui.close()


def test_no_recording_program_says_what_to_install(app, tmp_path, monkeypatch):
    ui = make_ui(app, tmp_path, monkeypatch, with_parecord=False)
    try:
        open_record_page(ui)
        click_text(ui, "Record")
        assert not ui.backend.studio.recording
        assert "pulseaudio-utils" in ui.backend.toast
    finally:
        ui.close()


def test_no_microphone_at_all_is_explained_in_the_list(app, tmp_path, monkeypatch):
    ui = make_ui(app, tmp_path, monkeypatch)
    try:
        monkeypatch.setattr("atarilauncher.studio.recorder.list_sources", lambda *a, **k: [])
        open_record_page(ui)
        assert any("No microphone" in t for t, _ in texts(ui)), [t for t, _ in texts(ui)]
    finally:
        ui.close()
