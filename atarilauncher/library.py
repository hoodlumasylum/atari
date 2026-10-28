"""Combine Steam games and ROMs into one list of Game objects."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import paths, roms, steam
from .config import Config

STEAM = "steam"
_IMG_EXT = ("png", "jpg", "jpeg", "webp")


@dataclass
class Game:
    gid: str
    title: str
    platform: str  # "steam" or a system id
    platform_name: str
    cover: str = ""  # local file path or ""
    steam_appid: str = ""
    rom_path: str = ""
    note: str = ""  # small warning/info line shown in the detail bar


@dataclass
class LibraryResult:
    games: list[Game] = field(default_factory=list)
    steam_scan: steam.SteamScan = field(default_factory=steam.SteamScan)
    rom_counts: dict[str, int] = field(default_factory=dict)
    steam_note: str = ""  # friendly status for the setup screen / empty state


def find_custom_cover(system_id: str, rom_path: Path, covers_root: Path | None = None) -> str:
    """User-supplied art: ~/.config/atari/covers/<system>/<rom file name without extension>.png"""
    root = (covers_root or paths.covers_dir()) / system_id
    if not root.is_dir():
        return ""
    for ext in _IMG_EXT:
        for cand in (root / f"{rom_path.stem}.{ext}", root / f"{rom_path.stem}.{ext.upper()}"):
            if cand.is_file():
                return str(cand)
    return ""


def steam_status_text(scan: steam.SteamScan, enabled: bool = True) -> str:
    if not enabled:
        return "Steam is turned off in settings."
    if not scan.found:
        return "Steam was not found. Install Steam and sign in once, then choose Rescan."
    parts = [f"Steam found at {scan.root}"]
    parts.append(f"{len(scan.games)} installed game{'s' if len(scan.games) != 1 else ''} "
                 f"in {len(scan.libraries)} librar{'ies' if len(scan.libraries) != 1 else 'y'}")
    miss = scan.missing_libraries
    if miss:
        parts.append("NOT MOUNTED: " + ", ".join(str(m.path) for m in miss))
    if any(lib.on_ntfs for lib in scan.libraries):
        parts.append("some libraries are on a Windows (NTFS) drive; Proton games may not run well there")
    return ". ".join(parts) + "."


def build_library(cfg: Config, home: Path | None = None, covers_root: Path | None = None,
                  mounts_file: str = "/proc/mounts") -> LibraryResult:
    res = LibraryResult()
    if cfg.steam_enabled:
        try:
            res.steam_scan = steam.scan_steam(home, cfg.steam_root, cfg.steam_extra_libraries, mounts_file)
        except Exception as exc:  # never let a odd Steam folder crash the launcher
            print(f"[atari] Steam scan failed: {exc}")
        scan = res.steam_scan
        for g in scan.games:
            note = ""
            if g.on_ntfs:
                note = "Installed on a Windows (NTFS) drive - may not run well on Linux"
            res.games.append(Game(
                gid=f"steam:{g.appid}", title=g.name, platform=STEAM, platform_name="Steam",
                cover=steam.find_art(scan.root, g.appid), steam_appid=g.appid, note=note))
    res.steam_note = steam_status_text(res.steam_scan, cfg.steam_enabled)

    for sc in cfg.systems.values():
        if not sc.roms:
            continue
        try:
            found = roms.scan_system(sc.roms, sc.extensions, sc.id)
        except Exception as exc:
            print(f"[atari] ROM scan failed for {sc.id}: {exc}")
            found = []
        res.rom_counts[sc.id] = len(found)
        for r in found:
            res.games.append(Game(
                gid=f"rom:{sc.id}:{os.path.realpath(r.path)}", title=r.title, platform=sc.id,
                platform_name=sc.name, cover=find_custom_cover(sc.id, r.path, covers_root),
                rom_path=str(r.path)))
    return res


def demo_library() -> LibraryResult:
    """Made-up games used for the screenshot / --demo. No real titles or art."""
    steam_titles = ["Cosmic Crawler", "Neon Pinball Deluxe", "Dungeon of Pixels", "Turbo Kart Rally",
                    "Lantern Valley", "Orbital Defense", "Mushroom Kingdom Builder", "Rust & Rails"]
    games = [Game(f"steam:{9000000 + i}", t, STEAM, "Steam", steam_appid=str(9000000 + i))
             for i, t in enumerate(steam_titles)]
    retro = {
        "atari2600": ("Atari 2600", ["Blocky Breakout", "Desert Raider", "Sky Gunner", "Maze Muncher"]),
        "atari7800": ("Atari 7800", ["Space Harrier Jr", "Pixel Hockey"]),
        "nes": ("Nintendo NES", ["Plumber Panic", "Ninja Frogs", "Castle Quest"]),
        "snes": ("Super Nintendo", ["Cloud Racers", "Dragon Tamer"]),
        "genesis": ("Sega Genesis", ["Hedgehog Hustle", "Street Brawlers"]),
        "gba": ("Game Boy Advance", ["Tiny Tactics", "Pocket Fishing"]),
    }
    counts = {}
    for sid, (name, titles) in retro.items():
        counts[sid] = len(titles)
        games += [Game(f"rom:{sid}:/demo/{t}", t, sid, name, rom_path=f"/demo/{t}") for t in titles]
    scan = steam.SteamScan(root=Path("/demo/Steam"))
    return LibraryResult(games, scan, counts, "Demo mode - these games are made up.")
