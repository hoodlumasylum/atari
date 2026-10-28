"""The step-by-step Roblox (Sober) fix screen: every check with pretend flatpak / network / clock, and the page with its Run fix button."""
import subprocess
import time

import pytest

from atarilauncher import sober

pytest.importorskip("PySide6")
from atarilauncher import backend as be  # noqa: E402
from atarilauncher.config import default_config  # noqa: E402
from atarilauncher.store import Store  # noqa: E402


class Flatpak:
    """A pretend `flatpak`: remotes, info --show-origin, remote-add."""

    def __init__(self, remotes="flathub\n", origin="flathub", installed=True, add_rc=0, override=False, override_rc=0):
        self.remotes, self.origin, self.installed, self.add_rc = remotes, origin, installed, add_rc
        self.override, self.override_rc = override, override_rc
        self.calls = []

    def __call__(self, args, **kw):
        self.calls.append(list(args))
        if args[:2] == ["flatpak", "remotes"]:
            return subprocess.CompletedProcess(args, 0, self.remotes, "")
        if args[:3] == ["flatpak", "info", "--show-origin"]:
            return subprocess.CompletedProcess(args, 0 if self.installed else 1, self.origin + "\n" if self.installed else "", "" if self.installed else "not installed")
        if args[:3] == ["flatpak", "override", "--user"] and "--show" in args:
            out = ("[Context]\ndevices=all;\nfilesystems=xdg-run/app/com.discordapp.Discord:create;xdg-run/discord-ipc-0;\n"
                   if self.override else "")
            return subprocess.CompletedProcess(args, 0, out, "")
        if args[:3] == ["flatpak", "override", "--user"]:
            if self.override_rc == 0:
                self.override = True
            return subprocess.CompletedProcess(args, self.override_rc, "", "denied" if self.override_rc else "")
        if args[:2] == ["flatpak", "remote-add"]:
            if self.add_rc == 0:
                self.remotes += "flathub\n"
            return subprocess.CompletedProcess(args, self.add_rc, "", "no network" if self.add_rc else "")
        return subprocess.CompletedProcess(args, 0, "", "")


def fix_ok(**kw):
    kw.setdefault("flat", Flatpak(override=True))
    return fix(**kw)


def fix(flat=None, probe=lambda u: 200, skew=0.0, dns=lambda h: True, portal=lambda: True, update=lambda: (True, ""), home=None):
    t = 1_800_000_000.0
    return sober.run_fix(run=flat or Flatpak(), probe=probe, now=lambda: t, date_fn=lambda: (t + skew) if skew is not None else None,
                         resolve=dns, portal=portal, update=update, home=home)


def by_id(steps):
    return {s.id: s for s in steps}


def test_all_good_says_honestly_it_is_sobers_service_and_names_the_version(tmp_path):
    flat = Flatpak(override=True)
    state = tmp_path / ".var/app/org.vinegarhq.Sober/data/sober/state"
    state.parent.mkdir(parents=True)
    state.write_text('{"version":"2.741.1061"}')
    steps, verdict = fix(flat, home=str(tmp_path))
    assert all(s.ok for s in steps) and [s.id for s in steps][:4] == ["flathub", "installed", "update", "permissions"]
    assert "looks right" in verdict and "2.741.1061" in verdict and "Sober's own download service" in verdict
    assert "nothing Code can repair" in verdict


def test_requested_version_comes_from_sobers_state_file(tmp_path):
    assert sober.requested_version(str(tmp_path)) == ""
    f = tmp_path / ".var/app/org.vinegarhq.Sober/data/sober/state"
    f.parent.mkdir(parents=True)
    f.write_text("version = 2.741.1061\nother = 1")
    assert sober.requested_version(str(tmp_path)) == "2.741.1061"


def test_missing_flathub_is_added_for_the_user_only():
    flat = Flatpak(remotes="")
    steps, _ = fix(flat)
    add = [c for c in flat.calls if c[:2] == ["flatpak", "remote-add"]]
    assert add == [["flatpak", "remote-add", "--user", "--if-not-exists", "flathub", sober.FLATHUB_URL]]
    assert by_id(steps)["flathub"].ok and "added it" in by_id(steps)["flathub"].detail
    steps, verdict = fix(Flatpak(remotes="", add_rc=1))
    assert not by_id(steps)["flathub"].ok and "could not be added" in by_id(steps)["flathub"].detail


def test_not_installed_and_wrong_origin_are_named():
    steps, verdict = fix(Flatpak(installed=False))
    assert not by_id(steps)["installed"].ok and "update" not in by_id(steps) and "Install on the Roblox tile" in verdict
    steps, verdict = fix(Flatpak(origin="fedora"))
    assert not by_id(steps)["installed"].ok and "fedora" in by_id(steps)["installed"].detail and "Flathub" in verdict


def test_flatpak_update_failure_is_reported():
    steps, verdict = fix(update=lambda: (False, "Error: no space left"))
    assert not by_id(steps)["update"].ok and "no space left" in verdict


def test_dns_block_is_diagnosed_with_the_documented_cure():
    steps, verdict = fix(dns=lambda h: h != "play.googleapis.com", probe=lambda u: 0)
    assert not by_id(steps)["dns"].ok and "1.1.1.1" in verdict and "play.googleapis.com" in by_id(steps)["dns"].detail


def test_unreachable_google_play_or_sober_server_is_explained():
    steps, verdict = fix(probe=lambda u: 0 if "googleapis" in u else 200)
    assert not by_id(steps)["play"].ok and "blocking" in verdict
    steps, verdict = fix(probe=lambda u: 500 if "vinegarhq" in u else 200)
    assert not by_id(steps)["manifest"].ok and "Sober's server is having a problem" in verdict


def test_a_wrong_clock_is_found_from_the_servers_date():
    steps, verdict = fix(skew=3 * 3600.0)
    assert not by_id(steps)["clock"].ok and "automatic date" in verdict
    steps, verdict = fix(skew=10.0)
    assert by_id(steps)["clock"].ok
    steps, _ = fix(skew=None)
    assert by_id(steps)["clock"].ok and "Could not compare" in by_id(steps)["clock"].detail


def test_a_missing_portal_is_only_a_note_not_the_cause():
    steps, verdict = fix(portal=lambda: False)
    p = by_id(steps)["portal"]
    assert not p.ok and "Code-only mode" in p.detail and "looks right" in verdict            # the verdict ignores it


def test_missing_flatpak_stops_with_a_clear_message(monkeypatch):
    monkeypatch.setattr(sober.shutil, "which", lambda n: None)

    def none(args, **kw):
        raise FileNotFoundError("flatpak")
    steps, verdict = sober.run_fix(run=none, probe=lambda u: 200)
    assert steps[0].id == "flatpak" and not steps[0].ok and "Flatpak" in verdict


def test_docs_urls_and_log_paths_are_the_ones_sober_documents():
    assert sober.LATEST_LOG.endswith("sober/sober_logs/latest.log") and sober.STATE_FILE.endswith("data/sober/state")
    assert sober.MANIFEST_URL == "https://sober.vinegarhq.org/app" and sober.FLATHUB_URL.startswith("https://dl.flathub.org/")


# ------------------------------------------------------------------ the page
@pytest.fixture
def be_(tmp_path, monkeypatch, _qt_app):
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = default_config()
    cfg.steam_enabled = False
    cfg.first_run = False
    return be.Backend(cfg=cfg, store=Store(tmp_path / "s.json"), enable_gamepad=False)


def titles(rows):
    return " | ".join(r.get("title", "") for r in rows)


def test_page_lists_steps_run_fix_logs_and_the_honest_limit_then_shows_results(be_, monkeypatch, _qt_app):
    rows = be_.pageRows("robloxfix")
    text = titles(rows)
    assert "Run fix" in text and "Open Roblox again" in text and "latest.log" in text and "Code's log" in text
    assert "Honest limit" in text and "never downloads a Roblox file" in text
    assert any(r.get("id") == "rbxrun" for r in rows)
    steps = [sober.Step("dns", "DNS works", False, "blocked"), sober.Step("clock", "Clock", True, "Yes.")]
    monkeypatch.setattr(sober, "run_fix", lambda: (steps, "Verdict text here"))
    assert be_.pageActivate("robloxfix", "rbxrun") == "refresh"
    assert "Working" in titles(be_.pageRows("robloxfix"))
    end = time.time() + 5
    while be_._rbx_state != "done" and time.time() < end:
        _qt_app.processEvents()
        time.sleep(0.02)
    rows = be_.pageRows("robloxfix")
    text = titles(rows)
    assert "FIX  DNS works" in text and "OK   Clock" in text and "Verdict text here" in text
    assert be_.pageTitle("robloxfix") == "FIX ROBLOX"


def test_help_and_fix_my_game_open_the_page_and_open_roblox_launches_it(be_, monkeypatch):
    assert be_.pageActivate("help", "soberfix") == "page:robloxfix"
    launched, installs = [], []
    monkeypatch.setattr(be_, "_launch_game", lambda g: launched.append(g.gid))
    monkeypatch.setattr(be_, "begin_install", lambda specs, **kw: installs.append(specs))
    tile = next(g for g in be_._all if g.gid == "app:roblox")
    tile.missing = True
    be_.pageActivate("robloxfix", "rbxopen")
    assert installs == [["roblox"]] and not launched
    tile.missing = False
    assert be_.pageActivate("robloxfix", "rbxopen") == "close" and launched == ["app:roblox"]


def test_a_failed_roblox_start_with_the_bundle_screen_opens_the_fix_page(be_, monkeypatch):
    asked = []
    be_.pageRequested.connect(asked.append)
    be_._on_session_ended("app:roblox", "Roblox", 0.0, launcher_msg())
    assert asked == ["robloxfix"]
    be_._on_session_ended("app:heroic", "Heroic", 0.0, launcher_msg())
    assert asked == ["robloxfix"]                                                    # only Roblox, only for this problem
    be_._on_session_ended("app:roblox", "Roblox", 600.0, "")
    assert asked == ["robloxfix"]


def launcher_msg():
    from atarilauncher import launcher
    return launcher.INFO + sober.recovery_note(True, sober.service_checks(lambda u: 200))


# ------------------------------------------------------------------ "Permission Update Required"
USER_COMMAND = ("flatpak override --user --filesystem=xdg-run/app/com.discordapp.Discord:create --filesystem=xdg-run/discord-ipc-0 "
                "--device=all org.vinegarhq.Sober")


def test_the_override_is_exactly_the_command_sober_shows_user_level_and_for_sober_only():
    assert sober.OVERRIDE_COMMAND == USER_COMMAND
    assert sober.OVERRIDE_ARGS == USER_COMMAND.split() and sober.OVERRIDE_ARGS[-1] == "org.vinegarhq.Sober"
    assert "--user" in sober.OVERRIDE_ARGS and "--system" not in sober.OVERRIDE_ARGS
    assert sober.OVERRIDE_ARGS.count("org.vinegarhq.Sober") == 1 and "no password" in sober.OVERRIDE_PLAIN
    assert USER_COMMAND in sober.OVERRIDE_PLAIN


def test_permission_screen_is_found_in_the_log(tmp_path):
    assert sober.needs_permission("info: x\nERROR: Permission Update Required\n") and sober.needs_permission("run flatpak override --user ...")
    assert sober.needs_permission("... --device=all ...") and not sober.needs_permission("permission denied: /dev/foo")
    d = tmp_path / ".var/app/org.vinegarhq.Sober/data/sober/sober_logs"
    d.mkdir(parents=True)
    (d / "latest.log").write_text("ERROR: Permission Update Required\n")
    assert sober.permission_state(0, home=str(tmp_path)) is True
    (d / "latest.log").write_text("info: Roblox started\n")
    assert sober.permission_state(0, home=str(tmp_path)) is False


def test_override_applied_reads_flatpaks_own_answer_and_apply_runs_the_exact_command():
    assert sober.override_applied(Flatpak(override=True)) is True
    assert sober.override_applied(Flatpak(override=False)) is False
    f = Flatpak()
    ok, _ = sober.apply_override(f)
    assert ok and f.calls == [sober.OVERRIDE_ARGS] and f.override
    ok, tail = sober.apply_override(Flatpak(override_rc=1))
    assert not ok and "denied" in tail


def test_run_fix_gives_the_permission_when_missing_and_says_it_will_start_roblox_again():
    flat = Flatpak(override=False)
    steps, verdict = fix(flat)
    p = by_id(steps)["permissions"]
    assert p.ok and p.changed and USER_COMMAND in p.detail
    assert [c for c in flat.calls if c[:3] == ["flatpak", "override", "--user"] and "--show" not in c] == [sober.OVERRIDE_ARGS]
    assert "start Roblox again" in verdict
    flat2 = Flatpak(override=True)
    steps, verdict = fix(flat2)
    assert not by_id(steps)["permissions"].changed and "start Roblox again" not in verdict
    assert not [c for c in flat2.calls if "--show" not in c and c[:2] == ["flatpak", "override"]]      # nothing applied twice


def test_a_failing_override_is_reported_and_nothing_else_is_overridden():
    steps, verdict = fix(Flatpak(override_rc=1))
    p = by_id(steps)["permissions"]
    assert not p.ok and not p.changed and "denied" in p.detail and "denied" in verdict


def test_not_installed_means_no_override_is_attempted():
    flat = Flatpak(installed=False)
    steps, _ = fix(flat)
    assert "permissions" not in by_id(steps) and not [c for c in flat.calls if c[:2] == ["flatpak", "override"]]


def test_launch_that_shows_the_permission_screen_points_to_the_fix_page(tmp_path, monkeypatch):
    from atarilauncher import launcher
    monkeypatch.setattr(sober, "permission_state", lambda since=0.0, home=None: True)
    sec, msg = launcher._roblox_recover(["sober"], time.time(), None)
    assert msg.startswith(launcher.INFO) and "Permission Update Required" in msg and USER_COMMAND in msg and "Run fix" in msg
    monkeypatch.setattr(sober, "permission_state", lambda since=0.0, home=None: False)
    monkeypatch.setattr(sober, "bundle_state", lambda since=0.0, home=None: False)
    assert launcher._roblox_recover(["sober"], time.time(), None) is None             # a normal start is untouched


def test_install_gives_sober_the_permission_straight_away_and_only_sober(tmp_path, monkeypatch):
    from atarilauncher import appinstall as ai
    ran, installed = [], {"v": False}

    def run(cmd, out, cancel):
        ran.append(list(cmd))
        if cmd[:2] == ["flatpak", "install"]:
            installed["v"] = True
        return 0
    env = ai.Env(run=run, which=lambda n: "/usr/bin/" + n if n == "flatpak" else None, home=tmp_path)
    monkeypatch.setattr(ai, "flatpak_installed", lambda fid, home=None: installed["v"])
    monkeypatch.setattr(ai, "_flatpak_ready", lambda env, out, has_apt: True)
    lines = []
    ok, why = ai._try("flatpak", ai.TARGETS["roblox"], env, lines.append, False)
    assert ok and sober.OVERRIDE_ARGS in ran and ran.index(sober.OVERRIDE_ARGS) > 0
    assert any(USER_COMMAND in l for l in lines)                                        # the command is shown
    ran.clear()
    ok, _ = ai._try("flatpak", ai.TARGETS["steam"], env, lambda s: None, False)
    assert sober.OVERRIDE_ARGS not in ran                                               # other apps never get this override


def test_fix_page_shows_the_command_first_and_run_fix_relaunches_roblox(be_, monkeypatch, _qt_app):
    text = titles(be_.pageRows("robloxfix"))
    assert USER_COMMAND in text and "Permission Update Required" in text and "no password" in text
    launched, closed = [], []
    be_.pageRequested.connect(closed.append)
    monkeypatch.setattr(be_, "_launch_game", lambda g: launched.append(g.gid))
    tile = next(g for g in be_._all if g.gid == "app:roblox")
    tile.missing = False
    be_._roblox_fix_finished([sober.Step("permissions", "p", True, "d", changed=True)], "v")
    assert launched == ["app:roblox"] and closed == ["close"]
    launched.clear()
    be_._roblox_fix_finished([sober.Step("permissions", "p", True, "d")], "v")
    assert launched == []                                                               # nothing changed: no surprise relaunch
    assert "FIX  " not in titles(be_.pageRows("robloxfix")) and "OK   p" in titles(be_.pageRows("robloxfix"))
