import os
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

from atarilauncher import config, kiosk, launcher, steamfix
from atarilauncher.library import Game

NO = lambda: False   # noqa: E731  (Steam is not running)
YES = lambda: True   # noqa: E731


def reg(home, startup=None, extra=""):
    p = home / ".steam" / "registry.vdf"
    p.parent.mkdir(parents=True, exist_ok=True)
    s = f'\t\t\t\t\t"language"\t\t"english"\n{extra}'
    if startup is not None:
        s += f'\t\t\t\t\t"StartupMode"\t\t"{startup}"\n'
    p.write_text('"Registry"\n{\n\t"HKCU"\n\t{\n\t\t"Software"\n\t\t{\n\t\t\t"Valve"\n\t\t\t{\n\t\t\t\t"Steam"\n\t\t\t\t{\n' + s +
                 '\t\t\t\t}\n\t\t\t}\n\t\t}\n\t}\n}\n')
    return p


def conf_vdf(home, body=""):
    root = home / ".local" / "share" / "Steam"
    (root / "config").mkdir(parents=True)
    (root / "steamapps").mkdir()
    p = root / "config" / "config.vdf"
    p.write_text('"InstallConfigStore"\n{\n\t"Software"\n\t{\n\t\t"Valve"\n\t\t{\n\t\t\t"Steam"\n\t\t\t{\n'
                 '\t\t\t\t"BaseInstallFolder_1"\t\t"/games"\n' + body + '\t\t\t}\n\t\t}\n\t}\n}\n')
    return p


# ------------------------------------------------------------------ the VDF reader / writer
def test_vdf_round_trips_quotes_slashes_and_unicode():
    d = {"A": {"path": 'C:\\Games "x"', "n": "ünï\tcode", "B": {"k": ""}}}
    assert steamfix.parse(steamfix.dump(d)) == d


@pytest.mark.parametrize("bad", ['"A"\n{\n"b" "c"\n', '"A" "b" }', '"A"', '"A" {', "garbage"])
def test_vdf_refuses_what_it_cannot_read(bad):
    with pytest.raises(steamfix.VdfError):
        steamfix.parse(bad)


# ------------------------------------------------------------------ Steam's own "start in Big Picture" setting
def test_startup_mode_is_written_with_a_backup_and_everything_else_kept(tmp_path):
    p = reg(tmp_path, startup="0", extra='\t\t\t\t\t"AutoLoginUser"\t\t"me"\n')
    original = p.read_text()
    changed, text = steamfix.set_startup_bigpicture(tmp_path, NO)
    assert changed and "ON" in text
    data = steamfix.parse(p.read_text())
    steam = data["Registry"]["HKCU"]["Software"]["Valve"]["Steam"]
    assert steam["StartupMode"] == "1" and steam["AutoLoginUser"] == "me" and steam["language"] == "english"
    assert (tmp_path / ".steam" / "registry.vdf.code-backup").read_text() == original
    assert steamfix.set_startup_bigpicture(tmp_path, NO)[0] is False         # second time: nothing to do
    assert (tmp_path / ".steam" / "registry.vdf.code-backup").read_text() == original   # the first backup is never overwritten


def test_startup_mode_is_added_when_missing(tmp_path):
    p = reg(tmp_path)
    assert steamfix.set_startup_bigpicture(tmp_path, NO)[0]
    assert steamfix.parse(p.read_text())["Registry"]["HKCU"]["Software"]["Valve"]["Steam"]["StartupMode"] == "1"


def test_startup_mode_is_not_written_while_steam_runs(tmp_path):
    p = reg(tmp_path, startup="0")
    before = p.read_text()
    changed, text = steamfix.set_startup_bigpicture(tmp_path, YES)
    assert not changed and "open right now" in text and p.read_text() == before


def test_startup_mode_without_a_registry_or_with_a_broken_one_is_harmless(tmp_path):
    assert steamfix.set_startup_bigpicture(tmp_path, NO)[0] is False
    p = tmp_path / ".steam" / "registry.vdf"
    p.parent.mkdir(parents=True)
    p.write_text('"Registry" {')
    changed, text = steamfix.set_startup_bigpicture(tmp_path, NO)
    assert not changed and "Could not" in text and p.read_text() == '"Registry" {'


# ------------------------------------------------------------------ Steam Play (Proton) for all games
def test_proton_default_is_set_when_nobody_chose(tmp_path):
    p = conf_vdf(tmp_path)
    changed, text = steamfix.set_default_proton(tmp_path, "", NO)
    assert changed and "proton-experimental" in text
    steam = steamfix.parse(p.read_text())["InstallConfigStore"]["Software"]["Valve"]["Steam"]
    assert steam["CompatToolMapping"]["0"]["name"] == "proton-experimental"
    assert steam["BaseInstallFolder_1"] == "/games"                          # the rest is untouched
    assert (p.parent / "config.vdf.code-backup").is_file()


def test_proton_choice_of_the_user_is_never_overwritten(tmp_path):
    body = '\t\t\t\t"CompatToolMapping"\n\t\t\t\t{\n\t\t\t\t\t"0"\n\t\t\t\t\t{\n\t\t\t\t\t\t"name"\t\t"GE-Proton9-1"\n\t\t\t\t\t}\n\t\t\t\t}\n'
    p = conf_vdf(tmp_path, body)
    before = p.read_text()
    changed, text = steamfix.set_default_proton(tmp_path, "", NO)
    assert not changed and "GE-Proton9-1" in text and p.read_text() == before


def test_proton_keeps_per_game_choices(tmp_path):
    body = '\t\t\t\t"CompatToolMapping"\n\t\t\t\t{\n\t\t\t\t\t"620"\n\t\t\t\t\t{\n\t\t\t\t\t\t"name"\t\t"proton_9"\n\t\t\t\t\t}\n\t\t\t\t}\n'
    p = conf_vdf(tmp_path, body)
    assert steamfix.set_default_proton(tmp_path, "", NO)[0]
    cm = steamfix.parse(p.read_text())["InstallConfigStore"]["Software"]["Valve"]["Steam"]["CompatToolMapping"]
    assert cm["620"]["name"] == "proton_9" and cm["0"]["name"] == "proton-experimental"


def test_proton_waits_while_steam_runs_and_survives_missing_or_bad_files(tmp_path):
    assert steamfix.set_default_proton(tmp_path, "", NO)[0] is False         # no Steam at all
    p = conf_vdf(tmp_path)
    before = p.read_text()
    assert steamfix.set_default_proton(tmp_path, "", YES)[0] is False and p.read_text() == before
    p.write_text('"InstallConfigStore" {')
    changed, text = steamfix.set_default_proton(tmp_path, "", NO)
    assert not changed and "Could not" in text and "Enable Steam Play" in text


def test_apply_honours_the_config_switch(tmp_path):
    reg(tmp_path, startup="0")
    p = conf_vdf(tmp_path)
    cfg = config.Config()
    cfg.steam_proton_default = False
    out = steamfix.apply(cfg, tmp_path, NO)
    assert len(out) == 1 and "CompatToolMapping" not in p.read_text()
    cfg.steam_proton_default = True
    assert len(steamfix.apply(cfg, tmp_path, NO)) == 2 and "CompatToolMapping" in p.read_text()


def test_proton_flag_round_trips_in_config(tmp_path, monkeypatch):
    monkeypatch.setenv("ATARI_CONFIG_DIR", str(tmp_path))
    cfg = config.Config()
    assert cfg.steam_proton_default is True
    cfg.steam_proton_default = False
    config.save_config(cfg)
    assert config.load_config().steam_proton_default is False


# ------------------------------------------------------------------ the `steam` wrapper, run for real with a fake Steam
def fake_path(tmp_path, steam_running):
    shims = steamfix.install_shim(tmp_path)
    real = tmp_path / "bin"
    real.mkdir(exist_ok=True)
    (real / "steam").write_text('#!/bin/sh\necho "ARGS: $*"\n')
    (real / "pgrep").write_text("#!/bin/sh\nexit " + ("0" if steam_running else "1") + "\n")
    for f in real.iterdir():
        f.chmod(0o755)
    return {"PATH": f"{shims}:{real}:/usr/bin:/bin"}, shims


def run_shim(tmp_path, args, steam_running=False):
    env, shims = fake_path(tmp_path, steam_running)
    r = subprocess.run([str(shims / "steam"), *args], env=env, capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def test_wrapper_adds_gamepadui_to_a_plain_steam(tmp_path):
    assert run_shim(tmp_path, []) == "ARGS: -gamepadui"
    assert run_shim(tmp_path, ["-nochatui"]) == "ARGS: -gamepadui -nochatui"


def test_wrapper_opens_big_picture_in_a_steam_that_is_already_open(tmp_path):
    assert run_shim(tmp_path, [], steam_running=True) == "ARGS: steam://open/bigpicture"


def test_wrapper_leaves_explicit_requests_alone(tmp_path):
    assert run_shim(tmp_path, ["-gamepadui"]) == "ARGS: -gamepadui"
    assert run_shim(tmp_path, ["-applaunch", "620"], steam_running=True) == "ARGS: -applaunch 620"
    assert run_shim(tmp_path, ["steam://rungameid/620"]) == "ARGS: steam://rungameid/620"
    assert run_shim(tmp_path, ["-shutdown"]) == "ARGS: -shutdown"


def test_wrapper_without_a_real_steam_says_so(tmp_path):
    shims = steamfix.install_shim(tmp_path)
    r = subprocess.run([str(shims / "steam")], env={"PATH": f"{shims}:/nonexistent"}, capture_output=True, text=True, timeout=20)
    assert r.returncode == 127 and "not found" in r.stderr


def test_shim_is_executable_idempotent_and_goes_first_in_path(tmp_path):
    d = steamfix.install_shim(tmp_path)
    assert os.access(d / "steam", os.X_OK)
    steamfix.install_shim(tmp_path)
    env = {"PATH": "/usr/bin:/bin"}
    assert steamfix.put_shim_first(env, tmp_path) and env["PATH"].split(":")[0] == str(d)
    steamfix.put_shim_first(env, tmp_path)
    assert env["PATH"].split(":").count(str(d)) == 1


# ------------------------------------------------------------------ the watcher
def test_guard_nudges_a_foreign_steam_twice_then_stops():
    g = steamfix.Guard((10, 30))
    sent = [g.tick(True, t) for t in (0, 5, 10, 11, 29, 30, 31, 100)]
    assert sent == [False, False, True, False, False, True, False, False]


def test_guard_stays_quiet_for_a_steam_code_started_and_resets_when_steam_closes():
    g = steamfix.Guard((10, 30))
    g.tick(True, 0)
    g.handled_by_code()
    assert not any(g.tick(True, t) for t in (10, 30, 60))
    g.tick(False, 70)
    g.tick(True, 100)
    assert g.tick(True, 110) is True                  # a new Steam process is watched again


# ------------------------------------------------------------------ the Steam tile in Code-only mode
def test_big_picture_is_forced_in_code_only_mode(monkeypatch):
    cfg = config.Config()
    cfg.steam_bigpicture = False
    monkeypatch.setattr(kiosk, "shell_mode", lambda *a, **k: False)
    assert launcher.big_picture_wanted(cfg) is False
    monkeypatch.setattr(kiosk, "shell_mode", lambda *a, **k: True)
    assert launcher.big_picture_wanted(cfg) is True
    cfg.steam_bigpicture = True
    monkeypatch.setattr(kiosk, "shell_mode", lambda *a, **k: False)
    assert launcher.big_picture_wanted(cfg) is True


# ------------------------------------------------------------------ the window manager
def test_window_manager_detection():
    assert kiosk.window_manager(lambda n: None) == ""
    assert kiosk.window_manager(lambda n: "/x/" + n if n == "marco" else None) == "marco"


def test_install_wm_runs_one_pkexec_script_and_explains(monkeypatch):
    seen = []

    def run(cmd, out, _):
        seen.append(cmd)
        return 0
    ok, text = kiosk.install_wm(run, which=lambda n: None)
    assert ok and "Restart" in text and seen[0][:3] == ["pkexec", "sh", "-c"]
    assert "apt-get install -y openbox" in seen[0][3] and "set -e" in seen[0][3]
    assert kiosk.install_wm(lambda *a: 1 / 0, which=lambda n: "/x")[0]       # already there: asks nothing
    assert "password window was closed" in kiosk.install_wm(lambda *a: 126, which=lambda n: None)[1]
    ok, text = kiosk.install_wm(lambda *a: 83, which=lambda n: None)
    assert not ok and "sudo apt install openbox" in text
    assert not kiosk.install_wm(lambda *a: 1 / 0, which=lambda n: None)[0]   # never raises


def test_session_script_still_starts_a_window_manager_first():
    s = kiosk.session_script("hazel") if hasattr(kiosk, "session_script") else kiosk.enable_script("hazel")
    assert "openbox" in s and "apt-get install -y openbox" in s


# ------------------------------------------------------------------ inside Code (backend)
pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from tests.test_features_ui import conf  # noqa: E402
from tests.test_ui_keys import Ui, app  # noqa: E402,F401


def test_steam_page_explains_dialogs_and_offers_proton_in_code_only_mode(app, tmp_path, monkeypatch):
    conf(tmp_path)
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        monkeypatch.setattr(ui.backend, "_shell_mode", lambda: True)
        rows = ui.backend._steam_rows()
        text = " ".join(r.get("title", "") for r in rows)
        assert "ALWAYS opens in Big Picture" in text and "Properties" in text
        assert any(r.get("id") == "steamproton" for r in rows)
        monkeypatch.setattr(ui.backend, "_shell_mode", lambda: False)
        assert not any(r.get("id") == "steamproton" for r in ui.backend._steam_rows())
    finally:
        ui.close()


def test_proton_button_edits_the_users_config_and_says_what_happened(app, tmp_path, monkeypatch):
    conf(tmp_path)
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        home = tmp_path / "home"
        p = conf_vdf(home)
        monkeypatch.setattr(steamfix.steam_mod, "steam_running", lambda: False)
        toasts = []
        monkeypatch.setattr(ui.backend, "show_toast", lambda t, *a: toasts.append(t))
        ui.backend.pageActivate("steam", "steamproton")
        assert "CompatToolMapping" in p.read_text() and "proton-experimental" in toasts[0]
    finally:
        ui.close()


def test_code_page_offers_the_window_manager_when_none_is_installed(app, tmp_path, monkeypatch):
    conf(tmp_path)
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        monkeypatch.setattr(kiosk, "enabled", lambda *a, **k: True)
        monkeypatch.setattr(kiosk, "window_manager", lambda *a, **k: "")
        rows = ui.backend._kiosk_rows()
        assert any(r.get("id") == "kioskwm" for r in rows)
        assert any("Steam's own windows" in r.get("title", "") for r in rows)
        monkeypatch.setattr(kiosk, "window_manager", lambda *a, **k: "openbox")
        assert not any(r.get("id") == "kioskwm" for r in ui.backend._kiosk_rows())
    finally:
        ui.close()


def test_watcher_asks_a_foreign_steam_for_big_picture(app, tmp_path, monkeypatch):
    conf(tmp_path)
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        b = ui.backend
        calls = []
        b._steam_guard = steamfix.Guard((0, 5))
        b._steam_run = lambda cmd, **kw: calls.append(cmd)
        monkeypatch.setattr(steamfix.steam_mod, "steam_running", lambda: True)
        b.cfg.emulator_commands["steam"] = "/bin/steam-test"
        b._steam_tick()
        for _ in range(100):
            if calls:
                break
            import time
            time.sleep(0.05)
        assert calls and calls[0][-1] == "steam://open/bigpicture"
        assert b._steam_busy is False
        # a Steam that Code started itself is left alone
        calls.clear()
        b._steam_guard = steamfix.Guard((0, 5))
        b._running_gid = "app:steam"
        b._steam_tick()
        import time
        time.sleep(0.3)
        assert calls == []
    finally:
        ui.close()


def test_code_hides_while_steam_runs_in_code_only_mode_only(app, tmp_path, monkeypatch):
    conf(tmp_path)
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        b = ui.backend
        monkeypatch.delenv("ATARI_NO_MINIMIZE", raising=False)
        for shell, expect in ((True, True), (False, False)):
            monkeypatch.setattr(b, "_shell_mode", lambda s=shell: s)
            b._running_gid, b._running_is_rom = "app:steam", False
            b._hide_timer.stop()
            b._on_session_started()
            assert b._hide_timer.isActive() is expect
            b._hide_timer.stop()
    finally:
        ui.close()
