"""Start mode: "Use Linux desktop" / "Use CodeAque only (console mode)", the read-back, the backup, the Power menu "Quit to the Linux desktop",
and the CodeAque launcher on the Mint menu and desktop. Nothing touches the real /etc: a Layout points the files into a temp folder and
pkexec is a stand-in that runs the generated script."""
import os
import subprocess
from pathlib import Path

import pytest

from atarilauncher import branding, kiosk
from tests.test_kiosk import box, checks, fake_pkexec  # noqa: F401  (fixtures and helpers)

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from tests.test_features_ui import conf, wait_for  # noqa: E402
from tests.test_ui_keys import Ui, app  # noqa: E402,F401

ROOT = Path(__file__).resolve().parent.parent


def turn_on(box_):
    layout, run_sh, _ = box_
    ok, _ = kiosk.enable(layout, fake_pkexec(layout), user="hazel", checks=checks(box_), run_sh=run_sh)
    assert ok
    return layout


# ------------------------------------------------------------------ kiosk.py
def test_read_mode_says_desktop_console_or_unclear(box):
    layout, run_sh, _ = box
    m = kiosk.read_mode(layout, env={})
    assert m["next"] == "desktop" and "Mint login" in m["lines"][0] and not m["backup"]
    turn_on(box)
    m = kiosk.read_mode(layout, env={"ATARI_KIOSK": "1"})
    assert m["next"] == "console" and m["running"] == "console" and "CodeAque only" in m["lines"][0]
    layout.p(layout.xsession).unlink()                                    # half-written: say so, never guess
    assert kiosk.read_mode(layout, env={})["next"] == "broken"
    layout.p(layout.lightdm_conf).write_text("[Seat:*]\nautologin-user=hazel\n")      # all three there, but no autologin-session line
    layout.p(layout.xsession).write_text("x")
    assert kiosk.read_mode(layout, env={})["next"] == "broken"


def test_use_linux_desktop_backs_up_removes_and_reads_back(box):
    layout, run_sh, _ = box
    turn_on(box)
    before = {f.name: f.read_text() for f in layout.files}
    run = fake_pkexec(layout)
    ok, text = kiosk.disable(layout, run)
    assert ok and len(run.calls) == 1 and "Linux desktop mode is ON" in text and "restart" in text.lower()
    assert not any(f.exists() for f in layout.files) and kiosk.read_mode(layout, env={})["next"] == "desktop"
    assert kiosk.has_backup(layout)
    assert {f.name: f.read_text() for f in kiosk.backup_files(layout)} == before          # the backup is an exact copy
    assert kiosk.read_mode(layout, env={})["backup"]
    assert (layout.root / "usr/share/xsessions/cinnamon.desktop").is_file()


def test_the_backup_restores_console_mode_with_the_printed_command(box):
    layout, run_sh, tmp = box
    turn_on(box)
    kiosk.disable(layout, fake_pkexec(layout))
    cmd = kiosk.restore_backup_command(layout)
    r = subprocess.run(["sh", "-c", cmd.replace("sudo ", "")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert kiosk.enabled(layout) and kiosk.read_mode(layout, env={})["next"] == "console"
    assert "autologin-session=atari" in layout.p(layout.lightdm_conf).read_text()


def test_a_failed_backup_copy_removes_nothing(box, monkeypatch):
    layout, run_sh, tmp = box
    turn_on(box)
    # make the backup place impossible: a file where the folder must be
    blocker = layout.p(layout.backup_dir)
    blocker.parent.mkdir(parents=True, exist_ok=True)
    blocker.write_text("not a folder")
    ok, text = kiosk.disable(layout, fake_pkexec(layout))
    assert not ok and kiosk.enabled(layout)                                # all three files are still there


def test_another_lightdm_file_that_still_logs_in_to_atari_is_reported(box):
    layout, run_sh, tmp = box
    turn_on(box)
    other = layout.p("etc/lightdm/lightdm.conf.d/50-mine.conf")
    other.write_text("[Seat:*]\nautologin-session=atari\n")
    assert kiosk.autologin_leftovers(layout) == [str(other)]
    ok, text = kiosk.disable(layout, fake_pkexec(layout))
    assert ok and "50-mine.conf" in text and "still start in console mode" in text
    assert kiosk.read_mode(layout, env={})["next"] == "broken"


def test_log_out_uses_cinnamon_then_loginctl_and_explains_failure():
    calls = []
    ok, _ = kiosk.log_out(lambda c, **k: calls.append(c), lambda n: "/usr/bin/" + n if n == "cinnamon-session-quit" else None, {})
    assert ok and calls == [["cinnamon-session-quit", "--logout", "--no-prompt"]]
    calls.clear()
    ok, _ = kiosk.log_out(lambda c, **k: calls.append(c), lambda n: "/usr/bin/" + n if n == "loginctl" else None, {"XDG_SESSION_ID": "c2"})
    assert ok and calls == [["loginctl", "terminate-session", "c2"]]
    ok, text = kiosk.log_out(lambda c, **k: None, lambda n: None, {})
    assert not ok and "restart" in text.lower()


# ------------------------------------------------------------------ launchers
def fake_install(tmp_path):
    root = tmp_path / "inst"
    (root / "packaging").mkdir(parents=True)
    (root / "run.sh").write_text("#!/bin/sh\n")
    (root / "packaging/atari.desktop.in").write_text((ROOT / "packaging/atari.desktop.in").read_text())
    return root


def no_run(cmd, **kw):
    class R:
        returncode, stdout = 1, ""
    no_run.calls.append(cmd)
    return R()


no_run.calls = []


def test_launchers_are_written_executable_and_never_replace_foreign_files(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    root = fake_install(tmp_path)
    env = {"XDG_DATA_HOME": str(home / ".local/share")}
    done = branding.ensure_launchers(home, root, env=env, run=no_run)
    assert done == ["the Mint menu", "the desktop"]
    menu, desk = home / ".local/share/applications/atari.desktop", home / "Desktop/CodeAque.desktop"
    for f in (menu, desk):
        text = f.read_text()
        assert "Name=CodeAque" in text and f"Exec={root}/run.sh" in text and "Icon=atari-launcher" in text and os.access(f, os.X_OK)
    assert any(c[:2] == ["gio", "set"] and c[3] == "metadata::trusted" for c in no_run.calls)       # marked trusted for Nemo
    assert branding.launchers_present(home, root, env=env, run=no_run) == {"menu": True, "desktop": True}
    assert branding.ensure_launchers(home, root, env=env, run=no_run) == []                      # second run: nothing to do
    desk.write_text("[Desktop Entry]\nName=Mine\nExec=/opt/other\n")
    assert branding.ensure_launchers(home, root, env=env, run=no_run) == []
    assert "Name=Mine" in desk.read_text()                                                        # someone else's file is left alone
    assert branding.launchers_present(home, root, env=env, run=no_run)["desktop"] is False


def test_launchers_without_an_install_do_nothing(tmp_path):
    assert branding.ensure_launchers(tmp_path / "h", tmp_path / "missing", run=no_run) == []


# ------------------------------------------------------------------ the screens
def make_ui(app, tmp_path, monkeypatch, box_):
    layout, run_sh, _ = box_
    conf(tmp_path)
    ui = Ui(app, tmp_path, monkeypatch, config_exists=True, home=tmp_path / "home")
    ui.backend._kiosk_layout = layout
    monkeypatch.setattr(kiosk, "preflight", lambda lay=layout, **kw: checks(box_))
    orig_enable, orig_disable = kiosk.enable, kiosk.disable
    monkeypatch.setattr(kiosk, "enable", lambda lay: orig_enable(lay, fake_pkexec(lay), user="hazel", checks=checks(box_), run_sh=run_sh))
    monkeypatch.setattr(kiosk, "disable", lambda lay: orig_disable(lay, fake_pkexec(lay)))
    return ui


def test_settings_row_start_mode_screen_and_both_directions(app, tmp_path, monkeypatch, box):
    layout, run_sh, _ = box
    (tmp_path / "home").mkdir(exist_ok=True)
    monkeypatch.setenv("ATARI_NO_STEAM_SPAWN", "1")
    monkeypatch.setattr(branding, "ensure_launchers", lambda *a, **k: ["the Mint menu", "the desktop"])
    ui = make_ui(app, tmp_path, monkeypatch, box)
    try:
        b = ui.backend
        row = [r for r in b.setupRows() if r.get("kind") == "startmodepage"][0]
        assert row["value"] == "LINUX DESKTOP" and row["title"].startswith("Start mode")
        assert b.pageTitle("startmode") == "START MODE"
        rows = b.pageRows("startmode")
        sel = [r["id"] for r in rows if r["kind"] != "info"]
        assert sel[:2] == ["smdesktop", "smconsole"] and sel[-1] == "back"
        assert [r for r in rows if r.get("id") == "smdesktop"][0]["value"] == "SELECTED"
        text = " ".join(r["title"] for r in rows)
        assert "Read back from the computer" in text and "sudo rm /etc/lightdm/lightdm.conf.d/90-atari-kiosk.conf" in text
        assert b.pageActivate("startmode", "smdesktop") == ""                          # already that way: nothing runs
        assert not b._kiosk_busy and "already" in b.toast
        # -> console mode
        assert b.pageActivate("startmode", "smconsole") == "refresh"
        assert wait_for(app, lambda: kiosk.enabled(layout) and not b._kiosk_busy, 10), b.toast
        rows = b.pageRows("startmode")
        sel = [r["id"] for r in rows if r["kind"] != "info"]
        assert sel[:3] == ["smlogout", "smreboot", "back"]                              # the log-out / restart prompt comes first
        assert "next start is CodeAque only" in " ".join(r["title"] for r in rows)
        assert [r for r in rows if r.get("id") == "smconsole"][0]["value"] == "SELECTED"
        assert [r for r in b.setupRows() if r.get("kind") == "startmodepage"][0]["value"] == "CODEAQUE ONLY"
        # -> Linux desktop
        assert b.pageActivate("startmode", "smdesktop") == "refresh"
        assert wait_for(app, lambda: not kiosk.enabled(layout) and not b._kiosk_busy, 10), b.toast
        assert kiosk.has_backup(layout)
        rows = b.pageRows("startmode")
        text = " ".join(r["title"] for r in rows)
        assert "next start is the Linux desktop" in text and "CodeAque was added to the Mint menu and the desktop" in text
        assert [r["id"] for r in rows if r["kind"] != "info"][:3] == ["smlogout", "smreboot", "back"]
        assert "smlaunchers" in [r.get("id") for r in rows]
        # restart asks again, No first
        assert b.pageActivate("startmode", "smreboot") == "page:power"
        assert [r["id"] for r in b.pageRows("power") if r["kind"] != "info"] == ["power_no", "power_yes"]
    finally:
        ui.close()


def test_a_failed_change_says_so_and_offers_no_restart(app, tmp_path, monkeypatch, box):
    layout, run_sh, _ = box
    (tmp_path / "home").mkdir(exist_ok=True)
    ui = make_ui(app, tmp_path, monkeypatch, box)
    try:
        b = ui.backend
        monkeypatch.setattr(kiosk, "enable", lambda lay: (False, "The password window was closed, so nothing was changed."))
        assert b.pageActivate("startmode", "smconsole") == "refresh"
        assert wait_for(app, lambda: not b._kiosk_busy, 10)
        rows = b.pageRows("startmode")
        assert "nothing was changed" in " ".join(r["title"] for r in rows)
        assert "smlogout" not in [r.get("id") for r in rows] and not kiosk.enabled(layout)
    finally:
        ui.close()


def test_launchers_button_adds_what_is_missing(app, tmp_path, monkeypatch, box):
    (tmp_path / "home").mkdir(exist_ok=True)
    ui = make_ui(app, tmp_path, monkeypatch, box)
    try:
        b = ui.backend
        calls = []
        monkeypatch.setattr(branding, "ensure_launchers", lambda *a, **k: calls.append(k) or ["the desktop"])
        monkeypatch.setattr(branding, "launchers_present", lambda *a, **k: {"menu": True, "desktop": True})
        assert "smlaunchers" in [r.get("id") for r in b.pageRows("startmode")]
        assert b.pageActivate("startmode", "smlaunchers") == "refresh" and calls
        assert "desktop icon yes" in " ".join(r["title"] for r in b.pageRows("startmode"))
    finally:
        ui.close()


def test_power_menu_quit_to_desktop_only_in_console_mode_asks_first_and_leaves_the_flag(app, tmp_path, monkeypatch, box):
    layout, run_sh, _ = box
    (tmp_path / "home").mkdir(exist_ok=True)
    ui = make_ui(app, tmp_path, monkeypatch, box)
    try:
        b = ui.backend
        ids = [r.get("id") for r in b.pageRows("power")]
        assert "power_desktop" not in ids and "power_quitcode" in ids                  # started from the desktop: no such entry
        monkeypatch.setenv("ATARI_KIOSK", "1")
        ids = [r.get("id") for r in b.pageRows("power")]
        assert "power_desktop" in ids and "power_quitcode" not in ids
        title = [r for r in b.pageRows("power") if r.get("id") == "power_desktop"][0]["title"]
        assert title == "Quit to the Linux desktop"
        assert b.pageActivate("power", "power_desktop") == "page:power"
        rows = b.pageRows("power")
        assert [r["id"] for r in rows if r["kind"] != "info"] == ["power_no", "power_yes"]       # No first
        assert "this login only" in rows[0]["title"] and "straight into CodeAque again" in rows[0]["title"]
        assert b.pageActivate("power", "power_no") == "page:power" and b._power_pending == ""
        calls = []
        monkeypatch.setattr(kiosk, "open_desktop_once", lambda *a, **k: calls.append(1) or (True, "Logging out - the Mint desktop opens next."))
        b.pageActivate("power", "power_desktop")
        assert not calls                                                              # asking is not doing
        assert b.pageActivate("power", "power_yes") == "close" and calls == [1] and b._power_pending == ""
        assert "Mint desktop opens next" in b.toast
    finally:
        ui.close()


def test_the_in_app_updater_still_keeps_the_new_modules():
    from atarilauncher import updater
    assert "atarilauncher" in updater.KEEP                        # the whole package (kiosk.py, branding.py ...) is replaced as one folder
    assert "install.sh" in updater.KEEP
