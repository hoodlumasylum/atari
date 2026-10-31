"""Steam games from CodeAque: start Steam first and wait for it, then ask for the game; live status, hint, resend, cancel, session log."""
import os
import threading
import time

import pytest

from atarilauncher import config, kiosk, launcher
from atarilauncher.library import Game

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt  # noqa: E402
from tests.test_features_ui import conf  # noqa: E402
from tests.test_ui_keys import Ui, app, pump  # noqa: E402,F401


class FakeSteam:
    """A fake `steam`: logs its arguments; '-gamepadui' makes Steam 'run'; steam://rungameid/<id> starts the 'game' for a while."""

    def __init__(self, tmp_path, start_game=True, game_secs=1.0):
        self.tmp = tmp_path
        self.log = tmp_path / "calls.log"
        self.up = tmp_path / "up"
        self.game = tmp_path / "game"
        script = tmp_path / "steam"
        script.write_text("#!/bin/sh\n"
                          f'echo "$*" >> {self.log}\n'
                          f'case "$*" in *-gamepadui*) touch {self.up} ;; esac\n'
                          + (f'case "$*" in *rungameid*) (touch {self.game}; sleep {game_secs}; rm -f {self.game}) >/dev/null 2>&1 & ;; esac\n'
                             if start_game else ""))
        script.chmod(0o755)
        self.cmd = str(script)

    def calls(self):
        time.sleep(0.3)
        return self.log.read_text().splitlines() if self.log.exists() else []


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ATARI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(launcher, "clean_env", lambda: dict(os.environ))
    events = []
    monkeypatch.setattr(kiosk, "log_event", lambda m, *a, **k: events.append(m))
    fs = FakeSteam(tmp_path)
    monkeypatch.setattr(launcher, "find_steam_pids", lambda appid, proc_root="/proc": [1] if fs.game.exists() else [])
    cfg = config.default_config()
    cfg.steam_command = fs.cmd
    cfg.steam_bigpicture = True
    return fs, cfg, events


def game():
    return Game("steam:4242", "Heavy Rain Demo", "steam", "Steam", steam_appid="4242")


def run(cfg, fs, **kw):
    seen = []
    kw.setdefault("steam_running", lambda: fs.up.exists())
    kw.setdefault("ui_ready", lambda: fs.up.exists())
    out = launcher._run_steam(cfg, game(), lambda: None, poll=0.1, start_timeout=kw.pop("start_timeout", 10), grace=0.3, settle=0,
                              status=lambda ph, tx: seen.append((ph, tx)), **kw)
    return out, seen


def test_steam_is_started_first_then_asked_for_the_game(env):
    fs, cfg, events = env
    (secs, err), seen = run(cfg, fs)
    assert err == "" and secs > 0.5
    calls = fs.calls()
    assert calls[0] == "-gamepadui" and calls[1] == "steam://rungameid/4242" and len(calls) == 2
    phases = [p for p, _ in seen]
    assert phases[0] == "starting" and "launching" in phases and phases[-1] == "playing"
    assert phases.index("launching") < phases.index("playing")
    assert any("Heavy Rain Demo" in t for p, t in seen if p == "launching")


def test_a_running_steam_is_not_started_again(env):
    fs, cfg, events = env
    fs.up.touch()
    (secs, err), seen = run(cfg, fs)
    assert err == "" and fs.calls() == ["steam://rungameid/4242"]
    assert "starting" not in [p for p, _ in seen]


def test_it_waits_for_steams_window_before_asking(env, monkeypatch):
    fs, cfg, events = env
    t0 = time.time()
    ready_at = {"t": None}

    def ui():
        if fs.up.exists() and ready_at["t"] is None:
            ready_at["t"] = time.time() + 0.8        # Steam "updates" for a moment
        return ready_at["t"] is not None and time.time() >= ready_at["t"]
    (secs, err), seen = run(cfg, fs, ui_ready=ui)
    assert err == "" and time.time() - t0 > 0.8
    first_ask = [i for i, (p, _) in enumerate(seen) if p == "launching"][0]
    assert all(p == "starting" for p, _ in seen[:first_ask]) and first_ask >= 3     # live "Starting Steam... N s" updates in between


def test_no_game_shows_status_steps_aside_hints_and_asks_again_then_explains(env):
    fs, cfg, events = env
    fs2 = FakeSteam(fs.tmp, start_game=False)
    fs2.up.touch()
    cfg.steam_command = fs2.cmd
    (secs, err), seen = run(cfg, fs2, start_timeout=2.0, reveal_after=0.3, resend_after=0.8, hint_after=1.2)
    phases = [p for p, _ in seen]
    assert "reveal" in phases and "playing" not in phases
    assert any("Still nothing after a minute" in t for _, t in seen)
    assert fs2.calls().count("steam://rungameid/4242") == 2                      # once, plus one resend
    assert secs == 0 and "did not start" in err
    assert any("never started" in e for e in events) and any("asking Steam again" in e for e in events)


def test_cancel_returns_to_code_and_leaves_steam_running(env):
    fs, cfg, events = env
    fs2 = FakeSteam(fs.tmp, start_game=False)
    fs2.up.touch()
    cfg.steam_command = fs2.cmd
    cancel = threading.Event()
    threading.Timer(0.5, cancel.set).start()
    (secs, err), seen = run(cfg, fs2, start_timeout=20, cancel=cancel)
    assert secs == 0 and err.startswith(launcher.INFO) and "Cancelled" in err
    assert any("cancelled" in e for e in events)


def test_cancel_while_steam_is_still_starting(env):
    fs, cfg, events = env
    cancel = threading.Event()
    threading.Timer(0.4, cancel.set).start()
    (secs, err), seen = run(cfg, fs, cancel=cancel, ui_ready=lambda: False, start_timeout=30)
    assert "Cancelled" in err


def test_steam_that_never_starts_is_reported(env, monkeypatch):
    fs, cfg, events = env
    t = {"n": 0}
    monkeypatch.setattr(launcher.time, "time", lambda: t.__setitem__("n", t["n"] + 5) or 1000.0 + t["n"])
    monkeypatch.setattr(launcher.time, "sleep", lambda s: None)
    (secs, err), seen = run(cfg, fs, steam_running=lambda: False, ui_ready=lambda: False, start_timeout=100)
    assert secs == 0 and "Steam did not start" in err


def test_steam_closing_before_the_game_is_reported(env):
    fs, cfg, events = env
    fs2 = FakeSteam(fs.tmp, start_game=False)
    fs2.up.touch()
    cfg.steam_command = fs2.cmd
    state = {"n": 0}

    def running():
        state["n"] += 1
        return state["n"] < 3                        # Steam is there for the first checks, then gone
    (secs, err), _ = run(cfg, fs2, steam_running=running, start_timeout=30, reveal_after=100)
    assert "Steam closed before the game started" in err or "did not seem" in err


def test_big_picture_flag_is_used_when_wanted_and_not_otherwise(env, monkeypatch):
    fs, cfg, events = env
    cfg.steam_bigpicture = False
    monkeypatch.setattr(kiosk, "shell_mode", lambda *a, **k: False)
    (secs, err), _ = run(cfg, fs, steam_running=lambda: fs.up.exists() or fs.log.exists() and bool(fs.up.touch()) is None)
    assert fs.calls()[0] == "-silent"                # `steam -silent` (no -gamepadui) outside CodeAque-only mode when the setting is off


def test_every_step_lands_in_the_session_log(env):
    fs, cfg, events = env
    run(cfg, fs)
    text = "\n".join(events)
    for word in ("Steam is not running - starting it", "Steam is up after", "asking Steam for the game", "game process found after", "the game ended after"):
        assert word in text, word


# ------------------------------------------------------------------ in CodeAque (backend + the Now Playing screen)
def test_status_steps_code_aside_in_code_only_mode_and_cancel_works(app, tmp_path, monkeypatch):
    conf(tmp_path)
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        b = ui.backend
        monkeypatch.delenv("ATARI_NO_MINIMIZE", raising=False)
        hidden = []
        monkeypatch.setattr(b, "_hide_for_game", lambda: hidden.append(1))
        b._running = True
        monkeypatch.setattr(b, "_shell_mode", lambda: True)
        b._on_launch_status("starting", "Starting Steam... 3 s")
        assert b.runningStatus == "Starting Steam... 3 s" and b.runningCancelable and not hidden
        b._on_launch_status("reveal", "Waiting")
        assert hidden == [1]
        monkeypatch.setattr(b, "_shell_mode", lambda: False)
        b._on_launch_status("playing", "Playing")
        assert hidden == [1] and not b.runningCancelable
        b._on_launch_status("waiting", "w")
        assert b.runningCancelable
        b.cancelLaunch()
        assert b._launch_cancel.is_set() and not b.runningCancelable and b.runningStatus == "Cancelling..."
    finally:
        ui.close()


def test_escape_on_the_now_playing_screen_cancels_a_steam_start_only(app, tmp_path, monkeypatch):
    conf(tmp_path)
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        b = ui.backend
        b._running, b._run_cancelable = True, True
        b.runningChanged.emit()
        b.runningStatusChanged.emit()
        pump(app, 100)
        ui.key(Qt.Key_Escape)
        assert b._launch_cancel.is_set()
        b._launch_cancel.clear()
        b._run_cancelable = False                         # a game that is really running: keys are left to the game
        b.runningStatusChanged.emit()
        ui.key(Qt.Key_Escape)
        assert not b._launch_cancel.is_set()
    finally:
        ui.close()


# ------------------------------------------------------------------ 0.4.9: a game that is already running, stuck "loading", stale state
def test_a_game_that_is_already_running_is_not_asked_for_again_but_brought_to_front(env):
    fs, cfg, events = env
    fs.up.touch()
    fs.game.touch()                                   # Marvel Rivals "is already running"
    fronted = []
    threading.Timer(0.8, lambda: fs.game.unlink()).start()
    (secs, err), seen = run(cfg, fs, front=lambda pids: fronted.append(pids) or True)
    assert err == "" and fronted == [[1]]
    assert fs.calls() == []                           # no steam://rungameid at all: Steam would ignore it and CodeAque stayed on "loading"
    assert any("already running" in t for p, t in seen) and [p for p, _ in seen][-1] == "playing"
    assert any("already running" in e for e in events)


def test_already_running_but_cannot_be_raised_says_what_to_do(env):
    fs, cfg, events = env
    fs.up.touch()
    fs.game.touch()
    threading.Timer(0.6, lambda: fs.game.unlink()).start()
    (secs, err), seen = run(cfg, fs, front=lambda pids: False)
    assert err == "" and any("Alt+Tab" in t for p, t in seen if p == "playing")


def test_cancel_while_the_game_runs_stops_tracking_and_leaves_the_game(env):
    fs, cfg, events = env
    fs.up.touch()
    fs.game.touch()
    cancel = threading.Event()
    threading.Timer(0.6, cancel.set).start()
    (secs, err), seen = run(cfg, fs, front=lambda pids: True, cancel=cancel)
    assert err.startswith(launcher.INFO) and "may still be running" in err
    assert fs.game.exists()                           # the game itself was not touched
    assert any("stopped waiting" in e for e in events)


def test_waiting_for_the_game_has_its_own_shorter_limit(env):
    fs, cfg, events = env
    fs2 = FakeSteam(fs.tmp, start_game=False)
    fs2.up.touch()
    cfg.steam_command = fs2.cmd
    t0 = time.time()
    (secs, err), seen = run(cfg, fs2, start_timeout=60, game_wait=1.0)
    assert time.time() - t0 < 10 and "did not start" in err and "anti-cheat" in err and "ProtonDB" in err


def test_bring_to_front_uses_xdotool_for_the_game_and_its_children(tmp_path):
    proc = tmp_path / "proc"
    for pid, ppid in ((10, 1), (11, 10), (12, 11)):
        (proc / str(pid)).mkdir(parents=True)
        (proc / str(pid) / "stat").write_text(f"{pid} (wine) S {ppid} 0 0\n")
    calls = []

    class R:
        def __init__(self, rc=0, out=""):
            self.returncode, self.stdout = rc, out

    def run_(cmd, **kw):
        calls.append(cmd)
        if cmd[:2] == ["xdotool", "search"]:
            return R(0, "777\n") if cmd[-1] == "12" else R(1, "")
        return R(0)
    ok = launcher.bring_to_front([10], which=lambda n: "/usr/bin/" + n if n == "xdotool" else None, run=run_, proc_root=str(proc))
    assert ok and ["xdotool", "windowactivate", "777"] in calls
    assert launcher.bring_to_front([], which=lambda n: None) is False
    assert launcher.bring_to_front([10], which=lambda n: None, run=run_, proc_root=str(proc)) is False


def test_bring_to_front_with_wmctrl(tmp_path):
    proc = tmp_path / "proc"
    (proc / "10").mkdir(parents=True)
    (proc / "10" / "stat").write_text("10 (game) S 1 0 0\n")
    calls = []

    class R:
        returncode = 0
        stdout = "0x01 0 99 host Other\n0x02 0 10 host Marvel Rivals\n"
    ok = launcher.bring_to_front([10], which=lambda n: "/x/wmctrl" if n == "wmctrl" else None,
                                 run=lambda cmd, **kw: calls.append(cmd) or R(), proc_root=str(proc))
    assert ok and ["wmctrl", "-ia", "0x02"] in calls


def test_playing_screen_offers_back_to_game_and_stop_waiting(app, tmp_path, monkeypatch):
    conf(tmp_path)
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        b = ui.backend
        b._running, b._running_appid, b._running_title = True, "4242", "Heavy Rain Demo"
        b._launch_cancel = threading.Event()
        b._on_launch_status("playing", "Playing")
        assert b.runningPlaying and not b.runningCancelable
        pump(app, 100)
        shown = []
        monkeypatch.setattr(launcher, "bring_to_front", lambda pids: shown.append(pids) or True)
        monkeypatch.setattr(launcher, "find_steam_pids", lambda appid, proc_root="/proc": [5])
        ui.key(Qt.Key_Return)
        for _ in range(30):
            pump(app, 50)
            if shown:
                break
        assert shown == [[5]]
        ui.key(Qt.Key_Escape)
        assert b._launch_cancel.is_set() and not b.runningPlaying and b.runningStatus == "Cancelling..."
    finally:
        ui.close()


def test_a_new_launch_forgets_that_codeaque_was_minimised_for_the_last_one(app, tmp_path, monkeypatch):
    conf(tmp_path)
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        b = ui.backend
        b._minimized_for_game = True                  # the user brought the window back by hand last time
        monkeypatch.setattr(launcher, "run_game", lambda *a, **k: (0.0, ""))
        g = Game("steam:4242", "Heavy Rain Demo", "steam", "Steam", steam_appid="4242")
        b._launch_game(g)
        assert b._minimized_for_game is False and b._running_appid == "4242"
        for _ in range(40):
            pump(app, 50)
            if not b._running:
                break
        assert not b._running and not b.runningPlaying and b.runningStatus == ""
    finally:
        ui.close()


def test_stale_minimised_flag_does_not_stop_the_next_game_stepping_aside(app, tmp_path, monkeypatch):
    conf(tmp_path)
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        b = ui.backend
        calls = []
        monkeypatch.setattr(ui.win, "showMinimized", lambda: calls.append("min"))
        monkeypatch.setattr(b, "_window", ui.win)
        b._running = True
        b._minimized_for_game = True                 # left over: the window is really on screen (the user brought it back by hand)
        b._hide_for_game()
        assert calls == ["min"]
    finally:
        ui.close()


# ------------------------------------------------------------------ 0.5.0 (t421u): stuck on "Starting Steam... 26 s"
def test_running_steam_without_a_window_process_does_not_block(env):
    fs, cfg, events = env
    t0 = time.time()
    (secs, err), seen = run(cfg, fs, ui_ready=lambda: False, ui_grace=0.6)
    assert err == "" and time.time() - t0 < 6
    assert any("asking for the game anyway" in e for e in events)
    assert "steam://rungameid/4242" in fs.calls()


def test_steam_started_silent_outside_big_picture(env, monkeypatch):
    fs, cfg, events = env
    cfg.steam_bigpicture = False
    monkeypatch.setattr(kiosk, "shell_mode", lambda *a, **k: False)
    run(cfg, fs, steam_running=lambda: fs.log.exists(), ui_ready=lambda: fs.log.exists())
    assert fs.calls()[0] == "-silent"


def test_rungameid_is_retried_every_few_seconds(env):
    fs, cfg, events = env
    fs2 = FakeSteam(fs.tmp, start_game=False)
    fs2.up.touch()
    cfg.steam_command = fs2.cmd
    run(cfg, fs2, start_timeout=2.2, reveal_after=5, resend_after=0.3, resend_every=0.5, hint_after=9)
    assert fs2.calls().count("steam://rungameid/4242") >= 4


def test_steam_detected_by_process_name_and_pid_file(tmp_path):
    from atarilauncher import steam
    proc = tmp_path / "proc"
    (proc / "77").mkdir(parents=True)
    (proc / "77" / "cmdline").write_bytes(b"")              # helpers rewrite their command lines
    (proc / "77" / "comm").write_text("steamwebhelper\n")
    home = tmp_path / "h"
    home.mkdir()
    assert steam.steam_running(str(proc), home=home) and steam.steam_ui_ready(str(proc))
    (proc / "77" / "comm").write_text("bash\n")
    assert not steam.steam_running(str(proc), home=home)
    (proc / "88").mkdir()
    (proc / "88" / "cmdline").write_bytes(b"x")
    (proc / "88" / "comm").write_text("steam\n")
    (home / ".steam").mkdir()
    (home / ".steam" / "steam.pid").write_text("88")
    assert steam.steam_running(str(proc), home=home)


def test_steam_log_report(tmp_path):
    from atarilauncher import steam
    logs = tmp_path / ".local/share/Steam/logs"
    logs.mkdir(parents=True)
    (logs / "console_log.txt").write_text("hello from steam\n")
    text = steam.steam_log_report(home=tmp_path, session_lines=["x steam launch: asking Steam for the game", "other"])
    assert "asking Steam for the game" in text and "hello from steam" in text and "other" not in text


# ------------------------------------------------------------------ 0.5.0 (t424u): start Steam at boot (hidden)
def test_remembered_login_flag_only(tmp_path):
    from atarilauncher import steam
    assert not steam.remembered_login(tmp_path)
    cfgd = tmp_path / ".local/share/Steam/config"
    cfgd.mkdir(parents=True)
    (cfgd / "loginusers.vdf").write_text('"users"\n{\n "7656" { "AccountName" "x" "RememberPassword" "0" }\n}\n')
    assert not steam.remembered_login(tmp_path)
    (cfgd / "loginusers.vdf").write_text('"users"\n{\n "7656" { "AccountName" "x" "RememberPassword" "1" }\n}\n')
    assert steam.remembered_login(tmp_path)
    assert steam.autostart_command(["steam"]) == ["steam", "-silent"]


def test_autostart_setting_default_on_when_installed(app, tmp_path, monkeypatch):
    from atarilauncher import steam
    conf(tmp_path)
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        b = ui.backend
        monkeypatch.setattr(b, "_steam_installed", lambda: True)
        monkeypatch.setattr(steam, "steam_running", lambda *a, **k: False)
        assert b._steam_autostart_on()
        row = next(r for r in b.setupRows() if r.get("kind") == "steamboot")
        assert row["title"].endswith("ON") and "password" in row["detail"]
        spawned, toasts = [], []
        monkeypatch.setattr(b, "show_toast", lambda t, *a: toasts.append(t))
        monkeypatch.setattr(steam, "remembered_login", lambda *a, **k: False)
        assert b._steam_autostart(spawn=spawned.append) == "login" and not spawned and "Open Steam once to log in" in toasts[0]
        monkeypatch.setattr(steam, "remembered_login", lambda *a, **k: True)
        assert b._steam_autostart(spawn=spawned.append) == "started" and spawned[0][-1] == "-silent"
        monkeypatch.setattr(steam, "steam_running", lambda *a, **k: True)
        assert b._steam_autostart(spawn=spawned.append) == "running" and len(spawned) == 1
        b.toggleSteamBoot()
        assert not b._steam_autostart_on() and b._steam_autostart(spawn=spawned.append) == "off"
        monkeypatch.setattr(b, "_steam_installed", lambda: False)
        b.store.set_pref(steam.AUTOSTART_PREF, None)
        assert not b._steam_autostart_on()
    finally:
        ui.close()


def test_marvel_rivals_gets_the_launch_option_hint(env):
    fs, cfg, events = env
    fs2 = FakeSteam(fs.tmp, start_game=False)
    fs2.up.touch()
    cfg.steam_command = fs2.cmd
    g = Game("steam:2767030", "Marvel Rivals", "steam", "Steam", steam_appid="2767030")
    secs, err = launcher._run_steam(cfg, g, lambda: None, poll=0.1, start_timeout=1.0, grace=0.3, settle=0, reveal_after=5,
                                    hint_after=0.5, steam_running=lambda: True, ui_ready=lambda: True)
    assert "SteamDeck=1 %command%" in err
    assert launcher.launch_option_hint("4242") == ""
