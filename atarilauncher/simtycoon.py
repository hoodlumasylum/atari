"""Sim & Tycoon: simulation and management games from every source (Steam, PC Games, DOS, emulated consoles), plus games you add by
hand, and - only when you ask - open-source engine remakes that play YOUR OWN original game files:

  CorsixTH  (Theme Hospital)                  MIT licence        com.corsixth.corsixth        needs your Theme Hospital files
  OpenRCT2  (RollerCoaster Tycoon 2 / 1)      GPL-3.0            io.openrct2.OpenRCT2         needs your RCT2 (or RCT Classic) files
  OpenTTD   (Transport Tycoon Deluxe style)   GPL-2.0            org.openttd.OpenTTD          free: comes with the free OpenGFX / OpenSFX / OpenMSX sets
  Augustus  (Caesar III)                      AGPL-3.0           com.github.keriew.augustus   needs your Caesar III files

(Licences as each project publishes them; the Flathub ids were checked on flathub.org.) CodeAque includes no game data, logos or box
art. The original files are looked for in your games folders, Downloads, GOG / Heroic installs, CodeAque's PC Games folders and Steam.
Which games count as "sim / tycoon" is decided from the title (Steam's genre tags are not stored on your computer, so they cannot be
used offline); anything can be added or removed by hand. Never raises."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .apps import AppDef

FILTER = "simtycoon"
NAME = "Sim & Tycoon"
TAGS_PREF = "sim_tags"        # games added by hand
UNTAGS_PREF = "sim_untags"    # games taken out by hand

TITLE_RE = re.compile(r"\b(theme hospital|theme park|rollercoaster tycoon|roller coaster tycoon|openrct2|transport tycoon|openttd|"
                      r"railroad tycoon|zoo tycoon|sim ?city|the sims|simtower|simfarm|simearth|simant|sim ?copter|cities[: ]+skylines|"
                      r"planet coaster|planet zoo|two point (hospital|campus|museum)|prison architect|tropico|anno \d|caesar (ii|iii|iv|3|4)|"
                      r"pharaoh|zeus|emperor[: ]+rise|startopia|dungeon keeper|frostpunk|banished|factorio|rimworld|oxygen not included|"
                      r"stardew valley|farming simulator|euro truck simulator|american truck simulator|flight simulator|"
                      r"jurassic world evolution|game dev tycoon|mad games tycoon|software inc|capitalism|cities in motion|"
                      r"theme (aquarium|resort)|hospital tycoon|parkitect|production line|satisfactory|house flipper|"
                      r"powerwash simulator|lemonade|tycoon|simulator)\b", re.I)


def is_sim_title(title: str) -> bool:
    return bool(TITLE_RE.search(title or ""))


GENRE_RE = re.compile(r"simulation|management|tycoon|city.?builder|strategy.?sim|god game", re.I)


def in_section(gid: str, title: str, tags: list | None, untags: list | None, genre: str = "") -> bool:
    """Added by hand, or a sim title, or a game whose genre (Steam / metadata, when known) says simulation / management."""
    if gid in (untags or []):
        return False
    return gid in (tags or []) or is_sim_title(title) or bool(GENRE_RE.search(genre or ""))


def steam_libraries(home: Path | None = None) -> list[Path]:
    from . import steam
    home = home or Path.home()
    out: list[Path] = []
    for root in (home / ".local/share/Steam", home / ".steam/steam", home / ".var/app/com.valvesoftware.Steam/.local/share/Steam"):
        vdf = root / "steamapps" / "libraryfolders.vdf"
        libs = [root] + ([Path(x) for x in steam.parse_libraryfolders(vdf)] if vdf.is_file() else [])
        for lib in libs:
            if lib.is_dir() and lib not in out:
                out.append(lib)
    return out


@dataclass(frozen=True)
class Engine:
    app: AppDef
    game: str                 # the original it plays
    licence: str
    needs_data: bool
    data_name: str = ""       # "Theme Hospital files"
    check: str = ""           # which data finder


ENGINES = [
    Engine(AppDef("corsixth", "CorsixTH (plays Theme Hospital)", "com.corsixth.corsixth", ("corsix-th", "CorsixTH"),
                  "Open-source Theme Hospital engine. Needs your own Theme Hospital files.", group="sim"),
           "Theme Hospital", "MIT", True, "Theme Hospital files", "th"),
    Engine(AppDef("openrct2", "OpenRCT2 (plays RollerCoaster Tycoon 2)", "io.openrct2.OpenRCT2", ("openrct2",),
                  "Open-source RollerCoaster Tycoon 2 engine. Needs your own RCT2 or RCT Classic files.", group="sim"),
           "RollerCoaster Tycoon 2", "GPL-3.0", True, "RollerCoaster Tycoon 2 files", "rct2"),
    Engine(AppDef("openttd", "OpenTTD (free transport tycoon)", "org.openttd.OpenTTD", ("openttd",),
                  "Free and open source. Comes with free graphics, sound and music (OpenGFX, OpenSFX, OpenMSX).", group="sim"),
           "OpenTTD", "GPL-2.0", False),
    Engine(AppDef("augustus", "Augustus (plays Caesar III)", "com.github.keriew.augustus", ("augustus",),
                  "Open-source Caesar III engine. Needs your own Caesar III files.", group="sim"),
           "Caesar III", "AGPL-3.0", True, "Caesar III files", "c3"),
]
APPS = [e.app for e in ENGINES]
BY_ID = {e.app.id: e for e in ENGINES}


# ------------------------------------------------------------------ finding the original files
def _ci(folder: Path, *parts: str) -> Path | None:
    """folder/parts with any upper / lower case (DOS and Windows games mix them)."""
    cur = folder
    for p in parts:
        try:
            hit = next((c for c in cur.iterdir() if c.name.lower() == p.lower()), None)
        except OSError:
            return None
        if hit is None:
            return None
        cur = hit
    return cur


def looks_like(kind: str, folder: Path) -> bool:
    if kind == "th":          # CorsixTH: a folder with DATA and LEVELS (HOSPITAL.EXE / HOSP95.EXE next to them)
        return _ci(folder, "data") is not None and (_ci(folder, "levels") is not None or _ci(folder, "hospital.exe") is not None
                                                    or _ci(folder, "hosp95.exe") is not None) and _ci(folder, "data", "vblk-0.tab") is not None
    if kind == "rct2":        # OpenRCT2: Data/g1.dat
        return _ci(folder, "data", "g1.dat") is not None
    if kind == "rct1":
        return _ci(folder, "data", "csg1.dat") is not None
    if kind == "c3":          # Augustus: c3.eng (or c3_north.555) in the folder
        return _ci(folder, "c3.eng") is not None or _ci(folder, "c3_north.555") is not None
    return False


def search_roots(home: Path | None = None, steam_libraries: list[Path] | None = None) -> list[Path]:
    home = home or Path.home()
    roots = [home / "Games", home / "GOG Games", home / "Downloads", home / "Documents", home / "Games/Heroic",
             home / ".local/share/atari/prefixes"]
    for lib in steam_libraries or []:
        roots.append(Path(lib) / "steamapps" / "common")
    return [r for r in roots if r.is_dir()]


def find_data(kind: str, roots: list[Path], max_depth: int = 6) -> str:
    """The first folder that holds these original files, or ''."""
    for root in roots:
        base = len(root.parts)
        for dirpath, dirnames, _files in os.walk(root, onerror=lambda e: None):
            d = Path(dirpath)
            if len(d.parts) - base >= max_depth:
                dirnames[:] = []
            dirnames[:] = [x for x in dirnames if not x.startswith(".") and x.lower() not in ("windows", "node_modules")]
            if looks_like(kind, d):
                return str(d)
    return ""


# ------------------------------------------------------------------ telling the engine where the files are
def corsixth_configs(home: Path | None = None) -> list[Path]:
    home = home or Path.home()
    return [home / ".config/CorsixTH/config.txt", home / ".var/app/com.corsixth.corsixth/config/CorsixTH/config.txt"]


def openrct2_configs(home: Path | None = None) -> list[Path]:
    home = home or Path.home()
    return [home / ".config/OpenRCT2/config.ini", home / ".var/app/io.openrct2.OpenRCT2/config/OpenRCT2/config.ini"]


def augustus_configs(home: Path | None = None) -> list[Path]:
    home = home or Path.home()
    return [home / ".local/share/augustus-game/augustus.ini", home / ".var/app/com.github.keriew.augustus/data/augustus-game/augustus.ini"]


def _set_line(text: str, key_re: str, line: str, section: str = "") -> str:
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if re.match(key_re, ln.strip()):
            lines[i] = line
            return "\n".join(lines) + "\n"
    if section:
        for i, ln in enumerate(lines):
            if ln.strip().lower() == f"[{section}]":
                lines.insert(i + 1, line)
                return "\n".join(lines) + "\n"
        lines += ([""] if lines else []) + [f"[{section}]", line]
        return "\n".join(lines) + "\n"
    return "\n".join(lines + [line]) + "\n"


def point_engine_at(engine_id: str, data: str, home: Path | None = None, which: Callable = shutil.which,
                    runner: Callable | None = None) -> list[str]:
    """Write the data folder into the engine's settings (native and Flatpak copies) and, for the Flatpak, let it read that folder.
    Returns the files written. Other settings are left alone."""
    written = []
    if engine_id == "corsixth":
        files, key, line, sec = corsixth_configs(home), r"^theme_hospital_install\s*=", f"theme_hospital_install = [[{data}]]", ""
    elif engine_id == "openrct2":
        files, key, line, sec = openrct2_configs(home), r"^game_path\s*=", f'game_path = "{data}"', "general"
    elif engine_id == "augustus":
        files, key, line, sec = augustus_configs(home), r"^game_path\s*=", f"game_path={data}", ""
    else:
        return written
    for f in files:
        try:
            text = f.read_text(encoding="utf-8") if f.is_file() else ""
            new = _set_line(text, key, line, sec)
            if new != text:
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(new, encoding="utf-8")
                written.append(str(f))
        except OSError:
            continue
    eng = BY_ID.get(engine_id)
    if eng and which("flatpak"):
        try:
            (runner or subprocess.run)(["flatpak", "override", "--user", f"--filesystem={data}:ro", eng.app.flatpak],
                                       capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            pass
    return written


NO_TH_DATA = ("You need your own Theme Hospital files. CorsixTH plays Theme Hospital, but the original game's files (graphics, sounds, "
              "levels) are not included - they come from your own copy (for example the GOG or EA version). Install the game, or copy its "
              "folder (with DATA and LEVELS inside) into ~/Games, then press Look again.")
