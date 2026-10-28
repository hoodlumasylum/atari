"""The start-up intro.

Two kinds, both skippable with any key, a click or a controller button:
  * YOUR video: ~/.local/share/atari/intro.mp4 (or .webm / .mkv / .mov) plays full screen before the home screen.
    It is played by mpv, else ffplay, else VLC (CodeAque's own Qt build has no video library). No player, or a player that
    fails = the intro is skipped quietly and CodeAque starts normally. It can never keep CodeAque waiting longer than the clip
    itself (plus a second's grace).
  * the video that ships with CodeAque (assets/intro/code-intro.mp4, ~10 s, original artwork) when you have none of your own;
  * CodeAque's own short animation (original artwork + a soft original sound) when no video player is installed.
CodeAque contains no third-party logo; Settings > Choose intro video replaces the shipped one with your own file.
Pure Python (no Qt) so it can be tested; players and the clock are injectable."""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import paths

VIDEO_EXT = (".mp4", ".webm", ".mkv", ".mov")
BUNDLED_NAME = "code-intro.mp4"
DEFAULT_SECONDS = 3.6                   # length of CodeAque's own animation (matches assets/sfx/intro.wav)
GRACE = 1.5                             # seconds a clip may overrun its length before it is stopped
UNKNOWN_CAP = 60.0                      # longest we wait when the clip length cannot be read
FAIL_WINDOW = 1.0                       # a player that dies this fast with an error = playback failed -> skip quietly
PLAYERS = ("mpv", "ffplay", "cvlc", "vlc")


def custom_file(data_dir: Path | None = None) -> Path | None:
    """The intro video the user chose, if there is one."""
    base = data_dir or paths.data_dir()
    for ext in VIDEO_EXT:
        f = base / f"intro{ext}"
        try:
            if f.is_file() and f.stat().st_size > 0:
                return f
        except OSError:
            pass
    return None


def install(src: str | Path, data_dir: Path | None = None) -> tuple[bool, str]:
    """Copy a chosen video to <data>/intro.<ext> (replacing an older one). Never raises."""
    src = Path(src)
    base = data_dir or paths.data_dir()
    ext = src.suffix.lower()
    if ext not in VIDEO_EXT:
        return False, "That does not look like a video CodeAque can use. Choose an .mp4, .webm, .mkv or .mov file."
    try:
        if not src.is_file() or src.stat().st_size == 0:
            return False, "That file could not be read (or it is empty)."
        base.mkdir(parents=True, exist_ok=True)
        tmp = base / f"intro{ext}.part"
        shutil.copyfile(src, tmp)
        for e in VIDEO_EXT:                                 # only one intro at a time
            if e != ext:
                try:
                    (base / f"intro{e}").unlink()
                except OSError:
                    pass
        os.replace(tmp, base / f"intro{ext}")
    except OSError as exc:
        return False, f"Could not copy the video: {exc.strerror or exc}"
    return True, f"Intro video set: {src.name}. It plays when CodeAque starts."


def remove(data_dir: Path | None = None) -> int:
    base = data_dir or paths.data_dir()
    n = 0
    for e in VIDEO_EXT:
        try:
            (base / f"intro{e}").unlink()
            n += 1
        except OSError:
            pass
    return n


# ------------------------------------------------------------------ what should play
@dataclass
class Plan:
    mode: str = ""             # "" (nothing) | "custom" (your video) | "builtin" (the video shipped with CodeAque) | "default" (CodeAque's own animation, no player needed)
    file: Path | None = None


def bundled_file() -> Path | None:
    """The intro video that ships with CodeAque (original artwork chosen by the project owner)."""
    f = Path(__file__).resolve().parent / "assets" / "intro" / BUNDLED_NAME
    try:
        return f if f.is_file() and f.stat().st_size > 0 else None
    except OSError:
        return None


def default_plan(which: Callable = shutil.which) -> Plan:
    """No video of your own: the bundled video if a player is installed, else CodeAque's own short animation."""
    b = bundled_file()
    if b is not None and find_player(which)[1]:
        return Plan("builtin", b)
    return Plan("default")


def plan(cfg, data_dir: Path | None = None, env: dict | None = None, which: Callable = shutil.which) -> Plan:
    env = env if env is not None else os.environ
    if env.get("ATARI_NO_INTRO"):
        return Plan()
    f = custom_file(data_dir)
    if f is not None and getattr(cfg, "intro_enabled", True):
        return Plan("custom", f)
    if f is None and getattr(cfg, "intro_default", True):
        return default_plan(which)
    return Plan()


# ------------------------------------------------------------------ players
def find_player(which: Callable = shutil.which) -> tuple[str, str]:
    """(kind, path) of the first video player installed, or ('', '')."""
    for kind in PLAYERS:
        p = which(kind)
        if p:
            return kind, p
    return "", ""


INPUT_CONF = "\n".join(f"{k} quit" for k in (
    "ESC", "ENTER", "KP_ENTER", "SPACE", "ANY_UNICODE", "BS", "TAB", "UP", "DOWN", "LEFT", "RIGHT",
    "MBTN_LEFT", "MBTN_RIGHT", "MBTN_MID", "q")) + "\n"


VOLUME = 85                 # percent: the clip's own peak is -0.7 dB, so a little below full is loud enough without clipping the speakers


def player_command(kind: str, exe: str, video: str | Path, muted: bool, input_conf: str | Path | None = None) -> list[str]:
    """The command line that plays `video` full screen, once, then quits. Sound off = no audio at all; sound on = unmuted at VOLUME %."""
    video = str(video)
    if kind == "mpv":
        # full screen over everything (no border, on top), the picture FILLS the whole display (panscan=1: on a 16:9 screen exactly,
        # on other shapes the edges are cropped instead of leaving black bars), mouse pointer hidden, sound ON at VOLUME %
        cmd = [exe, "--no-config", "--fs", "--no-border", "--ontop", "--keepaspect", "--panscan=1.0", "--no-osc", "--osd-level=0",
               "--really-quiet", "--no-terminal", "--keep-open=no", "--cursor-autohide=always", "--force-window=immediate",
               "--no-input-default-bindings"]
        if input_conf:
            cmd.append(f"--input-conf={input_conf}")
        cmd.append("--no-audio" if muted else f"--volume={VOLUME}")
        if not muted:
            cmd += ["--mute=no", "--volume-max=100"]
        return cmd + ["--", video]
    if kind == "ffplay":
        cmd = [exe, "-fs", "-autoexit", "-loglevel", "quiet", "-noborder"]
        cmd += ["-an"] if muted else ["-volume", str(VOLUME)]
        return cmd + [video]
    # VLC
    cmd = [exe, "--fullscreen", "--no-video-deco", "--video-on-top", "--mouse-hide-timeout=1", "--play-and-exit", "--no-osd",
           "--no-video-title-show", "--quiet"]
    if muted:
        cmd.append("--no-audio")
    return cmd + [video, "vlc://quit"]


def write_input_conf(data_dir: Path | None = None) -> str:
    f = (data_dir or paths.data_dir()) / "intro-input.conf"
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(INPUT_CONF)
        return str(f)
    except OSError:
        return ""


def probe_seconds(video: str | Path, which: Callable = shutil.which, run: Callable = subprocess.run) -> float | None:
    """Length of the clip in seconds (ffprobe), or None when it cannot be read."""
    probe = which("ffprobe")
    if not probe:
        return None
    try:
        res = run([probe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(video)],
                  capture_output=True, text=True, timeout=10)
        return float(res.stdout.strip().splitlines()[0])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def time_limit(seconds: float | None) -> float:
    return (seconds + GRACE) if seconds else UNKNOWN_CAP


# ------------------------------------------------------------------ playing
class Playback:
    """Runs the player, and ends it on: the clip finishing, any key (X11), skip(), the time limit, or a failure.
    `on_end(reason)` is called exactly once from a helper thread; reason is finished | skipped | timeout | failed."""

    def __init__(self, cmd: list[str], limit: float, on_end: Callable[[str], None], keys=None,
                 popen: Callable = subprocess.Popen, clock: Callable[[], float] = time.monotonic, poll: float = 0.03):
        self.cmd, self.limit, self.on_end = cmd, limit, on_end
        self.keys, self._popen, self._clock, self._poll = keys, popen, clock, poll
        self.reason = ""
        self.proc = None
        self._skip = threading.Event()
        self._thread: threading.Thread | None = None
        self.done = threading.Event()

    def start(self) -> "Playback":
        try:
            self.proc = self._popen(self.cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    start_new_session=True)
        except (OSError, ValueError):
            self._finish("failed")
            return self
        self._thread = threading.Thread(target=self._loop, name="atari-intro", daemon=True)
        self._thread.start()
        return self

    def skip(self) -> None:
        self._skip.set()

    @property
    def active(self) -> bool:
        return not self.done.is_set()

    def _loop(self) -> None:
        t0 = self._clock()
        if self.keys is not None and (isinstance(self.keys, type) or not hasattr(self.keys, "keymap")):
            self.keys = self.keys()                     # a factory: the X connection is opened on THIS thread
        baseline = self.keys.keymap() if self.keys is not None and getattr(self.keys, "available", False) else b""
        while True:
            rc = self.proc.poll()
            if rc is not None:
                self._finish("failed" if (rc != 0 and self._clock() - t0 < FAIL_WINDOW) else "finished")
                return
            if self._skip.is_set():
                self._finish("skipped")
                return
            if self.keys is not None and baseline and self._new_key(baseline):
                self._finish("skipped")
                return
            if self._clock() - t0 > self.limit:
                self._finish("timeout")
                return
            time.sleep(self._poll)

    def _new_key(self, baseline: bytes) -> bool:
        try:
            now = self.keys.keymap()
        except Exception:
            return False
        return any(n & ~b for n, b in zip(now, baseline))        # a key that was not down when the clip started

    def _stop_player(self) -> None:
        p = self.proc
        if p is None or p.poll() is not None:
            return
        for sig, wait in ((signal.SIGTERM, 1.0), (signal.SIGKILL, 1.0)):
            try:
                os.killpg(p.pid, sig)
            except OSError:
                try:
                    p.send_signal(sig)
                except OSError:
                    pass
            end = time.time() + wait
            while time.time() < end:
                if p.poll() is not None:
                    return
                time.sleep(0.02)

    def _finish(self, reason: str) -> None:
        if self.done.is_set():
            return
        self.reason = reason
        if reason in ("skipped", "timeout"):
            self._stop_player()
        self.done.set()
        try:
            self.on_end(reason)
        except Exception:
            pass

    def stop(self) -> None:
        self.skip()
        if self._thread is not None:
            self._thread.join(3.0)
