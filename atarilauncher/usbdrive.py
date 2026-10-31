"""CodeAque USB: notice a USB stick when it is plugged in (Mint mounts it by itself through udisks2), and "Make a CodeAque USB"
(folders + a README on a stick you choose - it never formats or deletes anything). Only your own games, free homebrew and your
own BIOS dumps belong on it; CodeAque ships none."""
from __future__ import annotations

from pathlib import Path

from . import importer

ROOT = "CodeAque"
SYSTEMS = ("nes", "snes", "n64", "gb", "gbc", "gba", "nds", "genesis", "mastersystem", "psx", "ps2", "psp", "gamecube", "wii",
           "xbox", "dreamcast", "atari2600", "atarilynx", "arcade", "dos")
README = """CodeAque USB
============

Plug this stick into a computer running CodeAque: it finds the games on it by itself and asks whether to play them straight
from the stick or copy them over.

Put each game in the folder of its console, for example:
  CodeAque/snes/My Game.sfc
  CodeAque/psx/My Game.chd
  CodeAque/BIOS/   (your own BIOS dumps, e.g. scph5501.bin - CodeAque finds and copies them)

Only put games and BIOS files on here that you are allowed to have: your own dumps of games and consoles you own, or free
homebrew / freeware that its makers share. CodeAque does not include or download any commercial games, BIOS or keys.
"""


def drives() -> list:
    try:
        return importer.detect_drives()
    except Exception:
        return []


class Watcher:
    """Call tick() every few seconds: returns the drives that appeared since the last tick (not the ones there at start)."""
    def __init__(self, lister=drives):
        self.lister = lister
        self.known = {d.path for d in lister()}

    def tick(self) -> list:
        now = self.lister()
        new = [d for d in now if d.path not in self.known]
        self.known = {d.path for d in now}
        return new


def game_root(mount: str) -> Path:
    p = Path(mount) / ROOT
    return p if p.is_dir() else Path(mount)


def prepare(mount: str, systems=SYSTEMS) -> tuple[bool, str]:
    """Make CodeAque/<system>, CodeAque/BIOS and README.txt on the stick. Nothing is deleted or formatted; existing files stay."""
    base = Path(mount) / ROOT
    try:
        for s in (*systems, "BIOS"):
            (base / s).mkdir(parents=True, exist_ok=True)
        rd = base / "README.txt"
        if not rd.exists():
            rd.write_text(README)
    except OSError as exc:
        return False, f"Could not write to the stick ({exc.strerror or exc}). Is it write-protected or full?"
    return True, f"Ready: {base} has a folder for each console, a BIOS folder and a README. Nothing on the stick was erased."
