"""Esc-to-return for web apps and Kodi, the F9 hotkey, and the gamepad chords - the keyboard parts run against a real
(headless) X server: Xvfb + xdotool send real key events, the watcher looks at them with XQueryKeymap."""
import os
import shutil
import stat
import subprocess
import sys
import time

import pytest

from atarilauncher import exitwatch, launcher
from atarilauncher.exitwatch import EscDetector
from atarilauncher.gamepad_helper import GuideChord

X = pytest.mark.skipif(not (shutil.which("Xvfb") and shutil.which("xdotool")), reason="needs Xvfb and xdotool")


# ------------------------------------------------------------------ the gesture state machine
def feed(det, seq):
    """seq = [(time, esc, ctrl)] -> list of results"""
    return [det.feed(t, e, c) for t, e, c in seq]


def test_single_esc_does_nothing():
    d = EscDetector()
    assert feed(d, [(0, False, False), (0.1, True, False), (0.2, False, False), (3.0, False, False)]) == ["", "", "", ""]


def test_two_quick_presses_quit_but_two_slow_ones_do_not():
    d = EscDetector()
    r = feed(d, [(0, False, False), (0.1, True, False), (0.2, False, False), (0.4, True, False), (0.5, False, False)])
    assert r[3] == "double"
    d = EscDetector()
    r = feed(d, [(0, False, False), (0.1, True, False), (0.2, False, False), (1.2, True, False), (1.3, False, False)])
    assert r == ["", "", "", "", ""]


def test_hold_one_second_quits_once():
    d = EscDetector()
    out = feed(d, [(0, False, False), (0.1, True, False), (0.5, True, False), (1.0, True, False), (1.2, True, False), (1.5, True, False)])
    assert out.count("hold") == 1 and out[4] == "hold"           # fires at 1.0 s after the press (0.1 + 1.0), once only
    assert feed(d, [(1.6, False, False), (1.7, True, False)]) == ["", ""]    # a fresh single press is just a press


def test_ctrl_esc_is_immediate():
    d = EscDetector()
    assert feed(d, [(0, False, False), (0.1, True, True)])[1] == "ctrl-esc"


def test_esc_already_held_at_start_is_ignored_until_released():
    d = EscDetector()
    out = feed(d, [(0, True, False), (0.5, True, False), (2.0, True, False), (2.1, False, False), (2.2, True, False)])
    assert out == ["", "", "", "", ""]


def test_guide_chords():
    c = GuideChord()
    assert c.button("b", True) is None                 # B alone = the normal "back"
    assert c.button("guide", True) == "swallow"
    assert c.button("b", True) == "quitapp"
    assert c.button("x", True) == "record"
    assert c.button("guide", False) == "swallow"
    assert c.button("b", True) is None


# ------------------------------------------------------------------ real X server
@pytest.fixture
def xvfb(monkeypatch):
    for n in range(90, 120):
        if not os.path.exists(f"/tmp/.X11-unix/X{n}"):
            break
    disp = f":{n}"
    p = subprocess.Popen(["Xvfb", disp, "-screen", "0", "640x480x24"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        if os.path.exists(f"/tmp/.X11-unix/X{n}"):
            break
        time.sleep(0.1)
    time.sleep(0.3)
    monkeypatch.setenv("DISPLAY", disp)
    yield disp
    p.terminate()
    p.wait(5)


def xdo(*args):
    subprocess.run(["xdotool", *args], check=True, env=dict(os.environ))


def tap(key="Escape", hold=0.07):
    """A key press the way a person does it (a few dozen ms down), not xdotool's 12 ms blip."""
    xdo("keydown", key)
    time.sleep(hold)
    xdo("keyup", key)


def sleeper():
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)


def stop(p):
    try:
        p.kill()
    except OSError:
        pass
    p.wait()


@X
def test_x11_keys_see_real_key_events(xvfb):
    k = exitwatch.X11Keys()
    assert k.available, k.why
    esc = k.keycode(exitwatch.XK_ESCAPE)
    assert not k.is_down(esc)
    xdo("keydown", "Escape")
    time.sleep(0.1)
    assert k.is_down(esc) and k.state()[0]
    xdo("keyup", "Escape")
    time.sleep(0.1)
    assert not k.is_down(esc)
    k.close()


@X
@pytest.mark.parametrize("gesture", ["double", "hold", "ctrl"])
def test_gestures_close_the_app(xvfb, gesture):
    p = sleeper()
    w = exitwatch.Watch(p, grace=2).start()
    try:
        assert w.keyboard_ok
        time.sleep(0.3)
        if gesture == "double":
            tap()
            time.sleep(0.15)
            tap()
        elif gesture == "hold":
            xdo("keydown", "Escape")
            time.sleep(1.4)
            xdo("keyup", "Escape")
        else:
            xdo("key", "ctrl+Escape")
        assert p.wait(6) is not None                          # the "browser" was asked to close
        assert w.triggered and w.reason in ("double", "hold", "ctrl-esc")
    finally:
        w.stop()
        stop(p)


@X
def test_single_esc_leaves_the_app_alone(xvfb):
    p = sleeper()
    w = exitwatch.Watch(p, grace=2).start()
    try:
        time.sleep(0.3)
        tap()
        time.sleep(1.0)
        tap()                                                  # a second press, but far too late
        time.sleep(0.6)
        assert p.poll() is None and not w.triggered
    finally:
        w.stop()
        stop(p)


def test_gamepad_request_quit_closes_the_watched_app():
    p = sleeper()
    k = exitwatch.X11Keys(display="")                          # no keyboard source at all: only the gamepad works
    w = exitwatch.Watch(p, keys=k, grace=2).start()
    try:
        assert not w.keyboard_ok
        assert exitwatch.request_quit("gamepad") is True
        assert p.wait(6) is not None and w.reason == "gamepad"
    finally:
        w.stop()
        stop(p)
    assert exitwatch.request_quit("gamepad") is False         # nothing is being watched any more


def test_terminate_kills_a_process_that_ignores_sigterm():
    p = subprocess.Popen([sys.executable, "-c", "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"],
                         start_new_session=True)
    time.sleep(0.4)
    exitwatch.terminate_app(p, grace=0.6)
    assert p.wait(5) is not None


def test_flatpak_apps_are_asked_to_stop_with_flatpak_kill():
    p = sleeper()
    calls = []
    exitwatch.terminate_app(p, "com.google.Chrome", grace=1, run=lambda cmd, **k: calls.append(cmd))
    assert calls == [["flatpak", "kill", "com.google.Chrome"]]
    stop(p)


@X
def test_f9_hotkey_fires_once_per_press(xvfb):
    hits = []
    hk = exitwatch.HotkeyWatch(lambda: hits.append(1)).start()
    try:
        assert hk.available
        time.sleep(0.2)
        tap("F9")
        time.sleep(0.2)
        tap("F9")
        time.sleep(0.3)
        assert len(hits) == 2
    finally:
        hk.stop()


# ------------------------------------------------------------------ the real launch path with a pretend browser
@X
def test_web_app_launch_returns_cleanly_when_esc_is_pressed_twice(xvfb, tmp_path, monkeypatch):
    from atarilauncher import config, library
    monkeypatch.setenv("ATARI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("HOME", str(tmp_path))
    browser = tmp_path / "fakebrowser"
    browser.write_text("#!/bin/sh\nexec sleep 60\n")
    browser.chmod(browser.stat().st_mode | stat.S_IEXEC)
    cfg = config.default_config()
    cfg.emulator_commands["browser"] = str(browser)
    game = [g for g in library.build_library(cfg, home=tmp_path).games if g.gid == "web:netflix"][0]
    started = []

    taps = []

    def press():
        time.sleep(1.0)
        tap()
        taps.append(1)
        time.sleep(0.12)
        tap()
        taps.append(2)

    import threading
    th = threading.Thread(target=press, daemon=True)
    th.start()
    t0 = time.time()
    secs, err = launcher.run_game(cfg, game, on_started=lambda: started.append(1))
    th.join(10)
    assert taps == [1, 2]                                                            # one Esc alone did not close it
    assert started == [1] and err == "" and secs > 0 and time.time() - t0 < 20       # no "closed right away" error either


def test_hint_text_mentions_esc_twice_and_can_be_switched_off(monkeypatch):
    from atarilauncher import config
    from atarilauncher.library import Game
    cfg = config.default_config()
    g = Game(gid="web:netflix", title="Netflix", platform="streaming", platform_name="Streaming")
    assert "Esc twice" in launcher.controls_hint(cfg, g) and "Guide + press B" in launcher.controls_hint(cfg, g)
    cfg.esc_exit = False
    assert launcher.controls_hint(cfg, g) == ""
