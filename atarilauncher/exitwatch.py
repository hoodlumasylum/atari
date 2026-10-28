"""Esc-to-return for full-screen web apps (Netflix, YouTube, Instagram, ... and Kodi).

A browser window in full screen owns the keyboard, so Atari cannot see any key while a web app runs. This module is a
small watcher that Atari starts next to the browser. It never grabs or swallows a key (a single Esc still leaves video
full screen exactly as the page expects); it only *looks* at which keys are down and quits the app on a deliberate gesture:

    Esc, Esc          two presses within 0.6 s           (the first one still exits video full screen as normal)
    hold Esc          for 1 second
    Ctrl + Esc        at once
    gamepad Guide + B at once (the controller helper reports it, see gamepad_helper.py)

Quitting = ask the browser to close (SIGTERM to its process group; `flatpak kill` for Flatpak apps; SIGKILL after a few
seconds if it ignores that). When the process is gone, launcher.py returns, and Atari raises and focuses its own window.

How the keys are seen: on X11 (Linux Mint's Cinnamon, the default) `XQueryKeymap` from libX11, loaded with ctypes, says
which keys are physically down. It is polled ~60 times a second. It needs no extra Python package, no root, no
/dev/input access and no key grab, and it works whichever window has the focus. On a pure Wayland session there is no
such call for other programs' keys, so only the gamepad chord works there (and Atari is still raised when the browser
closes); Mint's Cinnamon session is X11, and an XWayland-only display is detected and reported as "unavailable".

Why not a browser extension? Google Chrome 137+ ignores --load-extension (removed in branded builds, and the
DisableLoadExtensionCommandLineSwitch escape hatch went away in Chrome 142), a content script never sees the Esc that
exits video full screen, window.close() is not allowed, and it would not help Firefox, Kodi or the gamepad.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import signal
import subprocess
import threading
import time
from typing import Callable

DOUBLE_WINDOW = 0.6      # seconds between two Esc presses
HOLD_SECONDS = 1.0       # Esc held down this long
POLL = 0.008             # key state polling interval
GRACE = 4.0              # seconds a browser gets to close before SIGKILL

HINT = "Press Esc twice (or hold Esc for 1 second) to return to Atari"
HINT_PAD = "Gamepad: hold Guide + press B."
HINT_SHORT = "Esc, Esc  =  back to Atari"

XK_ESCAPE, XK_CONTROL_L, XK_CONTROL_R = 0xFF1B, 0xFFE3, 0xFFE4


class EscDetector:
    """Pure state machine: feed it the key state every poll, it says when the gesture happened.

    feed(now, esc, ctrl) -> '' | 'double' | 'hold' | 'ctrl-esc'. An Esc already held when watching starts is ignored until
    it is released. After a trigger, nothing else fires until Esc is released (so a held key cannot fire twice)."""

    def __init__(self, double_window: float = DOUBLE_WINDOW, hold: float = HOLD_SECONDS):
        self.double_window, self.hold = double_window, hold
        self._prev_esc = None            # None = no sample yet
        self._down_at = 0.0
        self._last_press = -1e9
        self._armed = True
        self._ignore_until_release = False

    def feed(self, now: float, esc: bool, ctrl: bool = False) -> str:
        if self._prev_esc is None:
            self._prev_esc = esc
            self._ignore_until_release = esc
            self._down_at = now
            return ""
        out = ""
        if esc and not self._prev_esc:                       # pressed just now
            self._down_at = now
            self._armed = True
            self._ignore_until_release = False
            if ctrl:
                out = "ctrl-esc"
            elif now - self._last_press <= self.double_window:
                out = "double"
            self._last_press = now
        elif esc and self._prev_esc and self._armed and not self._ignore_until_release:
            if now - self._down_at >= self.hold:
                out = "hold"
        elif not esc:
            self._ignore_until_release = False
        self._prev_esc = esc
        if out:
            self._armed = False
            self._last_press = -1e9
        return out


class X11Keys:
    """Which keys are down, straight from the X server (XQueryKeymap). `available` is False without X11."""

    def __init__(self, display: str | None = None):
        self.available = False
        self.why = ""
        self._xlib = None
        self._dpy = None
        name = display if display is not None else os.environ.get("DISPLAY", "")
        if not name:
            self.why = "no X11 display (Wayland-only session?)"
            return
        lib = ctypes.util.find_library("X11")
        if not lib:
            self.why = "libX11 not found"
            return
        try:
            x = ctypes.CDLL(lib)
            x.XOpenDisplay.restype = ctypes.c_void_p
            x.XOpenDisplay.argtypes = [ctypes.c_char_p]
            x.XKeysymToKeycode.restype = ctypes.c_ubyte
            x.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            x.XQueryKeymap.argtypes = [ctypes.c_void_p, ctypes.c_char * 32]
            x.XCloseDisplay.argtypes = [ctypes.c_void_p]
            dpy = x.XOpenDisplay(name.encode())
        except (OSError, AttributeError) as exc:
            self.why = f"libX11 unusable: {exc}"
            return
        if not dpy:
            self.why = f"cannot open display {name}"
            return
        self._xlib, self._dpy = x, dpy
        self._esc = x.XKeysymToKeycode(dpy, XK_ESCAPE)
        self._ctrl = [c for c in (x.XKeysymToKeycode(dpy, XK_CONTROL_L), x.XKeysymToKeycode(dpy, XK_CONTROL_R)) if c]
        self.available = bool(self._esc)
        if not self.available:
            self.why = "this keyboard layout has no Escape key"

    def keycode(self, keysym: int) -> int:
        return int(self._xlib.XKeysymToKeycode(self._dpy, keysym)) if self.available else 0

    def is_down(self, keycode: int) -> bool:
        """Is this key down right now (any window has the focus)? One XQueryKeymap round trip."""
        if not keycode or not self.available:
            return False
        buf = (ctypes.c_char * 32)()
        self._xlib.XQueryKeymap(self._dpy, buf)
        return bool(buf.raw[keycode >> 3] & (1 << (keycode & 7)))

    def state(self) -> tuple[bool, bool]:
        """(Esc down, Ctrl down)"""
        buf = (ctypes.c_char * 32)()
        self._xlib.XQueryKeymap(self._dpy, buf)
        raw = buf.raw
        def down(code: int) -> bool:
            return bool(raw[code >> 3] & (1 << (code & 7)))
        return down(self._esc), any(down(c) for c in self._ctrl)

    def close(self) -> None:
        if self._dpy:
            try:
                self._xlib.XCloseDisplay(self._dpy)
            except Exception:
                pass
            self._dpy = None
            self.available = False


# ---------------------------------------------------------------------------------- stopping the app

def terminate_app(proc: subprocess.Popen, flatpak_id: str = "", grace: float = GRACE,
                  run: Callable = subprocess.run) -> None:
    """Close the app politely, then forcefully. `proc` must have been started with start_new_session=True."""
    if flatpak_id:
        try:
            run(["flatpak", "kill", flatpak_id], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass
    _signal_group(proc, signal.SIGTERM)
    deadline = time.time() + grace
    while time.time() < deadline:
        if proc.poll() is not None:
            _signal_group(proc, signal.SIGTERM)     # stragglers (browser helper processes) of the same group
            return
        time.sleep(0.1)
    _signal_group(proc, signal.SIGKILL)


def _signal_group(proc: subprocess.Popen, sig: int) -> None:
    try:
        os.killpg(proc.pid, sig)                    # group id == pid because of start_new_session
        return
    except (ProcessLookupError, PermissionError):
        pass
    except OSError:
        pass
    try:
        if proc.poll() is None:
            proc.send_signal(sig)
    except OSError:
        pass


# ---------------------------------------------------------------------------------- the watcher

_active: "Watch | None" = None
_lock = threading.Lock()


def request_quit(reason: str = "gamepad") -> bool:
    """Quit the web app being watched right now (used by the gamepad chord). False if none is running."""
    with _lock:
        w = _active
    if w is None:
        return False
    w.trigger(reason)
    return True


class Watch:
    """Watches the keys while `proc` lives and closes it on the quit gesture. Use as a context manager or start()/stop()."""

    def __init__(self, proc: subprocess.Popen, flatpak_id: str = "", keys: X11Keys | None = None,
                 detector: EscDetector | None = None, grace: float = GRACE, on_trigger: Callable[[str], None] | None = None,
                 term: Callable = terminate_app, guard: Callable[[], bool] | None = None):
        self.proc, self.flatpak_id, self.grace = proc, flatpak_id, grace
        self.guard = guard               # returns True while the keyboard gesture must be ignored (a game is running)
        self.keys = keys if keys is not None else X11Keys()
        self.detector = detector or EscDetector()
        self.on_trigger = on_trigger
        self._term = term
        self.reason = ""                 # why the app was closed ('' = it closed by itself)
        self._stop = threading.Event()
        self._fired = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def keyboard_ok(self) -> bool:
        return self.keys.available

    @property
    def triggered(self) -> bool:
        return self._fired.is_set()

    def trigger(self, reason: str) -> None:
        if self._fired.is_set() or self.proc.poll() is not None:
            return
        self.reason = reason
        self._fired.set()
        if self.on_trigger:
            try:
                self.on_trigger(reason)
            except Exception:
                pass
        threading.Thread(target=self._term, args=(self.proc, self.flatpak_id, self.grace), daemon=True).start()

    def _loop(self) -> None:
        while not self._stop.is_set() and self.proc.poll() is None and not self._fired.is_set():
            if self.keys.available:
                try:
                    esc, ctrl = self.keys.state()
                except Exception:
                    self.keys.available = False
                    continue
                if self.guard is not None:
                    try:
                        if self.guard():
                            esc = ctrl = False       # a game is in front: its Esc key is its own
                    except Exception:
                        pass
                what = self.detector.feed(time.monotonic(), esc, ctrl)
                if what:
                    self.trigger(what)
                    break
            self._stop.wait(POLL)

    def start(self) -> "Watch":
        global _active
        with _lock:
            _active = self
        self._thread = threading.Thread(target=self._loop, name="atari-exitwatch", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        global _active
        self._stop.set()
        with _lock:
            if _active is self:
                _active = None
        if self._thread is not None:
            self._thread.join(1.0)
        self.keys.close()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()


XK_F9 = 0xFFC6


class HotkeyWatch:
    """A global hotkey (default F9) that works while a game or full-screen app has the focus, with the same
    no-grab XQueryKeymap method as the Esc watcher. Fires ``callback()`` once per key press (in a helper thread)."""

    def __init__(self, callback: Callable[[], None], keysym: int = XK_F9, keys: X11Keys | None = None):
        self.callback = callback
        self.keys = keys if keys is not None else X11Keys()
        self._code = self.keys.keycode(keysym) if self.keys.available else 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.available = bool(self._code)

    def start(self) -> "HotkeyWatch":
        if self.available:
            self._thread = threading.Thread(target=self._loop, name="atari-hotkey", daemon=True)
            self._thread.start()
        return self

    def _loop(self) -> None:
        was = self.keys.is_down(self._code)            # a key already held when we start is not a press
        while not self._stop.wait(0.03):
            try:
                down = self.keys.is_down(self._code)
            except Exception:
                return
            if down and not was:
                try:
                    self.callback()
                except Exception:
                    pass
            was = down

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(1.0)
        self.keys.close()


def enabled(cfg=None) -> bool:
    """On unless switched off in Settings (esc_exit) or by ATARI_NO_ESCEXIT=1."""
    if os.environ.get("ATARI_NO_ESCEXIT"):
        return False
    return bool(getattr(cfg, "esc_exit", True))


def notify(text: str) -> None:
    """Best effort desktop notification (shows in front of a full-screen window on many desktops)."""
    import shutil
    exe = shutil.which("notify-send")
    if not exe or os.environ.get("ATARI_NO_NOTIFY") or not os.environ.get("DISPLAY"):
        return
    try:
        subprocess.Popen([exe, "-a", "Atari", "-t", "6000", "Atari", text], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass
