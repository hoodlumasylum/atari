"""Scan user-configured ROM folders."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

_TAGS = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]")


def clean_title(filename: str) -> str:
    """'Super_Game (USA) [!].nes' -> 'Super Game'."""
    stem = Path(filename).stem
    stem = stem.replace("_", " ")
    stem = _TAGS.sub("", stem).strip(" -.")
    stem = re.sub(r"\s+", " ", stem)
    return stem or Path(filename).stem


@dataclass
class Rom:
    path: Path
    system: str
    title: str


def scan_folder(folder: Path, extensions, system: str, max_files: int = 20000) -> list[Rom]:
    exts = {e.lower().lstrip(".") for e in extensions}
    roms: list[Rom] = []
    folder = Path(folder).expanduser()
    if not folder.is_dir():
        return roms
    for dirpath, dirnames, filenames in os.walk(folder, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for fn in sorted(filenames):
            if fn.startswith("."):
                continue
            ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
            if ext in exts:
                roms.append(Rom(Path(dirpath) / fn, system, clean_title(fn)))
                if len(roms) >= max_files:
                    return roms
    return roms


def scan_system(folders, extensions, system: str) -> list[Rom]:
    out, seen = [], set()
    for f in folders:
        for r in scan_folder(Path(f), extensions, system):
            key = os.path.realpath(r.path)
            if key not in seen:
                seen.add(key)
                out.append(r)
    out.sort(key=lambda r: r.title.lower())
    return out


_ROOTS = ("ROMs", "Roms", "roms", "Games/ROMs", "Games/roms", "Emulation/roms", "Documents/ROMs")


def suggest_rom_dir(home: Path, system_id: str, aliases=()) -> str:
    """Guess an existing, non-empty folder for a system (e.g. ~/ROMs/snes). '' if none."""
    names = {system_id, system_id.upper(), *aliases, *(a.upper() for a in aliases)}
    for root in _ROOTS:
        for n in sorted(names):
            cand = home / root / n
            try:
                if cand.is_dir() and any(cand.iterdir()):
                    return str(cand)
            except OSError:
                pass
    return ""
