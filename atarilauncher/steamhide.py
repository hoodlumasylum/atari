"""Keeps a Steam that CodeAque started at boot (`steam -silent`) out of sight: for the first minutes, any Steam window that appears
(login check, update box, the main window, Big Picture) is minimised - or, without a window manager (some CodeAque-only sessions),
unmapped - and CodeAque is put back in front. X11 only (xdotool, or wmctrl); on Wayland nothing can move other apps' windows.
Steam's windows come back the normal way: the Steam tile (steam://open/...) shows them again. Never raises."""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Callable

STEAM_CLASSES = ("steam", "steamwebhelper")
WATCH_SECONDS = 120.0       # how long after the silent start Steam windows are hidden
SETTLED_SECONDS = 12.0      # no new Steam window for this long (and Steam is up) = finished loading


def x11() -> bool:
    return bool(os.environ.get("DISPLAY")) and os.environ.get("XDG_SESSION_TYPE", "x11") != "wayland"


def _run(cmd, runner=None) -> tuple[int, str]:
    try:
        p = (runner or subprocess.run)(cmd, capture_output=True, text=True, timeout=5)
        return p.returncode, p.stdout or ""
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def steam_windows(runner=None, which: Callable = shutil.which) -> list[str]:
    """Window ids (strings) of Steam's visible top-level windows."""
    ids: list[str] = []
    if which("xdotool"):
        for cls in STEAM_CLASSES:
            rc, out = _run(["xdotool", "search", "--onlyvisible", "--class", cls], runner)
            ids += [x.strip() for x in out.split() if x.strip().isdigit()]
    elif which("wmctrl"):
        rc, out = _run(["wmctrl", "-lx"], runner)
        for line in out.splitlines():
            parts = line.split(None, 3)
            if len(parts) >= 3 and any(c in parts[2].lower() for c in STEAM_CLASSES):
                ids.append(str(int(parts[0], 16)))
    seen: list[str] = []
    for i in ids:
        if i not in seen:
            seen.append(i)
    return seen


def has_window_manager(runner=None, which: Callable = shutil.which) -> bool:
    if which("wmctrl"):
        return _run(["wmctrl", "-m"], runner)[0] == 0
    return True       # cannot tell: assume one (minimise first)


def hide(wid: str, wm: bool, runner=None, which: Callable = shutil.which) -> bool:
    if which("xdotool"):
        if wm and _run(["xdotool", "windowminimize", wid], runner)[0] == 0:
            return True
        return _run(["xdotool", "windowunmap", wid], runner)[0] == 0
    if which("wmctrl"):
        return _run(["wmctrl", "-i", "-r", hex(int(wid)), "-b", "add,hidden"], runner)[0] == 0
    return False


class Watcher:
    """Call tick(now) about once a second after a silent Steam start. Returns (hidden window ids this tick, finished?)."""

    def __init__(self, started: float, runner=None, which: Callable = shutil.which, ui_ready: Callable[[], bool] | None = None,
                 watch: float = WATCH_SECONDS, settled: float = SETTLED_SECONDS):
        self.started, self.runner, self.which = started, runner, which
        self.ui_ready = ui_ready or (lambda: True)
        self.watch, self.settled = watch, settled
        self.last_hide = started
        self.hidden: set[str] = set()
        self.wm: bool | None = None
        self.usable = bool(which("xdotool") or which("wmctrl"))

    def tick(self, now: float) -> tuple[list[str], bool]:
        if not self.usable:
            return [], True
        if self.wm is None:
            self.wm = has_window_manager(self.runner, self.which)
        done: list[str] = []
        for wid in steam_windows(self.runner, self.which):
            if hide(wid, self.wm, self.runner, self.which):
                done.append(wid)
                self.hidden.add(wid)
        if done:
            self.last_hide = now
        finished = now - self.started >= self.watch or (now - self.last_hide >= self.settled and now - self.started >= self.settled
                                                        and self.ui_ready())
        return done, finished
