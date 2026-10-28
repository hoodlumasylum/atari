"""Studio first aid: diagnosis, the one-press fix with stubbed pip/pkexec, the on-screen Fix Studio button, and the log."""
import os
import subprocess
import sys

import pytest

from atarilauncher import studio_fix

has = lambda *names: (lambda n: "/usr/bin/" + n if n in names else None)  # noqa: E731


def test_problems_are_explained_in_plain_english():
    ps = studio_fix.problems(False, which=has("pkexec", "apt-get"), sources=[])
    assert [p.id for p in ps] == ["numpy", "audio-tools"]
    assert ps[0].fixable and "numpy" in ps[0].text and ps[1].fixable
    assert studio_fix.problems(True, which=has("parecord", "pactl"), sources=[])[0].id == "microphone"
    assert studio_fix.problems(True, which=has("parecord", "pactl"), sources=[{"id": "x"}]) == []
    assert "Everything" in studio_fix.summary([])


def test_fix_installs_numpy_with_pip_and_recording_tools_with_pkexec():
    calls = []

    def run(cmd, out, cancel=None):
        calls.append(cmd)
        out("ok")
        return 0
    ps = studio_fix.problems(False, which=has("pkexec", "apt-get"))
    ok, text = studio_fix.fix(ps, lambda l: None, run=run, which=has("pkexec", "apt-get", "parecord"), python="/venv/bin/python")
    assert ok and "numpy" in text
    assert ["/venv/bin/python", "-m", "pip", "install", "--disable-pip-version-check", "numpy>=1.24"] in calls
    assert ["pkexec", "apt-get", "install", "-y", "pulseaudio-utils"] in calls


def test_fix_reports_failure_honestly():
    ok, text = studio_fix.fix(studio_fix.problems(False, which=has()), lambda l: None, run=lambda c, o, x=None: 1, which=has())
    assert not ok and "Could not add: numpy" in text and "install.sh" in text


def test_log_goes_to_the_logs_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("ATARI_DATA_DIR", str(tmp_path))
    studio_fix.log("hello\nworld")
    assert studio_fix.log_file() == tmp_path / "logs" / "studio.log"
    assert studio_fix.read_log()[-1].endswith("hello | world")


def test_importing_the_studio_without_numpy_does_not_break_atari(tmp_path):
    code = ("import sys; sys.modules['numpy'] = None\n"
            "from atarilauncher import studio_ui, studio_fix\n"
            "assert studio_ui.mixer is None and not studio_fix.numpy_ok()\n"
            "print('ok')")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       env=dict(os.environ, QT_QPA_PLATFORM="offscreen"), cwd=os.getcwd())
    assert r.returncode == 0 and "ok" in r.stdout, r.stderr


# ------------------------------------------------------------------ on screen
pytest.importorskip("PySide6")
from PySide6.QtCore import QMetaObject  # noqa: E402

from tests.test_features_ui import conf  # noqa: E402
from tests.test_studio_click import click_text, texts  # noqa: E402
from tests.test_ui_keys import Ui, app, pump  # noqa: E402,F401


def test_fix_studio_button_on_the_studio_screen(app, tmp_path, monkeypatch):
    from atarilauncher import studio_ui
    state = {"numpy": False}
    monkeypatch.setattr(studio_ui, "numpy_available", lambda: state["numpy"])
    conf(tmp_path)
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        def fake_fix(ps, out, **kw):
            state["numpy"] = True
            return True, "Added numpy. The Studio is ready."
        monkeypatch.setattr(studio_fix, "fix", fake_fix)
        QMetaObject.invokeMethod(ui.win, "openStudio")
        pump(app, 300)
        st = ui.backend.studio
        assert not st.available
        assert any("Fix Studio" == t for t, _ in texts(ui)) and any("cannot start" in t.lower() or "numpy" in t for t, _ in texts(ui))
        click_text(ui, "Fix Studio")
        for _ in range(40):
            pump(app, 100)
            if st.available:
                break
        assert st.available and "ready" in ui.backend.toast.lower()
        assert any("Make a beat" in t for t, _ in texts(ui))                      # the real Studio is on screen now
        assert "Fix Studio finished ok=True" in " ".join(studio_fix.read_log())
        assert not ui.warnings, ui.warnings
    finally:
        ui.close()


def test_help_has_a_fix_studio_row_and_copy_log_includes_the_studio_log(app, tmp_path, monkeypatch):
    conf(tmp_path)
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        studio_fix.log("test line for the log")
        ids = [r.get("id") for r in ui.backend.pageRows("help")]
        assert "studiofix" in ids
        assert "test line for the log" in ui.backend.copyLog()
    finally:
        ui.close()
