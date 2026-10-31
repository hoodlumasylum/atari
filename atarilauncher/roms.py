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
    mtime: float = 0.0


def read_sfo_title(sfo: Path) -> str:
    """TITLE from a PS3 PARAM.SFO file ('' if unreadable)."""
    import struct
    try:
        data = sfo.read_bytes()
        if data[:4] != b"\0PSF":
            return ""
        key_off, data_off, count = struct.unpack_from("<III", data, 8)
        for i in range(min(count, 64)):
            k_off, fmt, ln, _mx, d_off = struct.unpack_from("<HHIII", data, 20 + i * 16)
            key = data[key_off + k_off:data.index(b"\0", key_off + k_off)].decode("ascii", "replace")
            if key == "TITLE":
                return data[data_off + d_off:data_off + d_off + ln].split(b"\0")[0].decode("utf-8", "replace").strip()
    except (OSError, ValueError, struct.error):
        pass
    return ""


def _ps3_game_in(dirpath: str, dirnames: list[str], filenames: list[str]) -> tuple[Path, str] | None:
    """If this folder is a PS3 game (PS3_GAME/USRDIR/EBOOT.BIN, or an installed USRDIR/EBOOT.BIN),
    return (path of EBOOT.BIN, title)."""
    base = Path(dirpath)
    upper = {d.upper(): d for d in dirnames}
    if "PS3_GAME" in upper:
        game = base / upper["PS3_GAME"]
        eboot = game / "USRDIR" / "EBOOT.BIN"
        if not eboot.is_file():
            hits = [p for p in (game / "USRDIR").glob("*") if p.name.upper() == "EBOOT.BIN"]
            eboot = hits[0] if hits else eboot
        title = read_sfo_title(game / "PARAM.SFO") or clean_title(base.name)
        return eboot, title
    if "USRDIR" in upper:
        usr = base / upper["USRDIR"]
        hits = [p for p in usr.glob("*") if p.name.upper() == "EBOOT.BIN"] if usr.is_dir() else []
        if hits:
            title = read_sfo_title(base / "PARAM.SFO") or clean_title(base.name)
            return hits[0], title
    return None


def scan_folder(folder: Path, extensions, system: str, max_files: int = 20000) -> list[Rom]:
    exts = {e.lower().lstrip(".") for e in extensions}
    roms: list[Rom] = []
    folder = Path(folder).expanduser()
    if not folder.is_dir():
        return roms
    for dirpath, dirnames, filenames in os.walk(folder, followlinks=False):
        if system == "ps3":
            game = _ps3_game_in(dirpath, dirnames, filenames)
            if game:  # a PS3 game folder is one game: do not look inside it
                try:
                    mtime = Path(dirpath).stat().st_mtime
                except OSError:
                    mtime = 0.0
                roms.append(Rom(game[0], system, game[1], mtime))
                dirnames[:] = []
                continue
        if system == "xbox":
            xbe = [f for f in filenames if f.lower() == "default.xbe"]
            if xbe:  # an unpacked original-Xbox game folder is one game
                try:
                    mtime = Path(dirpath).stat().st_mtime
                except OSError:
                    mtime = 0.0
                roms.append(Rom(Path(dirpath) / xbe[0], system, clean_title(Path(dirpath).name), mtime))
                dirnames[:] = []
                continue
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for fn in sorted(filenames):
            if fn.startswith("."):
                continue
            ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
            if ext in exts:
                full = Path(dirpath) / fn
                try:
                    mtime = full.stat().st_mtime
                except OSError:
                    mtime = 0.0
                roms.append(Rom(full, system, clean_title(fn), mtime))
                if len(roms) >= max_files:
                    return roms
    return roms


def scan_system(folders, extensions, system: str) -> list[Rom]:
    out, seen = [], set()
    for f in folders:
        for r in scan_folder(Path(f), extensions, system):
            key = os.path.realpath(r.path)
            if system == "xbox" and r.path.suffix.lower() == ".iso" and r.path.with_suffix(".xiso").is_file():
                continue        # CodeAque made a fixed copy next to it ("Fix game file"): show the game once, as the copy
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
