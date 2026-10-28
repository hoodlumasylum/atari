"""CodeAque-only mode: CodeAque must outlive every app it starts, take the screen back when one closes, and never quit by accident."""
import os
import stat
import time

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication  # noqa: E402

from atarilauncher import backend as be  # noqa: E402
from atarilauncher import config, kiosk, launcher  # noqa: E402
from atarilauncher.store import Store  # noqa: E402


def make_backend(tmp_path, monkeypatch, command):
    monkeypatch.setenv("ATARI_DATA_DIR", str(tmp_path / "data"))
    app = QCoreApplication.instance() or QCoreApplication([])
    roms = tmp_path / "roms"
    roms.mkdir()
    (roms / "Game (USA).gba").write_bytes(b"x")
    emu = tmp_path / "emu.sh"
    emu.write_text("#!/bin/sh\n" + command)
    emu.chmod(emu.stat().st_mode | stat.S_IEXEC)
    cfg = config.default_config()
    cfg.steam_enabled = False
    cfg.systems["gba"].roms = [str(roms)]
    cfg.systems["gba"].command = f"{emu} {{rom}}"
    cfg.first_run = False
    b = be.Backend(cfg=cfg, store=Store(tmp_path / "s.json"), enable_gamepad=False)
    b.setFilter("all")
    return app, b


def play_and_wait(app, b, seconds=15):
    b.launch(0)
    end = time.time() + seconds
    while (b.running or not b.toast) and time.time() < end:
        app.processEvents()
        time.sleep(0.05)
    for _ in range(10):
        app.processEvents()
        time.sleep(0.02)


@pytest.mark.parametrize("what", ["kill -9 0", "kill -TERM 0", "kill -HUP 0", "kill -9 $PPID"][:3])
def test_an_app_that_kills_its_whole_process_group_cannot_take_code_down(tmp_path, monkeypatch, what):
    """The emulator is started in its own session, so signalling 'its group' only reaches itself. If it shared CodeAque's group, this
    test process (standing in for CodeAque) would be killed and the CodeAque-only session would have ended."""
    app, b = make_backend(tmp_path, monkeypatch, f"sleep 0.4\n{what}\n")
    pgid_before = os.getpgrp()
    play_and_wait(app, b)
    assert not b.running and os.getpgrp() == pgid_before                          # we are still here, in our own group
    assert b.toast                                                                # CodeAque shows what happened (back in the library)


def test_every_launch_path_starts_the_app_in_its_own_session(monkeypatch, tmp_path):
    seen = []

    class P:
        pid = 1
        returncode = 0

        def poll(self):
            return 0

        def wait(self, *a, **k):
            return 0
    real = launcher.subprocess

    import types
    ns = types.SimpleNamespace(**{k: getattr(real, k) for k in dir(real) if not k.startswith("__")})
    ns.Popen = lambda cmd, **kw: (seen.append(kw.get("start_new_session")) or P())
    monkeypatch.setattr(launcher, "subprocess", ns)
    monkeypatch.setenv("ATARI_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(launcher, "_check_executable", lambda *a, **k: None)
    cfg = config.default_config()
    cfg.steam_enabled = False
    # an emulator ROM, a PC app, a Flatpak free game and a Windows game
    from atarilauncher import apps, library
    rom = tmp_path / "g.gba"
    rom.write_bytes(b"x")
    cfg.systems["gba"].roms = [str(tmp_path)]
    cfg.systems["gba"].command = "emu {rom}"
    games = {g.gid: g for g in library.build_library(cfg).games}
    rom_game = next(g for g in games.values() if g.rom_path == str(rom))
    launcher.run_game(cfg, rom_game, lambda: None)
    monkeypatch.setattr(apps, "app_command", lambda c, a, *x, **k: (["heroic"], "native"))
    launcher.run_game(cfg, games["app:heroic"], lambda: None)
    assert seen and all(v is True for v in seen), seen


def test_in_code_only_mode_quit_is_a_restart_and_the_window_retakes_the_whole_screen(tmp_path, monkeypatch):
    monkeypatch.setenv("ATARI_KIOSK", "1")
    app, b = make_backend(tmp_path, monkeypatch, "exit 0\n")
    assert b.kioskSession is True
    calls = []

    class Win:
        def showFullScreen(self): calls.append("full")
        def showNormal(self): calls.append("normal")
        def showMinimized(self): calls.append("min")
        def raise_(self): calls.append("raise")
        def requestActivate(self): calls.append("activate")
        def isActive(self): return True
    b._window = Win()
    b._minimized_for_game = True
    b.cfg.fullscreen = False                                   # even a windowed CodeAque goes full screen again in CodeAque-only mode
    b._restore_window()
    assert calls[:3] == ["full", "raise", "activate"]
    calls.clear()
    b._restore_window()                                        # not minimised: still re-asserts full screen
    assert calls[:3] == ["full", "raise", "activate"]
    rows = {r["id"]: r["title"] for r in b.pageRows("power")}                  # the Power page: Restart CodeAque, and no Quit in CodeAque-only mode
    assert rows["power_restartcode"] == "Restart CodeAque" and "power_quitcode" not in rows


def test_outside_code_only_mode_nothing_changes(tmp_path, monkeypatch):
    monkeypatch.delenv("ATARI_KIOSK", raising=False)
    app, b = make_backend(tmp_path, monkeypatch, "exit 0\n")
    assert b.kioskSession is False
    calls = []

    class Win:
        def showFullScreen(self): calls.append("full")
        def showNormal(self): calls.append("normal")
        def raise_(self): pass
        def requestActivate(self): pass
        def isActive(self): return True
    b._window = Win()
    b.cfg.fullscreen = False
    b._minimized_for_game = True
    b._restore_window()
    assert calls == ["normal"]
    calls.clear()
    b._restore_window()
    assert calls == []
