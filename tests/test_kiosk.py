"""CodeAque-only mode: the files it writes, the safety net, the way back, and the confirm / result screens.
Nothing here touches the real /etc: a Layout points the three files into a temporary folder, and "pkexec" is a stand-in
that runs the generated script with the paths moved under that folder."""
import os
import subprocess
import sys

from pathlib import Path

import pytest

from atarilauncher import kiosk

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from tests.test_features_ui import conf, wait_for  # noqa: E402
from tests.test_ui_keys import Ui, app  # noqa: E402,F401


@pytest.fixture
def box(tmp_path):
    """A fake machine root with LightDM, a Cinnamon session entry and CodeAque's run.sh."""
    root = tmp_path / "root"
    (root / "usr/share/xsessions").mkdir(parents=True)
    (root / "usr/share/xsessions/cinnamon.desktop").write_text("[Desktop Entry]\nName=Cinnamon\nExec=cinnamon-session-cinnamon\n")
    (root / "etc/X11").mkdir(parents=True)
    (root / "etc/X11/default-display-manager").write_text("/usr/sbin/lightdm\n")
    run_sh = tmp_path / "atari-launcher" / "run.sh"
    run_sh.parent.mkdir()
    run_sh.write_text("#!/bin/sh\nexit 0\n")
    run_sh.chmod(0o755)
    return kiosk.Layout(root=root), run_sh, tmp_path


def fake_pkexec(layout):
    """Runs the pkexec'd script for real (the Layout already points every path below layout.root); apt-get is a no-op."""
    calls = []

    def run(cmd, out, cancel):
        calls.append(cmd)
        assert cmd[:3] == ["pkexec", "sh", "-c"]
        script = cmd[3]
        script = script.replace("apt-get install", "true")
        return subprocess.run(["sh", "-c", script], capture_output=True, text=True).returncode
    run.calls = calls
    return run


ORIG_PREFLIGHT = kiosk.preflight


def checks(box, **kw):
    layout, run_sh, tmp = box
    args = dict(layout=layout, which=lambda n: "/usr/bin/" + n, dm_file=str(layout.root / "etc/X11/default-display-manager"),
                run_sh=run_sh, user="hazel", session_type="x11", lightdm_conf=str(tmp / "no-lightdm.conf"))
    args.update(kw)
    return ORIG_PREFLIGHT(**args)


# ------------------------------------------------------------------ preflight
def test_preflight_passes_on_a_normal_mint(box):
    cs = checks(box)
    assert kiosk.blocked(cs) == "" and all(c.ok for c in cs)


@pytest.mark.parametrize("kw,word", [
    ({"user": "root"}, "not as root"),
    ({"which": lambda n: None}, "pkexec"),
    ({"run_sh": None}, "start script"),
])
def test_preflight_blocks_with_plain_english(box, kw, word):
    if "run_sh" in kw:
        kw = {"run_sh": box[2] / "missing" / "run.sh"}
    assert word in kiosk.blocked(checks(box, **kw))


def test_other_login_managers_are_refused(box):
    layout = box[0]
    (layout.root / "etc/X11/default-display-manager").write_text("/usr/sbin/gdm3\n")
    assert "does not use LightDM" in kiosk.blocked(checks(box))


def test_an_existing_autologin_in_lightdm_conf_is_warned_about(box, tmp_path):
    conf = tmp_path / "lightdm.conf"
    conf.write_text("[Seat:*]\nautologin-user=someone\n")
    cs = checks(box, lightdm_conf=str(conf))
    bad = [c for c in cs if not c.ok]
    assert [c.id for c in bad] == ["conflict"] and not bad[0].fatal and "win over" in bad[0].text
    assert kiosk.blocked(cs) == ""


# ------------------------------------------------------------------ turning it on and off
def test_enable_writes_exactly_three_files_and_disable_removes_them(box):
    layout, run_sh, tmp = box
    run = fake_pkexec(layout)
    ok, text = kiosk.enable(layout, run, user="hazel", checks=checks(box), run_sh=run_sh)
    assert ok and "Settings > Start mode > Use Linux desktop" in text and kiosk.enabled(layout)
    assert len(run.calls) == 1                                           # ONE password window
    sess, xs, lm = (layout.p(r) for r in (layout.session_script, layout.xsession, layout.lightdm_conf))
    assert os.access(sess, os.X_OK) and not os.access(xs, os.X_OK)
    assert "autologin-user=hazel" in lm.read_text() and "autologin-session=atari" in lm.read_text()
    assert "autologin-user-timeout=0" in lm.read_text()
    x = xs.read_text()
    assert "Exec=/usr/local/bin/atari-session" in x and "Type=XSession" in x and "Name=CodeAque" in x
    s = sess.read_text()
    assert str(run_sh) in s and "exec cinnamon-session-cinnamon" in s                # the safety net uses Mint's own session
    assert "desktop-once" in s and "-lt 3" in s
    r = subprocess.run(["sh", "-n", str(sess)], capture_output=True, text=True)      # the script is valid shell
    assert r.returncode == 0, r.stderr
    files = sorted(str(p.relative_to(layout.root)) for p in layout.root.rglob("*") if p.is_file())
    assert [f for f in files if "atari" in f] == ["etc/lightdm/lightdm.conf.d/90-atari-kiosk.conf",
                                                  "usr/local/bin/atari-session", "usr/share/xsessions/atari.desktop"]
    ok, text = kiosk.disable(layout, fake_pkexec(layout))
    assert ok and not kiosk.enabled(layout) and not any(f.exists() for f in layout.files)
    assert (layout.root / "usr/share/xsessions/cinnamon.desktop").is_file()          # Mint's own entries are never touched


def test_enable_refuses_when_a_check_fails_and_changes_nothing(box):
    layout, run_sh, _ = box
    run = fake_pkexec(layout)
    ok, text = kiosk.enable(layout, run, user="root", checks=checks(box, user="root"), run_sh=run_sh)
    assert not ok and "not as root" in text and not run.calls and not kiosk.enabled(layout)


def test_closed_password_window_and_failures_are_explained(box):
    layout, run_sh, _ = box
    ok, text = kiosk.enable(layout, lambda c, o, x: 126, user="hazel", checks=checks(box), run_sh=run_sh)
    assert not ok and "nothing was changed" in text
    ok, text = kiosk.enable(layout, lambda c, o, x: 1, user="hazel", checks=checks(box), run_sh=run_sh)
    assert not ok and "code 1" in text
    ok, text = kiosk.enable(layout, lambda c, o, x: 0, user="hazel", checks=checks(box), run_sh=run_sh)   # claims success, wrote nothing
    assert not ok and "not written" in text


SESSION_ENV = {"ATARI_RESTART_DELAY": "0"}


def run_session(tmp_path, run_body, desktop_body="echo desktop >> %s/starts\n", home=None, timeout=60):
    """Run the generated session script for real with a stand-in CodeAque (run_body) and a stand-in Mint desktop."""
    run = tmp_path / "run.sh"
    run.write_text("#!/bin/sh\n" + run_body.replace("@T@", str(tmp_path)))
    run.chmod(0o755)
    desk = tmp_path / "fakedesktop"
    desk.write_text("#!/bin/sh\n" + (desktop_body % tmp_path))
    desk.chmod(0o755)
    script = tmp_path / "session.sh"
    script.write_text(kiosk.render_session_script(run, str(desk)))
    home = home or (tmp_path / "home")
    home.mkdir(exist_ok=True)
    env = dict(os.environ, HOME=str(home), PATH="/usr/bin:/bin", **SESSION_ENV)
    return subprocess.run(["sh", str(script)], env=env, timeout=timeout)


def starts(tmp_path):
    f = tmp_path / "starts"
    return f.read_text().split() if f.exists() else []


def test_the_session_script_still_falls_back_to_the_desktop_but_only_for_a_real_crash_loop(box, tmp_path):
    run_session(tmp_path, "echo start >> @T@/starts\nexit 1\n")
    assert starts(tmp_path) == ["start"] * kiosk.MAX_QUICK_CRASHES + ["desktop"]            # CodeAque cannot start at all: desktop, never locked out


def test_code_that_ends_for_any_reason_is_started_again_not_left_to_the_desktop(box, tmp_path):
    """CodeAque dies (killed by an app, crash, 'Restart CodeAque') after running a while: the session starts it again - no logout, no desktop."""
    body = ("n=$(cat @T@/n 2>/dev/null || echo 0); n=$((n+1)); echo $n > @T@/n; echo start >> @T@/starts\n"
            "sleep 4\n"                                                         # a normal, longer run
            "case $n in 1) kill -9 $$;; 2) exit 0;; 3) exit 3;; *) exit 64;; esac\n")   # 1: killed  2: restart  3: crash  4: log out on purpose
    run_session(tmp_path, body)
    assert starts(tmp_path) == ["start"] * 4                                         # four starts, then the deliberate logout; no desktop
    assert "desktop" not in starts(tmp_path)


def test_a_clean_exit_after_a_quick_run_does_not_count_as_a_crash_loop(box, tmp_path):
    """Pressing 'Restart CodeAque' a few times in a row (exit 0) never triggers the desktop fallback; only crashes do."""
    body = ("n=$(cat @T@/n 2>/dev/null || echo 0); n=$((n+1)); echo $n > @T@/n; echo start >> @T@/starts\n"
            "sleep 3.2\n[ $n -lt 7 ] && exit 0\nexit 64\n")
    run_session(tmp_path, body, timeout=90)
    assert starts(tmp_path) == ["start"] * 7


def test_a_crash_that_comes_after_a_long_run_resets_the_counter(box, tmp_path):
    body = ("n=$(cat @T@/n 2>/dev/null || echo 0); n=$((n+1)); echo $n > @T@/n; echo start >> @T@/starts\n"
            "case $n in 4|5) sleep 0;; *) ;; esac\n"
            "[ $n -eq 5 ] && sleep 11\n[ $n -ge 9 ] && exit 64\nexit 1\n")
    run_session(tmp_path, body, timeout=120)
    assert starts(tmp_path) == ["start"] * 9 and "desktop" not in starts(tmp_path)    # 4 quick crashes, a longer run, 4 more: still no fallback


def test_the_session_script_tells_code_it_is_the_session(box, tmp_path):
    run_session(tmp_path, 'echo "$ATARI_KIOSK" >> @T@/starts\nexit 64\n')
    assert starts(tmp_path) == ["1"]
    assert kiosk.in_session({"ATARI_KIOSK": "1"}) and not kiosk.in_session({}) and not kiosk.in_session({"ATARI_KIOSK": "0"})


def test_open_desktop_once_flag_makes_the_session_start_the_desktop_and_is_single_use(box, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    calls = []
    ok, text = kiosk.open_desktop_once(home, run=lambda cmd, **kw: calls.append(cmd), which=lambda n: "/usr/bin/" + n)
    assert ok and kiosk.desktop_once_flag(home).is_file() and calls == [["cinnamon-session-quit", "--logout", "--no-prompt"]]
    run_session(tmp_path, "echo atari >> @T@/starts\nexit 64\n", home=home)             # next login: desktop, once
    run_session(tmp_path, "echo atari >> @T@/starts\nexit 64\n", home=home)             # login after that: CodeAque again
    assert starts(tmp_path) == ["desktop", "atari"]
    assert not kiosk.desktop_once_flag(home).exists()


def test_the_flag_left_while_code_runs_sends_the_next_restart_to_the_desktop(box, tmp_path):
    """'Open the Mint desktop once' leaves the flag then logs out; if only CodeAque ends, the session honours the flag instead of looping."""
    home = tmp_path / "home"
    home.mkdir()
    run_session(tmp_path, "echo atari >> @T@/starts\nmkdir -p $HOME/.config/atari && echo 1 > $HOME/.config/atari/desktop-once\nsleep 3.2\nexit 0\n", home=home)
    assert starts(tmp_path) == ["atari", "desktop"]


def test_recovery_text_names_the_exact_command():
    assert "sudo rm /etc/lightdm/lightdm.conf.d/90-atari-kiosk.conf" in kiosk.RECOVERY and "Ctrl+Alt+F2" in kiosk.RECOVERY
    assert any("systemd-analyze blame" in t for t in kiosk.FAST_BOOT_TIPS)


# ------------------------------------------------------------------ the screens
def test_settings_row_confirm_screen_and_result(app, tmp_path, monkeypatch, box):
    layout, run_sh, _ = box
    conf(tmp_path, '[steam]\nenabled = false\n')
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        b = ui.backend
        b._kiosk_layout = layout
        row = [r for r in b.setupRows() if r.get("kind") == "kioskpage"][0]
        assert row["value"] == "OFF" and "CodeAque-only mode" in row["title"]
        monkeypatch.setattr(kiosk, "preflight", lambda lay=layout, **kw: checks(box))
        rows = b.pageRows("kiosk")
        text = " ".join(r.get("title", "") for r in rows)
        assert "no Linux Mint desktop" in text and "Ctrl+Alt+F2" in text and "systemd-analyze blame" in text
        ids = [r.get("id") for r in rows if r["kind"] != "info"]
        assert ids == ["kioskon", "back"]                                  # a clear Yes / No
        assert [r["title"] for r in rows if r.get("id") == "back"] == ["No, keep my normal desktop"]
        orig_enable, orig_disable = kiosk.enable, kiosk.disable
        monkeypatch.setattr(kiosk, "enable", lambda lay: orig_enable(lay, fake_pkexec(lay), user="hazel", checks=checks(box), run_sh=run_sh))
        monkeypatch.setattr(kiosk, "disable", lambda lay: orig_disable(lay, fake_pkexec(lay)))
        assert b.pageActivate("kiosk", "kioskon") == "refresh"             # runs in the background, never blocks the screen
        assert wait_for(app, lambda: kiosk.enabled(layout), 10), b.toast
        assert wait_for(app, lambda: not b._kiosk_busy, 5)
        assert "CodeAque-only mode is ON" in b.toast
        rows = b.pageRows("kiosk")
        assert [r.get("id") for r in rows if r["kind"] != "info"] == ["kioskupdate", "kioskoff", "kioskonce", "back"]
        assert rows[0]["kind"] == "info" and rows[0]["title"].startswith("Result:")
        row = [r for r in b.setupRows() if r.get("kind") == "kioskpage"][0]
        assert row["value"] == "ON" and row["title"].startswith("CodeAque-only mode: details")
        assert b.pageActivate("kiosk", "kioskoff") == "refresh"            # the way back from Settings
        assert wait_for(app, lambda: not kiosk.enabled(layout), 10)
        assert wait_for(app, lambda: not b._kiosk_busy, 5)
        assert "Linux desktop mode is ON" in b.toast
        assert not any(f.exists() for f in layout.files)
    finally:
        ui.close()


def test_blocked_machines_get_only_a_back_button(app, tmp_path, monkeypatch, box):
    layout, run_sh, _ = box
    conf(tmp_path, '[steam]\nenabled = false\n')
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        b = ui.backend
        b._kiosk_layout = layout
        monkeypatch.setattr(kiosk, "preflight", lambda lay=layout, **kw: checks(box, which=lambda n: None))
        rows = b.pageRows("kiosk")
        assert [r.get("id") for r in rows if r["kind"] != "info"] == ["back"]
        assert any(r["title"].startswith("CANNOT CONTINUE") and "pkexec" in r["title"] for r in rows)
    finally:
        ui.close()


# ------------------------------------------------------------------ an install made by an older CodeAque
OLD_SCRIPT = """#!/bin/sh
RUN=/x/run.sh
n=0
while [ "$n" -lt 3 ]; do
    t=$(date +%s)
    "$RUN" --fullscreen
    if [ $(( $(date +%s) - t )) -ge 30 ]; then exit 0; fi
    n=$((n + 1))
done
exec cinnamon-session-cinnamon
"""


def test_a_session_script_from_before_0_4_1_is_noticed_and_replaced_by_one_press(box):
    layout, run_sh, _ = box
    for f in layout.files:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x")
    layout.p(layout.session_script).write_text(OLD_SCRIPT)          # what CodeAque 0.3.x / 0.4.0 wrote (root's file: an update cannot touch it)
    assert kiosk.enabled(layout) and kiosk.session_outdated(layout)
    ok, text = kiosk.enable(layout, fake_pkexec(layout), user="hazel", checks=checks(box), run_sh=run_sh)
    assert ok and not kiosk.session_outdated(layout)
    assert f"atari-session-version: {kiosk.SESSION_VERSION}" in layout.p(layout.session_script).read_text()
    assert not kiosk.session_outdated(kiosk.Layout(root=layout.root / "nowhere"))      # nothing installed: nothing to update


def test_the_code_only_screen_offers_the_update_only_when_needed(app, tmp_path, monkeypatch, box):
    layout, run_sh, _ = box
    conf(tmp_path, '[steam]\nenabled = false\n')
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        b = ui.backend
        b._kiosk_layout = layout
        for f in layout.files:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("x")
        layout.p(layout.session_script).write_text(OLD_SCRIPT)
        rows = b.pageRows("kiosk")
        assert any(r.get("id") == "kioskupdate" for r in rows) and "drop you to the Mint desktop" in " ".join(r.get("title", "") for r in rows)
        layout.p(layout.session_script).write_text(kiosk.render_session_script(run_sh, "cinnamon-session"))
        rows = b.pageRows("kiosk")
        assert any(r.get("id") == "kioskupdate" for r in rows) and "up to date" in " ".join(r.get("title", "") for r in rows)  # always there
    finally:
        ui.close()


def test_the_update_button_is_in_settings_whenever_code_only_mode_is_installed(app, tmp_path, monkeypatch, box):
    layout, run_sh, _ = box
    conf(tmp_path, '[steam]\nenabled = false\n')
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        b = ui.backend
        b._kiosk_layout = layout
        assert not [r for r in b.setupRows() if r.get("kind") == "kioskupdate"]          # nothing installed: no row
        for f, text in zip(layout.files, ("#!/bin/sh\n# session from Atari 0.3.2, no marker\nexec run.sh\n", "x", "x")):
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text)
        assert kiosk.enabled(layout) and kiosk.session_outdated(layout)                    # a 0.3.x script (no marker) counts as old
        rows = [r for r in b.setupRows() if r.get("kind") == "kioskupdate"]
        assert len(rows) == 1 and rows[0]["title"] == "Update CodeAque-only mode" and rows[0]["value"] == "UPDATE NEEDED"
        layout.p(layout.session_script).write_text(kiosk.render_session_script(run_sh, "cinnamon-session"))
        rows = [r for r in b.setupRows() if r.get("kind") == "kioskupdate"]
        assert len(rows) == 1 and rows[0]["value"] == "Up to date"                         # still there when current
        page = b.pageRows("kiosk")
        assert [r["title"] for r in page if r.get("id") == "kioskupdate"] == ["Update CodeAque-only mode"]
        qml = (Path(kiosk.__file__).parent / "qml" / "Main.qml").read_text()
        assert 'r.kind === "kioskupdate"' in qml and "updateKioskSession" in qml
    finally:
        ui.close()


def test_the_settings_row_runs_the_update(app, tmp_path, monkeypatch, box):
    layout, run_sh, _ = box
    conf(tmp_path, '[steam]\nenabled = false\n')
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        b = ui.backend
        b._kiosk_layout = layout
        for f in layout.files:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("old")
        ran = []
        monkeypatch.setattr(kiosk, "enable", lambda lay: (ran.append(1) or (True, "CodeAque-only mode is ON (updated).")))
        b.updateKioskSession()
        assert wait_for(app, lambda: ran and not b._kiosk_busy, 10)
    finally:
        ui.close()


def test_terminal_one_liner_prints_the_current_script(tmp_path, capsys):
    import subprocess, sys
    root = Path(kiosk.__file__).resolve().parent.parent
    out = subprocess.run([sys.executable, "-m", "atarilauncher.kiosk", "--print-session"], cwd=root, capture_output=True, text=True, timeout=30)
    assert out.returncode == 0 and out.stdout.startswith("#!/bin/sh") and "atari-session-version: %d" % kiosk.SESSION_VERSION in out.stdout
    assert "run.sh" in out.stdout and "ATARI_KIOSK=1" in out.stdout
    assert subprocess.run(["sh", "-n"], input=out.stdout, text=True, capture_output=True).returncode == 0   # valid shell


# ------------------------------------------------------------------ 0.4.2: the session says what it does, and can be put right
def run_session2(tmp_path, code_body, env_extra=None, timeout=30):
    home = tmp_path / "h"
    home.mkdir(exist_ok=True)
    run = tmp_path / "run.sh"
    run.write_text("#!/bin/sh\n" + code_body)
    run.chmod(0o755)
    script = tmp_path / "session.sh"
    script.write_text(kiosk.render_session_script(run, "echo DESKTOP-STARTED"))
    env = dict(os.environ, HOME=str(home), ATARI_RESTART_DELAY="0", **(env_extra or {}))
    p = subprocess.run(["sh", str(script)], capture_output=True, text=True, env=env, timeout=timeout)
    log = (home / ".local/share/atari/session.log")
    return p, (log.read_text() if log.exists() else ""), home


def test_session_log_records_start_exit_and_the_reason_for_the_desktop(tmp_path):
    p, log, _ = run_session2(tmp_path, "exit 3\n")                          # CodeAque dies at once, every time
    assert "DESKTOP-STARTED" in p.stdout
    assert log.count("starting CodeAque") == kiosk.MAX_QUICK_CRASHES and "CodeAque ended: exit code 3" in log
    assert "STARTING THE MINT DESKTOP: CodeAque stopped %d times in a row" % kiosk.MAX_QUICK_CRASHES in log and "last exit code 3" in log


def test_session_log_names_a_leftover_desktop_once_note(tmp_path):
    home = tmp_path / "h"
    (home / ".config/atari").mkdir(parents=True)
    (home / ".config/atari/desktop-once").write_text("1")
    p, log, _ = run_session2(tmp_path, "exit 64\n")
    assert "DESKTOP-STARTED" in p.stdout and "'Open the Mint desktop once' note was found" in log
    assert not (home / ".config/atari/desktop-once").exists()               # used up: the next start is CodeAque again


def test_a_logout_exit_code_and_a_non_executable_run_script_are_handled(tmp_path):
    p, log, _ = run_session2(tmp_path, "exit 64\n")
    assert "DESKTOP-STARTED" not in p.stdout and "log out on purpose" in log
    run = tmp_path / "run.sh"
    run.chmod(0o644)                                                         # lost its x bit: still started (through sh), not the desktop
    script = tmp_path / "session.sh"
    p2 = subprocess.run(["sh", str(script)], capture_output=True, text=True, timeout=30,
                        env=dict(os.environ, HOME=str(tmp_path / "h"), ATARI_RESTART_DELAY="0"))
    assert "DESKTOP-STARTED" not in p2.stdout and p2.returncode == 0


def test_a_missing_run_script_says_so(tmp_path):
    script = tmp_path / "session.sh"
    script.write_text(kiosk.render_session_script(tmp_path / "gone" / "run.sh", "echo DESKTOP-STARTED"))
    home = tmp_path / "h"
    p = subprocess.run(["sh", str(script)], capture_output=True, text=True, timeout=30, env=dict(os.environ, HOME=str(home)))
    assert "DESKTOP-STARTED" in p.stdout and "start script is missing" in (home / ".local/share/atari/session.log").read_text()


def test_diagnose_finds_a_wrong_autologin_session_and_leftover_notes(box, tmp_path):
    layout, run_sh, _ = box
    home = tmp_path / "home"
    ok, _ = kiosk.enable(layout, fake_pkexec(layout), user="hazel", checks=checks(box), run_sh=run_sh)
    assert ok
    facts = kiosk.diagnose(layout, home)
    assert not [t for t in facts if t.startswith(("MISSING", "WRONG", "OLD", "WILL"))], facts
    layout.p(layout.lightdm_conf).write_text("[Seat:*]\nautologin-user=hazel\nautologin-session=cinnamon\n")
    (home / ".config/atari").mkdir(parents=True)
    kiosk.desktop_once_flag(home).write_text("1")
    layout.p(layout.session_script).write_text("#!/bin/sh\nRUN=/nope/run.sh\n")
    facts = " ".join(kiosk.diagnose(layout, home))
    assert "WRONG   auto-login session = cinnamon" in facts and "WILL OPEN THE DESKTOP ONCE" in facts
    assert "MISSING CodeAque's start script: /nope/run.sh" in facts and "OLD" in facts


def test_the_restore_command_is_one_line_that_rewrites_the_three_files_and_clears_the_note():
    c = kiosk.RESTORE_COMMAND
    assert "\n" not in c and "rm -f ~/.config/atari/desktop-once" in c and "kiosk.enable_script(" in c and c.endswith("| sudo sh")
    assert subprocess.run(["sh", "-n", "-c", c]).returncode == 0
    out = subprocess.run(["sh", "-c", c.replace("| sudo sh", "")], capture_output=True, text=True,
                         cwd=Path(kiosk.__file__).resolve().parent.parent, env=dict(os.environ, HOME="/tmp/nohome-xyz", USER="hazel"))
    assert out.returncode != 0 or "atari-session" in out.stdout                 # (the cd target does not exist here; the python part is checked next)
    gen = subprocess.run([sys.executable, "-c", "from atarilauncher import kiosk; print(kiosk.enable_script('hazel'))"], capture_output=True,
                         text=True, cwd=Path(kiosk.__file__).resolve().parent.parent)
    assert "autologin-user=hazel" in gen.stdout and "/usr/local/bin/atari-session" in gen.stdout and gen.stdout.startswith("set -e")


def test_the_code_only_page_shows_problems_and_the_restore_command(app, tmp_path, monkeypatch, box):
    layout, run_sh, _ = box
    conf(tmp_path, '[steam]\nenabled = false\n')
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        b = ui.backend
        b._kiosk_layout = layout
        for f in layout.files:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("x")
        layout.p(layout.lightdm_conf).write_text("[Seat:*]\nautologin-user=hazel\nautologin-session=cinnamon\n")
        text = " ".join(r.get("title", "") for r in b.pageRows("kiosk"))
        assert "Check:" in text and "auto-login session = cinnamon" in text and kiosk.RESTORE_COMMAND in text
    finally:
        ui.close()


# ------------------------------------------------------------------ 0.4.2: CodeAque started from the desktop still takes the screen back
def test_shell_mode_is_the_session_or_an_installed_code_only_mode(box, monkeypatch):
    layout, run_sh, _ = box
    assert not kiosk.shell_mode(layout, env={})
    assert kiosk.shell_mode(layout, env={"ATARI_KIOSK": "1"})                      # started by the session program
    for f in layout.files:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x")
    assert kiosk.shell_mode(layout, env={"XDG_CURRENT_DESKTOP": "X-Cinnamon"})     # installed, but started from the desktop / autostart
    assert kiosk.running_description({"ATARI_KIOSK": "1"})[0] == "code-only"
    kind, text = kiosk.running_description({"XDG_CURRENT_DESKTOP": "X-Cinnamon"})
    assert kind == "desktop" and "INSIDE the X-Cinnamon desktop" in text


def test_log_event_appends_to_the_session_log(tmp_path):
    kiosk.log_event("started - test", home=tmp_path)
    kiosk.log_event("an app closed", home=tmp_path)
    lines = kiosk.log_tail(5, tmp_path)
    assert len(lines) == 2 and lines[0].endswith("code: started - test")
    kiosk.log_event("never", home=Path("/proc/nope"))                              # an unwritable folder never raises


def test_restoring_after_an_app_goes_fullscreen_when_code_only_mode_is_installed_even_from_the_desktop(app, tmp_path, monkeypatch, box):
    layout, run_sh, _ = box
    conf(tmp_path, '[steam]\nenabled = false\n[general]\nfullscreen = false\n')
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        b = ui.backend
        b._kiosk_layout = layout
        monkeypatch.delenv("ATARI_KIOSK", raising=False)
        calls = []

        class Win:
            def showFullScreen(self): calls.append("full")
            def showNormal(self): calls.append("normal")
            def raise_(self): pass
            def requestActivate(self): pass
        b._window, b._minimized_for_game = Win(), True
        b._restore_window()
        assert calls == ["normal"]                                                  # a plain desktop install: unchanged behaviour
        for f in layout.files:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("x")
        calls.clear()
        b._minimized_for_game = True
        b._restore_window()
        assert calls == ["full"]                                                    # CodeAque-only mode installed: whole screen again
        calls.clear()
        b._minimized_for_game = False
        b._restore_window()
        assert calls == ["full"]
    finally:
        b._window = None
        ui.close()


def test_diagnose_notes_a_missing_window_manager_and_a_desktop_autostart(box, tmp_path, monkeypatch):
    layout, run_sh, _ = box
    home = tmp_path / "home"
    (home / ".config/autostart").mkdir(parents=True)
    (home / ".config/autostart/atari.desktop").write_text("[Desktop Entry]\n")
    monkeypatch.setattr(kiosk.shutil, "which", lambda n: None)
    facts = " ".join(kiosk.diagnose(layout, home))
    assert "no window manager (openbox)" in facts and "sudo apt install openbox" in facts and "autostart" in facts
