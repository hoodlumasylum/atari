"""Code-only mode: the files it writes, the safety net, the way back, and the confirm / result screens.
Nothing here touches the real /etc: a Layout points the three files into a temporary folder, and "pkexec" is a stand-in
that runs the generated script with the paths moved under that folder."""
import os
import subprocess
import sys

import pytest

from atarilauncher import kiosk

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from tests.test_features_ui import conf, wait_for  # noqa: E402
from tests.test_ui_keys import Ui, app  # noqa: E402,F401


@pytest.fixture
def box(tmp_path):
    """A fake machine root with LightDM, a Cinnamon session entry and Code's run.sh."""
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
    assert ok and "Settings > Back to Mint desktop" in text and kiosk.enabled(layout)
    assert len(run.calls) == 1                                           # ONE password window
    sess, xs, lm = (layout.p(r) for r in (layout.session_script, layout.xsession, layout.lightdm_conf))
    assert os.access(sess, os.X_OK) and not os.access(xs, os.X_OK)
    assert "autologin-user=hazel" in lm.read_text() and "autologin-session=atari" in lm.read_text()
    assert "autologin-user-timeout=0" in lm.read_text()
    x = xs.read_text()
    assert "Exec=/usr/local/bin/atari-session" in x and "Type=XSession" in x and "Name=Code" in x
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
    """Run the generated session script for real with a stand-in Code (run_body) and a stand-in Mint desktop."""
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
    assert starts(tmp_path) == ["start"] * kiosk.MAX_QUICK_CRASHES + ["desktop"]            # Code cannot start at all: desktop, never locked out


def test_code_that_ends_for_any_reason_is_started_again_not_left_to_the_desktop(box, tmp_path):
    """Code dies (killed by an app, crash, 'Restart Code') after running a while: the session starts it again - no logout, no desktop."""
    body = ("n=$(cat @T@/n 2>/dev/null || echo 0); n=$((n+1)); echo $n > @T@/n; echo start >> @T@/starts\n"
            "sleep 4\n"                                                         # a normal, longer run
            "case $n in 1) kill -9 $$;; 2) exit 0;; 3) exit 3;; *) exit 64;; esac\n")   # 1: killed  2: restart  3: crash  4: log out on purpose
    run_session(tmp_path, body)
    assert starts(tmp_path) == ["start"] * 4                                         # four starts, then the deliberate logout; no desktop
    assert "desktop" not in starts(tmp_path)


def test_a_clean_exit_after_a_quick_run_does_not_count_as_a_crash_loop(box, tmp_path):
    """Pressing 'Restart Code' a few times in a row (exit 0) never triggers the desktop fallback; only crashes do."""
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
    run_session(tmp_path, "echo atari >> @T@/starts\nexit 64\n", home=home)             # login after that: Code again
    assert starts(tmp_path) == ["desktop", "atari"]
    assert not kiosk.desktop_once_flag(home).exists()


def test_the_flag_left_while_code_runs_sends_the_next_restart_to_the_desktop(box, tmp_path):
    """'Open the Mint desktop once' leaves the flag then logs out; if only Code ends, the session honours the flag instead of looping."""
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
        assert row["value"] == "OFF" and "Code-only mode" in row["title"]
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
        assert "Code-only mode is ON" in b.toast
        rows = b.pageRows("kiosk")
        assert [r.get("id") for r in rows if r["kind"] != "info"] == ["kioskoff", "kioskonce", "back"]
        assert rows[0]["kind"] == "info" and rows[0]["title"].startswith("Result:")
        row = [r for r in b.setupRows() if r.get("kind") == "kioskpage"][0]
        assert row["value"] == "ON" and row["title"].startswith("Back to Mint desktop")
        assert b.pageActivate("kiosk", "kioskoff") == "refresh"            # the way back from Settings
        assert wait_for(app, lambda: not kiosk.enabled(layout), 10)
        assert wait_for(app, lambda: not b._kiosk_busy, 5)
        assert "Code-only mode is OFF" in b.toast
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


# ------------------------------------------------------------------ an install made by an older Code
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
    layout.p(layout.session_script).write_text(OLD_SCRIPT)          # what Code 0.3.x / 0.4.0 wrote (root's file: an update cannot touch it)
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
        assert not any(r.get("id") == "kioskupdate" for r in b.pageRows("kiosk"))
    finally:
        ui.close()
