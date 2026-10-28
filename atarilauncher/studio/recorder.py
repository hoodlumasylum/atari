"""Recording the microphone with the programs every Linux desktop already has (PulseAudio / PipeWire's `parecord`, else `arecord`,
else `ffmpeg`): no extra Python audio library is needed. A "headphone monitor" lets you hear yourself through a loopback."""
from __future__ import annotations

import shutil
import signal
import subprocess
import time
from pathlib import Path


def list_sources(run=subprocess.run, which=shutil.which) -> list[dict]:
    """[{id, name}] of real microphones (monitors of speakers are left out). Empty if the sound server cannot be asked."""
    if not which("pactl"):
        return []
    try:
        r = run(["pactl", "list", "short", "sources"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return []
    out = []
    for line in r.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and not parts[1].endswith(".monitor"):
            out.append({"id": parts[1], "name": pretty(parts[1])})
    return out


def pretty(source_id: str) -> str:
    s = source_id.replace("alsa_input.", "").replace("usb-", "USB ").replace("_", " ").replace("-", " ")
    return s.strip()[:48] or source_id


def record_command(path: Path, source: str = "", which=shutil.which) -> list[str] | None:
    if which("parecord"):
        cmd = ["parecord", "--channels=1", "--rate=44100", "--format=s16le", "--file-format=wav"]
        if source:
            cmd.append(f"--device={source}")
        return cmd + [str(path)]
    if which("arecord"):
        return ["arecord", "-q", "-f", "S16_LE", "-r", "44100", "-c", "1", str(path)]
    if which("ffmpeg"):
        return ["ffmpeg", "-y", "-loglevel", "error", "-f", "pulse", "-i", source or "default", "-ac", "1", "-ar", "44100", str(path)]
    return None


class Recorder:
    def __init__(self, popen=subprocess.Popen, run=subprocess.run, which=shutil.which):
        self._popen, self._run, self._which = popen, run, which
        self.proc = None
        self.path: Path | None = None
        self.started = 0.0
        self._loopback = ""

    @property
    def recording(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, path: Path, source: str = "", monitor: bool = False) -> None:
        cmd = record_command(path, source, self._which)
        if cmd is None:
            raise RuntimeError("No recording program found. Install one with:  sudo apt install pulseaudio-utils   (or alsa-utils)")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = Path(path)
        try:
            self.proc = self._popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        except OSError as exc:
            raise RuntimeError(f"Could not start the recorder: {exc}")
        self.started = time.time()
        if monitor and self._which("pactl"):
            try:
                r = self._run(["pactl", "load-module", "module-loopback"] + ([f"source={source}"] if source else [])
                              + ["latency_msec=40"], capture_output=True, text=True, timeout=5)
                self._loopback = r.stdout.strip() if r.returncode == 0 else ""
            except (OSError, subprocess.TimeoutExpired):
                self._loopback = ""

    def stop(self) -> Path | None:
        """Stop and return the file (None when nothing was recorded)."""
        if self._loopback and self._which("pactl"):
            try:
                self._run(["pactl", "unload-module", self._loopback], capture_output=True, timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass
            self._loopback = ""
        proc, self.proc = self.proc, None
        if proc is None:
            return None
        try:
            if proc.poll() is None:
                proc.send_signal(signal.SIGINT)                  # parecord / arecord finish the WAV header on Ctrl-C
            proc.wait(timeout=5)
        except (subprocess.TimeoutExpired, OSError):
            proc.kill()
        return self.path if self.path and self.path.is_file() and self.path.stat().st_size > 44 else None

    def failed_early(self) -> str:
        """Text from the recorder if it quit at once (no microphone, permission ...), else ''."""
        if self.proc is not None and self.proc.poll() not in (None, 0):
            try:
                return (self.proc.stderr.read() or b"").decode(errors="replace").strip()[-200:]
            except Exception:
                return "the recorder stopped"
        return ""
