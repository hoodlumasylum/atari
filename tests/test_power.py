import os
import subprocess
from pathlib import Path

import pytest

from atarilauncher import kiosk, power

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt  # noqa: E402
from tests.test_features_ui import conf, open_menu_item, wait_for  # noqa: E402
from tests.test_ui_keys import Ui, app  # noqa: E402,F401


def cp(rc=0, err=""):
    return subprocess.CompletedProcess([], rc, "", err)


class Fake:
    """A pretend subprocess.run: answers per command and records every call."""
    def __init__(self, answers=None):
        self.calls, self.answers = [], answers or {}

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        assert kw.get("stdin") == subprocess.DEVNULL                       # never waits for a keyboard
        a = self.answers.get(cmd[0], cp())
        if isinstance(a, Exception):
            raise a
        return a


ALL = lambda n: "/usr/bin/" + n  # noqa: E731


@pytest.mark.parametrize("action,word", [("reboot", "Restarting"), ("poweroff", "Shutting down"), ("suspend", "sleep")])
def test_the_normal_case_is_plain_systemctl_without_a_password(action, word):
    f = Fake()
    ok, text = power.run(action, f, ALL)
    assert ok and word.lower() in text.lower() and f.calls == [["systemctl", action]]


def test_polkit_refusal_falls_back_to_pkexec():
    f = Fake({"systemctl": cp(1, "Interactive authentication required.")})
    ok, text = power.run("reboot", f, ALL)
    assert ok and f.calls == [["systemctl", "reboot"], ["pkexec", "systemctl", "reboot"]]


def test_a_closed_password_window_stops_there_and_says_so():
    f = Fake({"systemctl": cp(1, "denied"), "pkexec": cp(126)})
    ok, text = power.run("poweroff", f, ALL)
    assert not ok and "password window was closed" in text and len(f.calls) == 2


def test_everything_refusing_gives_the_reason_and_a_manual_command():
    f = Fake({"systemctl": cp(1, "Failed to reboot system via logind: Access denied"), "pkexec": cp(1, "Error executing command as another user")})
    ok, text = power.run("reboot", f, ALL)
    assert not ok and "Error executing command" in text and "systemctl reboot" in text and "power button" in text


def test_without_systemctl_loginctl_then_pkexec_is_used():
    f = Fake({"loginctl": cp(1, "nope")})
    which = lambda n: None if n == "systemctl" else "/usr/bin/" + n  # noqa: E731
    power.run("suspend", f, which)
    assert f.calls == [["loginctl", "suspend"], ["pkexec", "loginctl", "suspend"]]
    ok, text = power.run("reboot", Fake(), lambda n: None)
    assert not ok and "power button" in text


def test_a_slow_shutdown_and_missing_programs_are_not_errors():
    ok, _ = power.run("poweroff", Fake({"systemctl": subprocess.TimeoutExpired("systemctl", 1)}), ALL)
    assert ok
    f = Fake({"systemctl": FileNotFoundError("gone")})
    assert power.run("reboot", f, ALL)[0]                                   # pkexec answered fine
    assert power.run("explode", Fake(), ALL)[0] is False and power.command_chain("explode", ALL) == []


def test_only_restart_and_shutdown_ask_first():
    assert power.NEEDS_CONFIRM == ("reboot", "poweroff") and "suspend" not in power.NEEDS_CONFIRM


# ------------------------------------------------------------------ the screens
@pytest.fixture
def ui(app, tmp_path, monkeypatch):
    conf(tmp_path, "[steam]\nenabled = false\n")
    u = Ui(app, tmp_path, monkeypatch, config_exists=False)
    u.ran = []
    u.backend._power_run = lambda action: (u.ran.append(action) or (True, power.ACTIONS[action][1]))
    yield u
    u.close()


def page(ui):
    return ui.win.property("pageName")


def ids(ui):
    return [r.get("id") for r in ui.backend.pageRows("power") if r["kind"] != "info"]


def test_power_is_the_last_options_entry_and_reachable_by_keyboard(ui):
    qml = (Path(power.__file__).parent / "qml" / "Main.qml").read_text()
    assert 'id: "power", title: "Power:' in qml and 'id === "power"' in qml
    open_menu_item(ui, "power")
    assert ui.mode == "page" and page(ui) == "power"
    assert ids(ui) == ["power_restartcode", "power_quitcode", "power_reboot", "power_poweroff", "power_suspend", "back"]
    assert ui.backend.pageTitle("power") == "POWER"
    ui.key(Qt.Key_Escape)
    assert ui.mode in ("menu", "library") and not ui.warnings


def go(ui, row_id):
    rows = [r for r in ui.backend.pageRows("power") if r["kind"] != "info"]
    for _ in range([r["id"] for r in rows].index(row_id)):
        ui.key(Qt.Key_Down)
    ui.key(Qt.Key_Return)


def test_restart_device_asks_first_and_a_stray_enter_cancels(ui):
    open_menu_item(ui, "power")
    go(ui, "power_reboot")
    assert ids(ui) == ["power_no", "power_yes"]                              # the safe answer comes first
    text = " ".join(r.get("title", "") for r in ui.backend.pageRows("power"))
    assert "Really restart the computer?" in text and "not saved will be lost" in text
    ui.key(Qt.Key_Return)                                                    # Enter on the first (selected) row = No
    assert ui.ran == [] and "power_reboot" in ids(ui)
    go(ui, "power_reboot")
    ui.key(Qt.Key_Down)
    ui.key(Qt.Key_Return)                                                    # Yes
    assert wait_for(ui.app, lambda: ui.ran == ["reboot"], 5)
    assert "Restarting" in ui.backend.toast and ui.mode == "library"


def test_shut_down_asks_first_and_escape_leaves_without_doing_anything(ui):
    open_menu_item(ui, "power")
    go(ui, "power_poweroff")
    assert "Really shut the computer down?" in " ".join(r.get("title", "") for r in ui.backend.pageRows("power"))
    ui.key(Qt.Key_Escape)
    ui.key(Qt.Key_Escape)
    assert ui.ran == []
    ui.backend.powerReset()                                                  # the menu entry resets the question when reopened
    assert "power_reboot" in ids(ui) and "power_yes" not in ids(ui)


def test_the_question_is_gone_when_the_menu_entry_is_opened_again(ui):
    open_menu_item(ui, "power")
    go(ui, "power_poweroff")
    while ui.mode == "page":
        ui.key(Qt.Key_Escape)
    if ui.mode == "menu":
        ui.key(Qt.Key_F10)
    assert ui.mode == "library"
    open_menu_item(ui, "power")
    assert "power_yes" not in ids(ui) and ui.ran == []


def test_sleep_needs_no_question(ui):
    open_menu_item(ui, "power")
    go(ui, "power_suspend")
    assert wait_for(ui.app, lambda: ui.ran == ["suspend"], 5)


def test_a_refusal_is_shown_in_plain_words(ui):
    ui.backend._power_run = lambda action: (False, "Could not restart the computer (Access denied). Use the power button.")
    open_menu_item(ui, "power")
    go(ui, "power_reboot")
    ui.key(Qt.Key_Down)
    ui.key(Qt.Key_Return)
    assert wait_for(ui.app, lambda: "Access denied" in ui.backend.toast, 5)


def test_demo_mode_never_touches_the_computer(ui):
    ui.backend._demo = True
    ui.backend.doPower("poweroff")
    ui.backend.restartCode()
    assert ui.ran == [] and "Demo mode" in ui.backend.toast


def test_restart_code_in_the_code_only_session_ends_code_so_the_session_starts_it_again(ui, monkeypatch):
    quits, spawned = [], []
    monkeypatch.setattr(ui.backend, "quit", lambda: quits.append(1))
    ui.backend._restart_spawn = lambda cmd, **kw: spawned.append(cmd)
    monkeypatch.setenv("ATARI_KIOSK", "1")
    assert [r["title"] for r in ui.backend.pageRows("power") if r.get("id") == "power_restartcode"] == ["Restart CodeAque"]
    assert "power_quitcode" not in ids(ui)                                   # in CodeAque-only mode there is no Quit
    ui.backend.pageActivate("power", "power_restartcode")
    assert quits == [1] and spawned == []                                    # no second copy: the session program restarts it


def test_restart_code_on_the_desktop_relaunches_it_and_quit_just_quits(ui, monkeypatch):
    quits, spawned = [], []
    monkeypatch.setattr(ui.backend, "quit", lambda: quits.append(1))
    ui.backend._restart_spawn = lambda cmd, **kw: spawned.append(cmd)
    monkeypatch.delenv("ATARI_KIOSK", raising=False)
    ui.backend.pageActivate("power", "power_restartcode")
    assert len(spawned) == 1 and spawned[0][0] == "bash"
    assert "run.sh" in " ".join(spawned[0]) and quits == [1]
    quits.clear()
    ui.backend.pageActivate("power", "power_quitcode")
    assert quits == [1] and len(spawned) == 1


def test_it_works_with_the_real_command_runner_without_touching_the_system(ui, monkeypatch):
    calls = []
    monkeypatch.setattr(power.subprocess, "run", lambda cmd, **kw: (calls.append(cmd) or cp()))
    monkeypatch.setattr(power.shutil, "which", ALL)
    assert power.run("reboot")[0] and calls == [["systemctl", "reboot"]]
