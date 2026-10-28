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
    assert secs == 0 and "did not seem to start the game" in err
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
    assert fs.calls()[0] == ""                       # plain `steam` (no -gamepadui) outside CodeAque-only mode when the setting is off


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
