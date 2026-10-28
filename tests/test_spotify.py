"""Spotify tiles (desktop app + web player) that keep playing behind CodeAque, and the top bar's playerctl / MPRIS music buttons."""
import subprocess
import time

import pytest

from atarilauncher import apps, appinstall, icons, launcher, library, media, webapps
from atarilauncher.config import default_config

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt  # noqa: E402

from atarilauncher import backend as be  # noqa: E402
from tests.test_features_ui import conf  # noqa: E402
from tests.test_studio_click import click_text, texts  # noqa: E402
from tests.test_ui_keys import Ui, app, pump  # noqa: E402,F401
from tests.test_wifi import say, wait_until  # noqa: E402


def only(*names):
    return lambda exe: f"/usr/bin/{exe}" if exe in names else None


class Run:
    """A pretend playerctl."""

    def __init__(self, out="Playing\tspotify\tDaft Punk\tAround the World", rc=0):
        self.out, self.rc, self.calls = out, rc, []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        return subprocess.CompletedProcess(cmd, self.rc, self.out, "")


# ------------------------------------------------------------------ playerctl / MPRIS
def test_parse_now_playing():
    t = media.parse("Playing\tspotify\tDaft Punk\tAround the World")
    assert t.playing and t.player == "spotify" and t.text == "Daft Punk - Around the World"
    assert not media.parse("Paused\tspotify\tA\tB").playing and media.parse("Paused\tspotify\tA\tB") is not None
    assert media.parse("Stopped\tspotify\t\t") is None and media.parse("") is None
    assert media.parse("Playing\tchromium\t\tOnly a title").text == "Only a title"
    assert media.parse("Playing\tvlc\t\t").text == "Vlc"


def test_now_playing_asks_spotify_first_and_is_quiet_without_playerctl_or_player():
    run = Run()
    t = media.now_playing(only("playerctl"), run)
    assert t.title == "Around the World"
    assert run.calls[0][:3] == ["playerctl", "-p", "spotify,%any"] and "metadata" in run.calls[0]
    assert media.now_playing(only(), run) is None and len(run.calls) == 1             # no playerctl: no call at all
    assert media.now_playing(only("playerctl"), Run("No players found", rc=1)) is None

    def boom(*a, **k):
        raise subprocess.TimeoutExpired("playerctl", 2)
    assert media.now_playing(only("playerctl"), boom) is None


def test_send_runs_only_the_three_known_actions():
    run = Run()
    assert media.send("play-pause", only("playerctl"), run) and run.calls[0][-1] == "play-pause"
    assert media.send("next", only("playerctl"), run) and media.send("previous", only("playerctl"), run)
    assert not media.send("rm -rf", only("playerctl"), run) and len(run.calls) == 3
    assert not media.send("next", only(), run)
    assert not media.send("next", only("playerctl"), Run(rc=1))


# ------------------------------------------------------------------ tiles
def test_spotify_tiles_exist_keep_playing_and_ship_no_logo():
    a = apps.BY_ID["spotify"]
    assert a.flatpak == "com.spotify.Client" and a.group == "streaming" and a.background
    assert appinstall.TARGETS["spotify"] is not None and "playerctl" in appinstall.TARGETS
    w = webapps.BY_ID["spotify"]
    assert w.background and w.drm and w.url == "https://open.spotify.com" and not w.browse
    for gid in ("app:spotify", "web:spotify"):
        assert icons.spec_for(gid) is not None                                          # icon fetched at runtime
    res = library.build_library(default_config())
    g = {x.gid: x for x in res.games}
    assert g["app:spotify"].platform == "streaming" and g["web:spotify"].platform == "streaming"
    from pathlib import Path
    shipped = [p.name.lower() for p in (Path(media.__file__).parent / "assets").rglob("*") if p.is_file()]
    assert not any("spotify" in n for n in shipped)


# ------------------------------------------------------------------ running in the background
def shim_popen(monkeypatch, factory):
    """Replace subprocess.Popen only inside launcher.py (a copy of the module), never globally."""
    import types
    ns = types.SimpleNamespace(**{k: getattr(subprocess, k) for k in dir(subprocess) if not k.startswith("__")})
    ns.Popen = factory
    monkeypatch.setattr(launcher, "subprocess", ns)


class FakeProc:
    def __init__(self, rc=None):
        self.rc, self.pid = rc, 4242

    def poll(self):
        return self.rc


def test_background_app_returns_to_code_on_the_gesture_and_is_not_killed(monkeypatch):
    killed = []
    monkeypatch.setattr(launcher.exitwatch, "terminate_app", lambda *a, **k: killed.append(a))
    proc = FakeProc()
    shim_popen(monkeypatch, lambda *a, **k: proc)
    monkeypatch.setattr(launcher.exitwatch, "enabled", lambda cfg: True)

    class FakeWatch:
        def __init__(self, p, fid, term=None, grace=0.0, **k):
            self.term, self.p, self.triggered, self.reason, self.keyboard_ok = term, p, False, "", True
            self.keys = type("K", (), {"why": ""})()
            FakeWatch.last = self

        def start(self):
            import threading
            def later():
                time.sleep(0.4)
                self.triggered = True
                self.term(self.p, "", 0)             # what the real Watch does on Esc, Esc
            threading.Thread(target=later, daemon=True).start()

        def stop(self):
            pass
    monkeypatch.setattr(launcher.exitwatch, "Watch", FakeWatch)
    monkeypatch.setattr(launcher.exitwatch, "notify", lambda *a, **k: None)
    started = []
    elapsed, msg = launcher._run_background(default_config(), ["spotify"], "Spotify", lambda: started.append(1), subprocess.DEVNULL)
    assert started and "keeps playing" in msg and msg.startswith(launcher.INFO) and not killed
    assert proc.poll() is None                                                        # the app is still running
    assert FakeWatch.last.term is launcher._leave_running


def test_a_failed_start_or_a_closed_window_ends_the_wait(monkeypatch):
    monkeypatch.setattr(launcher.exitwatch, "enabled", lambda cfg: False)
    shim_popen(monkeypatch, lambda *a, **k: FakeProc(rc=3))
    elapsed, msg = launcher._run_background(default_config(), ["spotify"], "Spotify", lambda: None, subprocess.DEVNULL)
    assert "closed right away" in msg
    a = launcher._Alive(FakeProc(rc=0), time.time())
    assert a.poll() is None                                                           # handed over to an open copy: still "there"
    a2 = launcher._Alive(FakeProc(rc=0), time.time() - 60)
    assert a2.poll() == 0                                                             # closed after a long run: over
    assert launcher._Alive(FakeProc(rc=None)).poll() is None and launcher._Alive(None).poll() is None


def test_web_and_app_tiles_take_the_background_path(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(launcher, "_run_background", lambda cfg, cmd, name, cb, fh, **k: calls.append((cmd, name)) or (0.0, ""))
    monkeypatch.setattr(launcher, "_check_executable", lambda *a, **k: None)
    monkeypatch.setattr(webapps, "build_command", lambda cfg, wa, *a, **k: (["chrome", "--app=" + wa.url], "Google Chrome"))
    monkeypatch.setattr(apps, "app_command", lambda cfg, app, *a, **k: (["flatpak", "run", app.flatpak], "flatpak"))
    monkeypatch.setenv("ATARI_DATA_DIR", str(tmp_path))
    games = {g.gid: g for g in library.build_library(default_config()).games}
    launcher.run_game(default_config(), games["web:spotify"], lambda: None)
    launcher.run_game(default_config(), games["app:spotify"], lambda: None)
    assert [c[1] for c in calls] == ["Google Chrome", "Spotify"] and calls[1][0] == ["flatpak", "run", "com.spotify.Client"]


# ------------------------------------------------------------------ the top bar
def make(app, tmp_path, monkeypatch, track, sent):
    conf(tmp_path, "[steam]\nenabled = false\n")
    monkeypatch.delenv("ATARI_NO_MEDIA", raising=False)
    state = {"t": track}

    def now():
        return state["t"]

    def send(action):
        sent.append(action)
        if action == "play-pause" and state["t"] is not None:
            t = state["t"]
            state["t"] = media.Track("Paused" if t.playing else "Playing", t.player, t.artist, t.title)
        return True
    monkeypatch.setattr(be.Backend, "_media_fns", (now, send), raising=False)
    monkeypatch.setattr(be.Backend, "_media_poll", lambda self: self.media.refresh(), raising=True)
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    return ui, state


def test_top_bar_shows_the_music_control_only_while_something_plays_and_the_buttons_work(app, tmp_path, monkeypatch):
    sent = []
    ui, state = make(app, tmp_path, monkeypatch, media.Track("Playing", "spotify", "Daft Punk", "Around the World"), sent)
    try:
        assert wait_until(app, lambda: ui.backend.media.active)
        shown = say(ui)
        assert "Daft Punk - Around the World" in shown and "\u23F8" in shown            # pause symbol while playing
        click_text(ui, "\u23F8")
        assert wait_until(app, lambda: not ui.backend.media.playing) and sent == ["play-pause"]
        assert wait_until(app, lambda: "\u25B6" in say(ui))                             # now shows play
        click_text(ui, "\u23ED")
        assert wait_until(app, lambda: sent == ["play-pause", "next"])
        click_text(ui, "\u23EE")
        assert wait_until(app, lambda: sent[-1] == "previous")
        state["t"] = None                                                                # Spotify closed
        ui.backend.media.refresh()
        assert wait_until(app, lambda: not ui.backend.media.active)
        assert "Around the World" not in say(ui)
    finally:
        ui.close()


def test_controller_and_keyboard_reach_the_music_buttons_from_the_top_bar(app, tmp_path, monkeypatch):
    sent = []
    ui, _state = make(app, tmp_path, monkeypatch, media.Track("Playing", "spotify", "A", "B"), sent)
    try:
        assert wait_until(app, lambda: ui.backend.media.active)
        ui.win.setProperty("area", "tabs")
        ui.win.setProperty("tabFocus", 7)
        pump(app, 50)
        ui.key(Qt.Key_Right)                       # 8 previous
        ui.key(Qt.Key_Right)                       # 9 play / pause
        assert ui.win.property("tabFocus") == 9
        ui.key(Qt.Key_Return)
        assert wait_until(app, lambda: sent == ["play-pause"])
        ui.key(Qt.Key_Right)
        ui.key(Qt.Key_Right)                       # stops at 10 (next)
        assert ui.win.property("tabFocus") == 10
    finally:
        ui.close()


def test_without_a_player_the_bar_has_no_music_buttons_and_focus_stops_at_wifi(app, tmp_path, monkeypatch):
    ui, _s = make(app, tmp_path, monkeypatch, None, [])
    try:
        pump(app, 200)
        assert not ui.backend.media.active
        ui.win.setProperty("area", "tabs")
        ui.win.setProperty("tabFocus", 7)
        ui.key(Qt.Key_Right)
        assert ui.win.property("tabFocus") == 7
    finally:
        ui.close()
