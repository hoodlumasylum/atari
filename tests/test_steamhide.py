"""0.5.1 (t450u): Steam at boot stays hidden - no Big Picture nudge, no Big Picture start-up mode, Steam windows hidden, CodeAque in front."""
import types

from atarilauncher import steamfix, steamhide
from tests.test_steamfix import reg, NO, YES


def test_silent_start_is_never_nudged_even_before_steam_appears():
    g = steamfix.Guard(nudge_at=(0.0, 1.0))
    g.silent_start(100.0)
    assert not g.tick(False, 100.5)          # Steam not visible yet: the old Guard reset 'handled' here
    assert not g.tick(True, 101.0) and not g.tick(True, 150.0)
    g2 = steamfix.Guard(nudge_at=(0.0,))
    assert g2.tick(True, 1.0)                 # a Steam CodeAque did NOT start is still nudged


def test_big_picture_start_mode_is_turned_off_for_hidden_start(tmp_path):
    p = reg(tmp_path, startup="1")
    assert steamfix.set_startup_normal(tmp_path, YES)[0] is False and '"1"' in p.read_text()     # Steam open: left alone
    ok, text = steamfix.set_startup_normal(tmp_path, NO)
    assert ok and '"StartupMode"\t\t"0"' in p.read_text() and '"language"' in p.read_text()
    assert steamfix.set_startup_normal(tmp_path, NO)[0] is False
    out = steamfix.apply(types.SimpleNamespace(steam_proton_default=False), tmp_path, NO, proton=False, bigpicture_start=False)
    assert "normally" in out[0]


class FakeX:
    def __init__(self, wins, wm=True):
        self.wins, self.wm, self.calls = list(wins), wm, []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        rc, out = 0, ""
        if cmd[:2] == ["xdotool", "search"]:
            out = "\n".join(self.wins) if cmd[-1] == "steam" else ""
        elif cmd[:2] == ["wmctrl", "-m"]:
            rc = 0 if self.wm else 1
        elif cmd[0] == "xdotool" and cmd[1] in ("windowminimize", "windowunmap"):
            if cmd[1] == "windowminimize" and not self.wm:
                rc = 1
            else:
                self.wins = [w for w in self.wins if w != cmd[2]]
        return types.SimpleNamespace(returncode=rc, stdout=out)


def which_all(x):
    return "/usr/bin/" + x


def test_watcher_minimises_steam_windows_and_finishes_when_settled():
    fx = FakeX(["111", "222"])
    w = steamhide.Watcher(0.0, runner=fx, which=which_all, ui_ready=lambda: True, watch=100, settled=5)
    hidden, done = w.tick(1.0)
    assert hidden == ["111", "222"] and not done
    assert ["xdotool", "windowminimize", "111"] in fx.calls
    assert w.tick(3.0) == ([], False)
    fx.wins.append("333")                     # Steam's main window maps late
    assert w.tick(4.0)[0] == ["333"]
    assert w.tick(9.5)[1] is True             # nothing new for 5 s and Steam is up


def test_without_a_window_manager_windows_are_unmapped():
    fx = FakeX(["7"], wm=False)
    w = steamhide.Watcher(0.0, runner=fx, which=which_all)
    assert w.tick(1.0)[0] == ["7"] and ["xdotool", "windowunmap", "7"] in fx.calls


def test_no_tools_means_nothing_to_do():
    w = steamhide.Watcher(0.0, which=lambda x: None)
    assert w.tick(1.0) == ([], True)


import os  # noqa: E402
import time  # noqa: E402

import pytest  # noqa: E402

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from tests.test_ui_keys import app, pump  # noqa: E402,F401
from tests.test_xemuconfig import make_ui  # noqa: E402


def test_autostart_marks_the_guard_and_brings_code_back(app, tmp_path, monkeypatch):
    from atarilauncher import steam
    ui = make_ui(app, tmp_path, monkeypatch, tmp_path / "home")
    try:
        b = ui.backend
        b._steam_guard = steamfix.Guard()
        monkeypatch.setattr(b, "_steam_installed", lambda: True)
        monkeypatch.setattr(steam, "steam_running", lambda *a, **k: False)
        monkeypatch.setattr(steam, "remembered_login", lambda *a, **k: True)
        spawned = []
        assert b._steam_autostart(spawn=spawned.append) == "started" and spawned[0][-1] == "-silent"
        assert b._steam_guard.quiet_until > time.monotonic() + 60
        raised = []
        monkeypatch.setattr(b, "_raise_window", lambda: raised.append(1))
        fx = FakeX(["5"])
        w = steamhide.Watcher(time.monotonic(), runner=fx, which=which_all, settled=0.2, watch=5)
        b._start_steam_hider(watcher=w, sleep=lambda s: time.sleep(0.05))
        t = time.time()
        while time.time() - t < 3 and len(raised) < 2:
            pump(app, 50)
        assert len(raised) >= 2 and "5" in w.hidden
    finally:
        ui.close()
