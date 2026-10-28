"""The in-app administrator password: sudo -S fed from CodeAque's own dialog instead of a pkexec window that cannot show in CodeAque-only mode."""
import os
import stat
import subprocess
import threading
import time

import pytest

from atarilauncher import appinstall, kiosk, quietboot, rootauth

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QObject, Qt  # noqa: E402
from tests.test_features_ui import conf  # noqa: E402
from tests.test_ui_keys import Ui, app, pump  # noqa: E402,F401

PASSWORD = "hunter2 & co"


@pytest.fixture(autouse=True)
def clean():
    rootauth.set_provider(None)
    yield
    rootauth.set_provider(None)


@pytest.fixture
def fake_sudo(tmp_path, monkeypatch):
    """A `sudo` that reads the password from stdin like `sudo -S`, accepts only PASSWORD, and then runs the command after `--` / `true`.
    It records its own command line (which must never contain the password)."""
    d = tmp_path / "bin"
    d.mkdir()
    s = d / "sudo"
    s.write_text(f"""#!/bin/sh
echo "$@" >> {tmp_path}/sudo.args
read pw
if [ "$pw" != '{PASSWORD}' ]; then echo "Sorry, try again." >&2; exit 1; fi
while [ "$1" != "--" ] && [ "$1" != "true" ] && [ $# -gt 0 ]; do shift; done
[ "$1" = "--" ] && shift
exec "$@"
""")
    s.chmod(0o755)
    monkeypatch.setenv("PATH", f"{d}:{os.environ['PATH']}")
    monkeypatch.setattr(rootauth.os, "geteuid", lambda: 1000)
    return tmp_path


def lines_of(out):
    return lambda l: out.append(l)


def test_without_a_dialog_nothing_changes_pkexec_is_still_used(fake_sudo):
    cmd, secret, early = rootauth.prepare(["pkexec", "sh", "-c", "x"])
    assert cmd == ["pkexec", "sh", "-c", "x"] and secret is None and early is None
    assert rootauth.prepare(["ls"]) == (["ls"], None, None)


def test_a_typed_password_runs_the_command_as_sudo_without_showing_it_anywhere(fake_sudo):
    asked = []
    rootauth.set_provider(lambda prompt, error: asked.append((prompt, error)) or PASSWORD)
    out = []
    rc = appinstall.stream_run(["pkexec", "sh", "-c", "echo ran-as-root"], lambda l: out.append(l))
    assert rc == 0 and out == ["ran-as-root"]
    assert asked == [(asked[0][0], "")] and "password" in asked[0][0].lower()
    recorded = (fake_sudo / "sudo.args").read_text()
    assert PASSWORD not in recorded and "-S" in recorded and "-k" in recorded            # never on a command line
    assert PASSWORD not in "".join(out)


def test_a_wrong_password_asks_again_with_the_reason_then_works(fake_sudo):
    answers = iter(["nope", "", PASSWORD])
    seen = []
    rootauth.set_provider(lambda prompt, error: seen.append(error) or next(answers))
    out = []
    assert appinstall.stream_run(["pkexec", "sh", "-c", "echo ok"], lambda l: out.append(l)) == 0 and out == ["ok"]
    assert seen[0] == "" and seen[1] == "Wrong password." and "Type the password" in seen[2]


def test_five_wrong_passwords_give_up_without_running_anything(fake_sudo):
    rootauth.set_provider(lambda prompt, error: "wrong")
    marker = fake_sudo / "ran"
    rc = appinstall.stream_run(["pkexec", "sh", "-c", f"touch {marker}"], lambda l: None)
    assert rc == rootauth.CANCELLED and not marker.exists() and "five times" in rootauth.last_error


def test_cancelling_the_dialog_is_exit_126_and_the_scripts_say_so(fake_sudo):
    rootauth.set_provider(lambda prompt, error: None)
    assert appinstall.stream_run(["pkexec", "true"], lambda l: None) == 126
    ok, text = kiosk._result_text(126, "x", "y")
    assert not ok and "password window was closed" in text
    assert "No password was entered" in quietboot.explain(126, "x", [])


def test_a_user_who_may_not_use_sudo_gets_a_plain_message(tmp_path, monkeypatch):
    d = tmp_path / "bin"
    d.mkdir()
    (d / "sudo").write_text("#!/bin/sh\necho 'hazel is not in the sudoers file.' >&2\nexit 1\n")
    (d / "sudo").chmod(0o755)
    monkeypatch.setenv("PATH", f"{d}:" + "/usr/bin:/bin")        # no pkexec in this PATH
    monkeypatch.setattr(rootauth.shutil, "which", lambda n: str(d / n) if n == "sudo" else None)
    monkeypatch.setattr(rootauth.os, "geteuid", lambda: 1000)
    rootauth.set_provider(lambda p, e: "anything")
    assert appinstall.stream_run(["pkexec", "true"], lambda l: None) == rootauth.REFUSED
    ok, text = kiosk._result_text(rootauth.REFUSED, "x", "y")
    assert not ok and "not allowed to use administrator rights" in text
    assert "not allowed" in quietboot.explain(rootauth.REFUSED, "x", [])


def test_the_password_is_remembered_for_one_multi_step_action_only(fake_sudo, monkeypatch):
    n = []
    rootauth.set_provider(lambda p, e: n.append(1) or PASSWORD)
    for _ in range(3):
        assert appinstall.stream_run(["pkexec", "true"], lambda l: None) == 0
    assert len(n) == 1                                         # one dialog for a flow with several steps
    monkeypatch.setattr(rootauth.time, "monotonic", lambda t=time.monotonic(): t + 200)
    assert appinstall.stream_run(["pkexec", "true"], lambda l: None) == 0
    assert len(n) == 2                                         # ... and never for longer than 90 seconds
    rootauth.forget()
    appinstall.stream_run(["pkexec", "true"], lambda l: None)
    assert len(n) == 3


def test_the_password_never_reaches_the_environment_or_the_logs(fake_sudo, monkeypatch):
    logged = []
    monkeypatch.setattr(kiosk, "log_event", lambda m, *a, **k: logged.append(m))
    rootauth.set_provider(lambda p, e: PASSWORD)
    ok, text = kiosk.install_wm(which=lambda n: None)          # runs for real through stream_run with the fake sudo (apt-get is absent)
    assert PASSWORD not in text and all(PASSWORD not in m for m in logged)
    assert PASSWORD not in "".join(os.environ.values())


def test_already_root_just_runs_the_command(monkeypatch):
    monkeypatch.setattr(rootauth.os, "geteuid", lambda: 0)
    assert rootauth.prepare(["pkexec", "a", "b"]) == (["a", "b"], None, None)


def test_checks_accept_sudo_alone_only_with_a_dialog():
    only = lambda *n: (lambda x: "/bin/" + x if x in n else None)       # noqa: E731
    assert not rootauth.can_elevate(only("sudo")) or os.geteuid() == 0
    rootauth.set_provider(lambda p, e: None)
    assert rootauth.can_elevate(only("sudo")) and rootauth.can_elevate(only("pkexec")) and not rootauth.can_elevate(only())


# ------------------------------------------------------------------ the dialog in CodeAque
@pytest.fixture
def ui(app, tmp_path, monkeypatch):
    monkeypatch.delenv("ATARI_NO_ROOTAUTH", raising=False)
    conf(tmp_path)
    u = Ui(app, tmp_path, monkeypatch, config_exists=False)
    yield u
    u.close()


def test_a_worker_asks_through_the_dialog_and_the_answer_comes_back(app, ui):
    from PySide6.QtTest import QTest
    result = []
    t = threading.Thread(target=lambda: result.append(ui.backend.ask_text_blocking("ADMINISTRATOR PASSWORD", "Type it.", True, "", "")))
    t.start()
    for _ in range(100):
        pump(app, 50)
        if ui.backend.inputActive:
            break
    assert ui.backend.inputActive and ui.backend.inputSecret and ui.backend.inputTitle == "ADMINISTRATOR PASSWORD"
    for ch in "Secret pw 1":                                   # a real keyboard: every key carries its character
        QTest.keyClick(ui.win, ch)
    pump(app, 100)
    field = ui.win.findChild(QObject, "inputField")
    assert field.property("text") == "\u2022" * 11 + "\u258c"      # shown as dots, never as text
    ui.key(Qt.Key_Return, 20)
    t.join(5)
    pump(app, 100)
    assert result == ["Secret pw 1"] and not ui.backend.inputActive


def pad(ui, key):
    """A controller button arrives as a key event with no text (a real keyboard's Enter carries text)."""
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtGui import QKeyEvent
    QCoreApplication.sendEvent(ui.win, QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier, ""))
    QCoreApplication.sendEvent(ui.win, QKeyEvent(QEvent.KeyRelease, key, Qt.NoModifier, ""))
    pump(ui.app, 20)


def test_the_controller_can_type_with_the_on_screen_keyboard(app, ui):
    got = []
    ui.backend.ask_text("T", "p", False, "ab", "", got.append)
    pump(app, 100)
    pad(ui, Qt.Key_Return)                                  # A on the highlighted key ("1")
    pad(ui, Qt.Key_Right)
    pad(ui, Qt.Key_Return)                                  # "2"
    pad(ui, Qt.Key_Q)                                       # L1 = delete
    for _ in range(4):
        pad(ui, Qt.Key_Down)                                # to the action row
    for _ in range(5):
        pad(ui, Qt.Key_Right)                               # ... OK
    pad(ui, Qt.Key_Return)
    assert got == ["ab1"]


def test_escape_cancels_the_dialog_and_the_worker_gets_none(app, ui):
    result = []
    t = threading.Thread(target=lambda: result.append(ui.backend.ask_text_blocking("T", "p", True)))
    t.start()
    for _ in range(100):
        pump(app, 50)
        if ui.backend.inputActive:
            break
    ui.key(Qt.Key_Escape)
    t.join(5)
    assert result == [None] and not ui.backend.inputActive


def test_requests_queue_one_after_another(app, ui):
    got = []
    ui.backend.ask_text("ONE", "a", False, "x", "", got.append)
    ui.backend.ask_text("TWO", "b", False, "y", "", got.append)
    pump(app, 100)
    assert ui.backend.inputTitle == "ONE" and ui.backend.inputInitial == "x"
    ui.backend.submitInput("first")
    pump(app, 100)
    assert ui.backend.inputTitle == "TWO"
    ui.backend.cancelInput()
    assert got == ["first", None] and not ui.backend.inputActive


def test_backend_registers_itself_as_the_password_provider(ui):
    assert rootauth.provider() is not None


def test_power_fallback_asks_in_app_and_never_passes_the_password_on_the_command_line(fake_sudo):
    from atarilauncher import power
    rootauth.set_provider(lambda prompt, error: PASSWORD)
    calls = []

    def runner(cmd, **kw):
        calls.append((cmd, kw))
        if cmd[0] != "sudo":                                     # the direct systemctl/loginctl tries fail; pkexec -> sudo then runs
            return subprocess.CompletedProcess(cmd, 1, "", "denied")
        return subprocess.run(cmd, **kw)
    ok, text = power.run("suspend", runner, which=lambda n: f"{fake_sudo}/{n}" if n == "sudo" else f"/usr/bin/{n}", timeout=10)
    sudo_calls = [c for c in calls if c[0][0].endswith("sudo")]
    assert sudo_calls and all(PASSWORD not in " ".join(c[0]) for c in calls)
    assert any(PASSWORD in str(c[1].get("input", "")) for c in sudo_calls)


def test_power_cancelled_password_says_so(fake_sudo):
    from atarilauncher import power
    rootauth.set_provider(lambda prompt, error: None)

    def runner(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, "", "denied")
    ok, text = power.run("reboot", runner, which=lambda n: f"/usr/bin/{n}", timeout=10)
    assert not ok and ("password window was closed" in text or "denied" in text)
