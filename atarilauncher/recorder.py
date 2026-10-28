"""Screen recorder: ffmpeg in a separate background process, so it keeps recording while an emulator, a game or a
full-screen web app has the focus and Atari's own window is hidden.

    X11 (Linux Mint's default)   ffmpeg -f x11grab  + PulseAudio / PipeWire-Pulse audio (desktop sound, microphone or both)
    Wayland                      wf-recorder, when it is installed (otherwise Atari says what to install)
Video is H.264 (libx264 ultrafast, a low-CPU preset) in a fragmented MP4, so even a crash or a power cut leaves a playable
file. Files go to ~/Videos/Atari Recordings/Atari-YYYY-MM-DD_HH-MM-SS.mp4 (change the folder in Settings).
Stopping sends SIGINT, which makes ffmpeg finish the file properly. VAAPI hardware encoding is available with
`[recording] encoder = "vaapi"` in config.toml (it is not the default because it depends on the graphics driver).
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Callable

AUDIO_MODES = ("none", "desktop", "mic", "both")
AUDIO_LABELS = {"none": "No sound", "desktop": "Game / desktop sound", "mic": "Microphone", "both": "Desktop sound + microphone"}
QUALITIES = {"low": 33, "medium": 28, "high": 23}          # x264 CRF: lower = better picture, bigger file
FPS_CHOICES = (30, 60)


def default_dir(home: Path | None = None) -> Path:
    return (home or Path.home()) / "Videos" / "Atari Recordings"


def out_dir(cfg, home: Path | None = None) -> Path:
    d = (getattr(cfg, "rec_dir", "") or "").strip()
    return Path(d).expanduser() if d else default_dir(home)


def new_filename(now: float | None = None) -> str:
    return time.strftime("Atari-%Y-%m-%d_%H-%M-%S.mp4", time.localtime(now))


def session_type(env: dict | None = None) -> str:
    """'x11' | 'wayland' | ''"""
    env = os.environ if env is None else env
    st = (env.get("XDG_SESSION_TYPE") or "").lower()
    if st == "wayland" and env.get("WAYLAND_DISPLAY"):
        return "wayland"
    if env.get("DISPLAY"):
        return "x11"
    return "wayland" if env.get("WAYLAND_DISPLAY") else ""


def screen_size(display: str | None = None) -> tuple[int, int] | None:
    """Pixel size of the whole X screen (ffmpeg's x11grab needs it), or None."""
    name = display if display is not None else os.environ.get("DISPLAY", "")
    lib = ctypes.util.find_library("X11")
    if not name or not lib:
        return None
    try:
        x = ctypes.CDLL(lib)
        x.XOpenDisplay.restype = ctypes.c_void_p
        x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x.XDisplayWidth.argtypes = [ctypes.c_void_p, ctypes.c_int]
        x.XDisplayHeight.argtypes = [ctypes.c_void_p, ctypes.c_int]
        x.XCloseDisplay.argtypes = [ctypes.c_void_p]
        dpy = x.XOpenDisplay(name.encode())
        if not dpy:
            return None
        try:
            w, h = x.XDisplayWidth(dpy, 0), x.XDisplayHeight(dpy, 0)
        finally:
            x.XCloseDisplay(dpy)
        return (w - w % 2, h - h % 2) if w > 0 and h > 0 else None   # H.264 wants even sizes
    except (OSError, AttributeError):
        return None


def _pactl(which: Callable, run: Callable, *args: str) -> str:
    if not which("pactl"):
        return ""
    try:
        r = run(["pactl", *args], capture_output=True, text=True, timeout=4)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def pulse_sources(which: Callable = shutil.which, run: Callable = subprocess.run) -> tuple[str, str]:
    """(desktop-sound source, microphone source). Desktop sound = the monitor of the default output."""
    sink = _pactl(which, run, "get-default-sink")
    mic = _pactl(which, run, "get-default-source")
    return (sink + ".monitor" if sink else "@DEFAULT_MONITOR@"), (mic or "default")


def has_encoder(name: str, which: Callable = shutil.which, run: Callable = subprocess.run) -> bool:
    ff = which("ffmpeg")
    if not ff:
        return False
    try:
        return name in run([ff, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=8).stdout
    except (OSError, subprocess.SubprocessError):
        return False


def build_command(cfg, out_file: Path, *, size: tuple[int, int] | None, env: dict | None = None,
                  which: Callable = shutil.which, run: Callable = subprocess.run, sources: tuple[str, str] | None = None) -> list[str]:
    """The recorder command, or [] when nothing here can record (the caller explains why)."""
    env = os.environ if env is None else env
    audio = getattr(cfg, "rec_audio", "desktop")
    fps = int(getattr(cfg, "rec_fps", 30) or 30)
    crf = QUALITIES.get(getattr(cfg, "rec_quality", "medium"), 28)
    kind = session_type(env)
    if kind == "wayland" and which("wf-recorder"):
        cmd = ["wf-recorder", "-f", str(out_file), "-r", str(fps), "-c", "libx264", "-p", f"crf={crf}", "-p", "preset=ultrafast"]
        if audio != "none":
            cmd.append("-a")           # wf-recorder records the default source; desktop sound needs a loopback - noted in the README
        return cmd
    ff = which("ffmpeg")
    if not ff or kind != "x11" or size is None:
        return []
    cmd = [ff, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
           "-f", "x11grab", "-framerate", str(fps), "-video_size", f"{size[0]}x{size[1]}", "-draw_mouse", "1",
           "-i", f"{env.get('DISPLAY', ':0')}+0,0"]
    inputs: list[str] = []
    if audio != "none":
        desk, mic = sources or pulse_sources(which, run)
        if audio in ("desktop", "both"):
            inputs.append(desk)
        if audio in ("mic", "both"):
            inputs.append(mic)
        for src in inputs:
            cmd += ["-thread_queue_size", "1024", "-f", "pulse", "-i", src]
    if len(inputs) == 2:
        cmd += ["-filter_complex", "[1:a][2:a]amix=inputs=2:duration=longest[a]", "-map", "0:v", "-map", "[a]"]
    elif inputs:
        cmd += ["-map", "0:v", "-map", "1:a"]
    if getattr(cfg, "rec_encoder", "x264") == "vaapi" and has_encoder("h264_vaapi", which, run) and Path("/dev/dri/renderD128").exists():
        cmd = cmd[:1] + ["-vaapi_device", "/dev/dri/renderD128"] + cmd[1:]
        cmd += ["-vf", "format=nv12,hwupload", "-c:v", "h264_vaapi", "-qp", str(crf)]
    else:
        cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-crf", str(crf), "-pix_fmt", "yuv420p"]
    if inputs:
        cmd += ["-c:a", "aac", "-b:a", "160k"]
    cmd += ["-movflags", "+frag_keyframe+empty_moov+default_base_moof", str(out_file)]
    return cmd


def why_not(cfg, env: dict | None = None, which: Callable = shutil.which) -> str:
    """Plain-English reason recording is impossible here ('' when it can work)."""
    env = os.environ if env is None else env
    kind = session_type(env)
    if kind == "wayland" and not which("wf-recorder"):
        return ("This is a Wayland session. Recording there needs wf-recorder (sudo apt install wf-recorder) - "
                "or log in with the standard 'Cinnamon' (X11) session, which Atari can record with ffmpeg.")
    if kind == "":
        return "There is no screen to record (no display found)."
    if kind == "x11" and not which("ffmpeg"):
        return "ffmpeg is not installed yet. Press Install to add it."
    return ""


class Recorder:
    """Starts and stops one recording. Safe to call from the main thread; nothing here blocks for long."""

    def __init__(self, popen: Callable = subprocess.Popen):
        self._popen = popen
        self.proc: subprocess.Popen | None = None
        self.path: Path | None = None
        self.started = 0.0
        self.error = ""

    @property
    def active(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def elapsed(self) -> float:
        return time.time() - self.started if self.active else 0.0

    def start(self, cfg, *, size=None, env: dict | None = None, which: Callable = shutil.which,
              home: Path | None = None, run: Callable = subprocess.run, sources=None) -> Path | None:
        self.error = ""
        if self.active:
            return self.path
        reason = why_not(cfg, env, which)
        if reason:
            self.error = reason
            return None
        d = out_dir(cfg, home)
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.error = f"Cannot create the recordings folder {d}: {exc}"
            return None
        target = d / new_filename()
        if session_type(env) == "x11" and size is None:
            size = screen_size()
        cmd = build_command(cfg, target, size=size, env=env, which=which, run=run, sources=sources)
        if not cmd:
            self.error = "Atari could not work out how to record this screen."
            return None
        try:
            self.proc = self._popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                    start_new_session=True)
        except OSError as exc:
            self.error = f"Could not start the recorder: {exc}"
            return None
        self.path, self.started = target, time.time()
        time.sleep(0.4)                     # a wrong option makes ffmpeg exit at once: report that instead of "recording"
        if self.proc.poll() is not None:
            err = ""
            try:
                err = (self.proc.stderr.read() or b"").decode(errors="replace").strip().splitlines()[-1:][0]
            except (OSError, IndexError, ValueError):
                pass
            self.error = "The recorder stopped right away" + (f": {err[:160]}" if err else ".")
            self.proc = None
            return None
        return target

    def stop(self, wait: float = 8.0) -> Path | None:
        """Finish the file. Returns its path (None if nothing was recording)."""
        proc, path = self.proc, self.path
        if proc is None:
            return None
        try:
            os.killpg(proc.pid, signal.SIGINT)         # ffmpeg / wf-recorder close the file cleanly on SIGINT
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.send_signal(signal.SIGINT)
            except OSError:
                pass
        try:
            proc.wait(wait)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(3)
            except subprocess.TimeoutExpired:
                proc.kill()
        self.proc = None
        return path if path and path.is_file() and path.stat().st_size > 0 else None


def list_recordings(cfg, home: Path | None = None) -> list[dict]:
    """Newest first: [{path, name, size_mb, when}]"""
    d = out_dir(cfg, home)
    out = []
    try:
        for p in d.iterdir():
            if p.suffix.lower() in (".mp4", ".mkv", ".webm") and p.is_file():
                st = p.stat()
                out.append({"path": str(p), "name": p.name, "size_mb": st.st_size / (1024 * 1024), "mtime": st.st_mtime})
    except OSError:
        return []
    return sorted(out, key=lambda r: -r["mtime"])


def player_command(path: str, cfg=None, which: Callable = shutil.which) -> list[str]:
    """mpv (native or Flatpak) to play a recording full screen; xdg-open as the last resort."""
    custom = ((cfg.emulator_commands.get("mpv") if cfg is not None else "") or "").strip()
    if custom:
        import shlex
        return shlex.split(custom) + [path]
    if which("mpv"):
        return ["mpv", "--fs", path]
    from .emulators import flatpak_installed
    if which("flatpak") and flatpak_installed("io.mpv.Mpv"):
        return ["flatpak", "run", "--filesystem=" + str(Path(path).parent), "io.mpv.Mpv", "--fs", path]
    if which("xdg-open"):
        return ["xdg-open", path]
    return []
