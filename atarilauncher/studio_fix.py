"""Studio first aid: find out why the Studio (beat maker / voice recorder) cannot work and fix it with one press.

Typical causes on a real Linux Mint laptop:
  * numpy (the only extra Python library) is missing - the installer's pip step lost the network once;
  * no recording program (parecord / arecord / ffmpeg) - `pulseaudio-utils` gives parecord;
  * no microphone is plugged in or chosen.
Everything the Studio hits is also written to ~/.local/share/atari/logs/studio.log, which "Copy log" in Help includes.
All the outside world (pip, pkexec, which) is injectable, so tests never install anything."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import paths
from . import rootauth

NUMPY_REQ = "numpy>=1.24"
AUDIO_PKG = "pulseaudio-utils"          # parecord + pactl (PipeWire systems provide the same commands through pipewire-pulse)


def log_dir() -> Path:
    return paths.data_dir() / "logs"


def log_file() -> Path:
    return log_dir() / "studio.log"


def log(message: str) -> None:
    """One line into the Studio log. Never raises."""
    try:
        log_dir().mkdir(parents=True, exist_ok=True)
        with open(log_file(), "a", encoding="utf-8") as fh:
            fh.write(time.strftime("%Y-%m-%d %H:%M:%S ") + message.replace("\n", " | ") + "\n")
    except OSError:
        pass


def read_log(lines: int = 60) -> list[str]:
    try:
        return log_file().read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
    except OSError:
        return []


@dataclass
class Problem:
    id: str            # numpy | audio-tools | microphone
    text: str          # plain English
    fixable: bool      # "Fix Studio" can do it
    blocking: bool = True


def numpy_ok() -> bool:
    from .studio import numpy_available
    return numpy_available()


def in_venv() -> bool:
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def problems(numpy_ok: bool, which: Callable = shutil.which, sources: list | None = None) -> list[Problem]:
    out: list[Problem] = []
    if not numpy_ok:
        out.append(Problem("numpy", "The Studio needs one extra library (numpy) and it is not installed yet.", True))
    if not any(which(x) for x in ("parecord", "arecord", "ffmpeg")):
        out.append(Problem("audio-tools", "No recording program was found (parecord, arecord or ffmpeg), so the microphone cannot be used. "
                                          "Beats still work.", bool(rootauth.can_elevate(which) and which("apt-get")), blocking=False))
    if sources is not None and not sources and which("pactl"):
        out.append(Problem("microphone", "No microphone was found. Plug in a USB microphone or headset, then open this screen again. "
                                         "If one is plugged in, check Linux Mint's Sound settings > Input.", False, blocking=False))
    return out


def summary(ps: list[Problem]) -> str:
    return " ".join(p.text for p in ps) if ps else "Everything the Studio needs is here."


def fix(ps: list[Problem], out: Callable[[str], None], run: Callable | None = None, which: Callable = shutil.which,
        python: str | None = None) -> tuple[bool, str]:
    """Install what is missing. Returns (all fixable things worked, plain-English result). Never raises."""
    from .appinstall import stream_run
    run = run or stream_run
    python = python or sys.executable
    done: list[str] = []
    failed: list[str] = []
    for p in ps:
        if not p.fixable:
            continue
        if p.id == "numpy":
            out("Adding the numpy library (about 20 MB, needs internet)...")
            if in_venv():
                rc = run([python, "-m", "pip", "install", "--disable-pip-version-check", NUMPY_REQ], out, None)
            elif rootauth.can_elevate(which) and which("apt-get"):
                out("Code is not in its own Python environment, so numpy comes from your system. A password window will pop up...")
                rc = run(["pkexec", "apt-get", "install", "-y", "python3-numpy"], out, None)
            else:
                rc = 1
            (done if rc == 0 else failed).append("numpy")
            log(f"fix numpy rc={rc}")
        elif p.id == "audio-tools":
            out("Adding the recording tools - a password window will pop up...")
            rc = run(["pkexec", "apt-get", "install", "-y", AUDIO_PKG], out, None)
            (done if rc == 0 and any(which(x) for x in ("parecord", "arecord")) else failed).append("recording tools")
            log(f"fix audio-tools rc={rc}")
    if failed:
        return False, ("Could not add: " + ", ".join(failed) + ". Check the internet connection and press Fix Studio again, "
                       "or run ./install.sh again in the Code folder.")
    if done:
        return True, "Added " + " and ".join(done) + ". The Studio is ready."
    return True, "Nothing needed fixing."
