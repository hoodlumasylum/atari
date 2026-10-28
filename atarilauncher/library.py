"""Combine Steam games and ROMs into one list of Game objects."""
from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import appinstall, apps, icons, covers as covers_mod, emulators, freegames, paths, roms, steam, webapps, windows
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
    header: str = ""  # wide banner art for the detail panel (Steam header.jpg) or ""
    added: float = 0.0  # file date, used by "Recently added"
    meta: dict = field(default_factory=dict)  # optional genre / players / release / rating
    missing: str = ""  # program that is not installed yet: appinstall target id ("id" or "id|core"); shown as INSTALL
    fit: bool = False  # the picture is an app icon / logo: show it whole on a coloured tile instead of cropping it
    launch: str = ""  # for imported Heroic / Lutris games: the link that starts it (heroic://launch/..., lutris:rungameid/N)


@dataclass
class LibraryResult:
    games: list[Game] = field(default_factory=list)
    steam_scan: steam.SteamScan = field(default_factory=steam.SteamScan)
    rom_counts: dict[str, int] = field(default_factory=dict)
    steam_note: str = ""  # friendly status for the setup screen / empty state


def _dir_index(folder: Path) -> dict[str, str]:
    """{lower-case file name: real file name} for the image files of one folder."""
    try:
        return {n.lower(): n for n in os.listdir(folder) if n.rsplit(".", 1)[-1].lower() in _IMG_EXT}
    except OSError:
        return {}


def find_custom_cover(system_id: str, rom_path: Path, covers_root: Path | None = None,
                      title: str = "", _cache: dict | None = None) -> str:
    """Your own art for a ROM. Looked up (name match is not case sensitive) as
    ~/.local/share/atari/covers/<game name>.png|jpg  (also in a <system> sub folder), and as the older
    ~/.config/atari/covers/<system>/<rom file name>.png.  <game name> = the clean title or the file name."""
    roots = [covers_root] if covers_root else [paths.user_covers_dir(), paths.covers_dir()]
    cache = _cache if _cache is not None else {}
    names = [n for n in dict.fromkeys([rom_path.stem, title, rom_path.stem.replace("_", " ")]) if n]
    for root in roots:
        for folder in (root / system_id, root):
            if folder not in cache:
                cache[folder] = _dir_index(folder)
            idx = cache[folder]
            if not idx:
                continue
            for name in names:
                for ext in _IMG_EXT:
                    hit = idx.get(f"{name}.{ext}".lower())
                    if hit:
                        return str(folder / hit)
    return ""


def load_metadata(path: Path | None = None) -> dict:
    """Optional ~/.local/share/atari/metadata.json: {"Game title or game id": {"genre": "...", "players": "1-2",
    "release": "1982", "rating": 4.5}}. Keys are matched case-insensitively. Missing/broken file = {}."""
    path = path or paths.metadata_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k).lower(): v for k, v in data.items() if isinstance(v, dict)}


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


def rom_missing(cfg: Config, sc, home: Path | None = None) -> str:
    """appinstall target ("id" or "id|core") for a console whose emulator is not installed; '' when it is ready or unknown."""
    if sc.command.strip():
        return ""
    ch = emulators.choose(cfg, sc, home)
    if ch is None or ch.ready:
        return ""
    if not ch.how:
        return ch.emu.id if (ch.emu.flatpak or ch.emu.apt) else ""
    if ch.emu.id == "retroarch" and ch.core:
        return f"retroarch|{ch.core}"
    return ""


def build_library(cfg: Config, home: Path | None = None, covers_root: Path | None = None,
                  mounts_file: str = "/proc/mounts", metadata: dict | None = None) -> LibraryResult:
    res = LibraryResult()
    meta = load_metadata() if metadata is None else metadata

    def meta_for(gid: str, title: str) -> dict:
        return meta.get(gid.lower()) or meta.get(title.lower()) or {}

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
            # Steam's own local library cache first; pictures Code downloaded (Settings > Download covers) after
            cover = steam.find_art(scan.root, g.appid) or covers_mod.find_downloaded_steam_art(g.appid, "cover", covers_root)
            header = (steam.find_header(scan.root, g.appid)
                      or covers_mod.find_downloaded_steam_art(g.appid, "header", covers_root))
            res.games.append(Game(
                gid=f"steam:{g.appid}", title=g.name, platform=STEAM, platform_name="Steam",
                cover=cover, steam_appid=g.appid, note=note,
                header=header, added=g.added,
                meta=meta_for(f"steam:{g.appid}", g.name)))
    res.steam_note = steam_status_text(res.steam_scan, cfg.steam_enabled)

    cover_cache: dict = {}
    for sc in cfg.systems.values():
        if not sc.roms:
            continue
        miss = rom_missing(cfg, sc, home)
        try:
            found = roms.scan_system(sc.roms, sc.extensions, sc.id)
        except Exception as exc:
            print(f"[atari] ROM scan failed for {sc.id}: {exc}")
            found = []
        res.rom_counts[sc.id] = len(found)
        for r in found:
            gid = f"rom:{sc.id}:{os.path.realpath(r.path)}"
            cover = find_custom_cover(sc.id, r.path, covers_root, r.title, cover_cache)
            res.games.append(Game(
                gid=gid, title=r.title, platform=sc.id, platform_name=sc.name, cover=cover,
                rom_path=str(r.path), header=cover, added=r.mtime, meta=meta_for(gid, r.title),
                missing=miss,
                note=("PS3 installer package: Play opens RPCS3's install window."
                      if r.path.suffix.lower() == ".pkg" else (emulators.SYSTEM_BY_ID[sc.id].note if sc.id in emulators.SYSTEM_BY_ID else ""))))
    # "PC Apps / Stores": one always-visible entry per app (Roblox, Heroic, Lutris, ...)
    for app in apps.APP_DEFS:
        ready, _text = apps.app_status(cfg, app, home)
        plat, pname = ((webapps.STREAMING, webapps.STREAMING_NAME) if app.group == "streaming"
                       else (apps.APPS, apps.APPS_NAME))
        res.games.append(Game(gid=app.gid, title=app.title, platform=plat, platform_name=pname,
                              note=app.note if ready else apps.install_hint(app), missing="" if ready else app.id))
    # the music Studio: one tile that opens the Studio screen
    res.games.append(Game(gid="studio:open", title="Hoodlum Asylum Studio", platform="studio", platform_name="Studio",
                          note="Make a beat, record your voice and share it. Press Play to open the Studio."))
    # "Tools": the screen recorder and the recordings player
    rec_missing = "" if (shutil.which("ffmpeg") or shutil.which("wf-recorder")) else "ffmpeg"
    res.games.append(Game(gid="tool:record", title="Record screen (F9)", platform="tools", platform_name="Tools",
                          missing=rec_missing,
                          note="Press Play to start or stop recording the whole screen to an MP4 in ~/Videos/Atari Recordings. "
                               "F9 (or Guide + X on a controller) does the same while a game is full screen."))
    res.games.append(Game(gid="tool:recordings", title="Recordings", platform="tools", platform_name="Tools",
                          note="Your screen recordings. Press Play to pick one and watch it (mpv)."))
    # "Free Games": hand-checked free-to-play games that run on Linux
    inst = {g.steam_appid for g in res.games if g.platform == STEAM and g.steam_appid}
    steam_ok = bool(res.steam_scan.root) or appinstall.is_installed(appinstall.TARGETS["steam"], home)
    for fg in freegames.GAMES:
        have = (fg.kind == "steam" and fg.ref in inst) or (fg.kind == "flatpak" and emulators.flatpak_installed(fg.ref, home))
        art = fg.kind == "steam"
        cv = (steam.find_art(res.steam_scan.root, fg.ref) or covers_mod.find_downloaded_steam_art(fg.ref, "cover", covers_root)) if art else ""
        hd = (steam.find_header(res.steam_scan.root, fg.ref) or covers_mod.find_downloaded_steam_art(fg.ref, "header", covers_root)) if art else ""
        miss = ("steam" if not steam_ok else "") if fg.kind == "steam" else (
            f"fp:{fg.ref}" if fg.kind == "flatpak" and not have else "")
        res.games.append(Game(gid=fg.gid, title=fg.title, platform=freegames.FREE, platform_name=freegames.FREE_NAME,
                              steam_appid=fg.ref if art else "", cover=cv, header=hd, missing=miss,
                              note=f"{fg.badge}. {fg.why}" + ("  Installed - press Play." if have else
                                    ("  Press Play to install it (free)." if fg.kind != "info" else "")),
                              meta={"genre": fg.genre} if fg.genre else {}))
    # "Streaming & Social": web apps that open in a browser window
    for wa in webapps.WEBAPPS:
        ready, text = webapps.status(cfg, wa, home)
        res.games.append(Game(gid=wa.gid, title=wa.title, platform=webapps.STREAMING, platform_name=webapps.STREAMING_NAME,
                              note=(wa.note + " " + text).strip() if ready else text, missing="" if ready else "chrome"))
    # Windows games you added with "Add Windows game"
    for wg in windows.load_games():
        cover = wg.cover if wg.cover and Path(wg.cover).is_file() else ""
        res.games.append(Game(gid=wg.gid, title=wg.name, platform=windows.PLATFORM, platform_name=windows.PLATFORM_NAME,
                              cover=cover, header=cover, rom_path=wg.exe,
                              added=_mtime(wg.exe)))
    # games you installed through Heroic and Lutris (read from their own files, never changed)
    for finder in (apps.heroic_games, apps.lutris_games):
        try:
            found = finder(home)
        except Exception as exc:  # an odd file there must never break Code
            print(f"[atari] {finder.__name__} failed: {exc}")
            found = []
        for sg in found:
            res.games.append(Game(gid=sg.gid, title=sg.title, platform=sg.store, platform_name=sg.store_name,
                                  launch=sg.uri, added=sg.played))
    apply_icons(res.games, home)
    return res


def apply_icons(games: list, home: Path | None = None, icons_root: Path | None = None) -> None:
    """Give app tiles (web apps, PC apps, free games) their icon: the installed app's own, else the downloaded copy."""
    for g in games:
        if g.cover or g.rom_path or g.gid.partition(":")[0] not in ("web", "app", "free"):
            continue
        spec = icons.spec_for(g.gid)
        if spec is None:
            continue
        try:
            path, fit = icons.resolve(spec, home, icons_root)
        except Exception as exc:          # a strange icon folder must never break Code
            print(f"[atari] icon lookup failed for {g.gid}: {exc}")
            continue
        if path:
            g.cover = g.header = path
            g.fit = fit


def _mtime(path: str) -> float:
    try:
        return os.stat(path).st_mtime
    except OSError:
        return 0.0


def demo_library() -> LibraryResult:
    """Made-up games used for the screenshot / --demo. No real titles or art."""
    steam_titles = ["Cosmic Crawler", "Neon Pinball Deluxe", "Dungeon of Pixels", "Turbo Kart Rally",
                    "Lantern Valley", "Orbital Defense", "Mushroom Kingdom Builder", "Rust & Rails"]
    now = time.time()
    games = [Game(f"steam:{9000000 + i}", t, STEAM, "Steam", steam_appid=str(9000000 + i),
                  added=now - i * 3600) for i, t in enumerate(steam_titles)]
    retro = {
        "atari2600": ("Atari 2600", ["Blocky Breakout", "Desert Raider", "Sky Gunner", "Maze Muncher"]),
        "atari7800": ("Atari 7800", ["Space Harrier Jr", "Pixel Hockey"]),
        "nes": ("Nintendo NES", ["Plumber Panic", "Ninja Frogs", "Castle Quest"]),
        "snes": ("Super Nintendo", ["Cloud Racers", "Dragon Tamer"]),
        "genesis": ("Sega Genesis", ["Hedgehog Hustle", "Street Brawlers"]),
        "ps1": ("PlayStation", ["Turbo Kart Zero", "Dino Dash"]),
        "ps2": ("PlayStation 2", ["Midnight Racer", "Sword of Dawn"]),
        "dreamcast": ("Dreamcast", ["Orbit Fighters", "Lantern Quest"]),
        "gamecube": ("GameCube", ["Island Hoppers", "Block Party"]),
        "gba": ("Game Boy Advance", ["Tiny Tactics", "Pocket Fishing"]),
    }
    counts = {}
    for sid, (name, titles) in retro.items():
        counts[sid] = len(titles)
        games += [Game(f"rom:{sid}:/demo/{t}", t, sid, name, rom_path=f"/demo/{t}", added=now - 86400 * len(games))
                  for t in titles]
    scan = steam.SteamScan(root=Path("/demo/Steam"))
    return LibraryResult(games, scan, counts, "Demo mode - these games are made up.")
