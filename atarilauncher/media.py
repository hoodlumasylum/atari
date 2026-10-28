"""Music in the background: what is playing and play / pause / next / previous, for the small control in the top bar.

Spotify (the desktop app, Flatpak com.spotify.Client, or its web player in a browser) and most other players publish
themselves on the desktop's MPRIS interface. `playerctl` (the standard small tool, apt package "playerctl") talks to it; CodeAque only
runs it with a short timeout and never needs a login, key or network. With no playerctl, or no player, the control stays hidden.
Spotify is asked first, then any other player. Nothing here knows Spotify's logo or artwork: the tiles' icons are fetched at runtime.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable

FORMAT = "{{status}}\t{{playerName}}\t{{artist}}\t{{title}}"
PLAYERS = "spotify,%any"              # Spotify first, otherwise whichever player there is
ACTIONS = {"play-pause": "play-pause", "next": "next", "previous": "previous"}


@dataclass(frozen=True)
class Track:
    status: str = ""          # Playing | Paused | Stopped
    player: str = ""
    artist: str = ""
    title: str = ""

    @property
    def playing(self) -> bool:
        return self.status == "Playing"

    @property
    def text(self) -> str:
        if self.artist and self.title:
            return f"{self.artist} - {self.title}"
        return self.title or self.artist or self.player.capitalize()


def available(which: Callable = shutil.which) -> bool:
    return bool(which("playerctl"))


def _run(args: list[str], run: Callable, timeout: float = 2.0) -> tuple[int, str]:
    try:
        r = run(["playerctl", "-p", PLAYERS, *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return r.returncode, (r.stdout or "").strip()


def parse(out: str) -> Track | None:
    """'Playing\\tspotify\\tArtist\\tTitle' -> Track. None when nothing is playing or paused."""
    parts = (out.split("\t") + ["", "", "", ""])[:4]
    status, player, artist, title = (p.strip() for p in parts)
    if status not in ("Playing", "Paused"):
        return None
    return Track(status, player, artist, title)


def now_playing(which: Callable = shutil.which, run: Callable = subprocess.run) -> Track | None:
    if not available(which):
        return None
    rc, out = _run(["metadata", "--format", FORMAT], run)
    return parse(out) if rc == 0 else None


def send(action: str, which: Callable = shutil.which, run: Callable = subprocess.run) -> bool:
    """play-pause | next | previous. False when playerctl or a player is missing."""
    if action not in ACTIONS or not available(which):
        return False
    rc, _ = _run([ACTIONS[action]], run)
    return rc == 0
