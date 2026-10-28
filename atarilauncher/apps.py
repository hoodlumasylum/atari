"""PC apps and stores shown in Code's "PC Apps / Stores" section, and games imported from Heroic and Lutris.

Every app is described by one AppDef (a Flathub id plus how to find a native install), so adding another is one line.
Code only *starts* these programs; you sign in to each store / service yourself, inside its own window.

Roblox has no official Linux client. "Sober" (Flatpak org.vinegarhq.Sober, VinegarHQ) is an unofficial community runner
that can break after a Roblox update. Wine / Vinegar do not work (Roblox blocks them), so Code does not try them.
"""
from __future__ import annotations

import json
import shlex
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import emulators

APPS = "apps"                       # platform id of the "PC Apps / Stores" section
NON_GAME = ("apps", "streaming", "free", "studio", "tools")    # tiles that are not games: hidden from "All Games" and the game counts
APPS_NAME = "PC Apps / Stores"
HEROIC = "heroic"
LUTRIS = "lutris"


@dataclass(frozen=True)
class AppDef:
    id: str
    title: str
    flatpak: str                    # Flathub application id (verified on flathub.org)
    exes: tuple = ()                # program names when installed natively
    note: str = ""                  # shown on the tile / Emulators page
    apt: str = ""                   # apt package name when there is one
    group: str = "apps"             # which tile it lives on: "apps" (PC Apps) or "streaming" (Streaming & Social)
    background: bool = False        # keeps running behind Code (music): Esc twice / Guide+B brings Code back and leaves it playing

    @property
    def name(self) -> str:          # lets the installer treat apps like emulators
        return self.title

    @property
    def gid(self) -> str:
        return f"app:{self.id}"


APP_DEFS: list[AppDef] = [
    AppDef("steam", "Steam", "com.valvesoftware.Steam", ("steam",),
           "Valve's game store. Press Install if it is missing; then sign in to your own Steam account. Installed games show up in Code "
           "(press Rescan Steam in Settings after installing one).", apt="steam-installer"),
    AppDef("roblox", "Roblox", "org.vinegarhq.Sober", ("sober",),
           "Runs through Sober, an unofficial community app (not made by Roblox). It can break after a Roblox "
           "update. The first start helps you install Roblox; sign in to your own Roblox account there."),
    AppDef("heroic", "Heroic Games Launcher", "com.heroicgameslauncher.hgl", ("heroic",),
           "Epic, GOG and Amazon games. Sign in to your own accounts inside Heroic; installed games show up in Code."),
    AppDef("lutris", "Lutris", "net.lutris.Lutris", ("lutris",),
           "Runs many Windows and retro games. Installed Lutris games show up in Code."),
    AppDef("bottles", "Bottles", "com.usebottles.bottles", ("bottles",),
           "Runs Windows programs and games."),
    AppDef("itch", "itch.io", "io.itch.itch", ("itch",),
           "Indie games from itch.io. Sign in to your own itch account inside the app."),
    AppDef("prism", "Prism Launcher (Minecraft)", "org.prismlauncher.PrismLauncher", ("prismlauncher",),
           "Minecraft launcher. Add your own Microsoft account (you need to own Minecraft) inside Prism."),
    AppDef("minecraft", "Minecraft Launcher", "com.mojang.Minecraft", ("minecraft-launcher",),
           "Unofficial Flatpak of Mojang's own launcher. Sign in with your own Microsoft account."),
    AppDef("protonup", "ProtonUp-Qt (Proton manager)", "net.davidotek.pupgui2", ("protonup-qt",),
           "Installs and updates Proton-GE / Wine versions, which Windows games run on."),
    AppDef("kodi", "Kodi (media centre)", "tv.kodi.Kodi", ("kodi",),
           "Plays your own videos, music and photos; add-ons are up to you.", apt="kodi", group="streaming"),
    AppDef("transmission", "Transmission (torrent client)", "com.transmissionbt.Transmission",
           ("transmission-gtk", "transmission-qt"),
           "Open-source torrent downloader. Code does not preload any torrents, trackers or sites: you add your own .torrent file or "
           "magnet link, and only for files you own or may legally share. Saves to ~/Downloads; Options > Downloads moves finished "
           "files into your games.", apt="transmission-gtk"),
    AppDef("obs", "OBS Studio (live streaming)", "com.obsproject.Studio", ("obs",),
           "Free, open-source streaming and recording program for Twitch, YouTube Live, TikTok LIVE and others. Options > Go Live starts "
           "it with a ready screen-capture scene; you add your own stream key. Linux has no 'Game Capture' - it captures the screen.",
           apt="obs-studio"),
    AppDef("spotify", "Spotify", "com.spotify.Client", ("spotify",),
           "Spotify's own app (a Spotify account is needed; free accounts have ads). It keeps playing behind Code: press Esc twice "
           "(or Guide + B) to come back, and use the music buttons in the top bar (they need playerctl). The Flathub package is "
           "community-maintained, not made by Spotify or Code.", group="streaming", background=True),
    AppDef("moonlight", "Moonlight (game streaming)", "com.moonlight_stream.Moonlight", ("moonlight", "moonlight-qt"),
           "Streams games from another PC running Sunshine or GeForce Experience."),
]
BY_ID = {a.id: a for a in APP_DEFS}
# installed by the install-everything script, but not shown as tiles
HELPERS: list[AppDef] = [
    AppDef("wine", "Wine (Windows compatibility)", "", ("wine",), "Runs Windows programs (fallback for Windows games).",
           apt="wine"),
    AppDef("chrome", "Google Chrome (for YouTube, Netflix and other web apps)", "com.google.Chrome",
           ("google-chrome-stable", "google-chrome"), "Streaming web apps open in it. Has Widevine for Netflix & co."),
    AppDef("playerctl", "playerctl (music buttons in the top bar)", "", ("playerctl",),
           "Lets Code's top bar play / pause / skip Spotify and other players. Small and free.", apt="playerctl"),
    AppDef("antimicrox", "AntiMicroX (optional: gamepad as mouse)", "io.github.antimicrox.antimicrox", ("antimicrox",),
           "Lets a controller move the mouse inside web apps. Optional."),
    AppDef("ffmpeg", "FFmpeg (screen recorder)", "", ("ffmpeg",), "Records the screen to an MP4 file (F9).", apt="ffmpeg"),
    AppDef("7zip", "7-Zip (opens .7z / .rar game archives)", "", ("7z", "7zz", "7za"), "Opens .7z and .rar archives.",
           apt="p7zip-full"),
    AppDef("umu", "umu-launcher (runs Windows games with Proton)", "", ("umu-run",),
           "Code's first choice for Windows games. Installed from its official GitHub release."),
]


def install_hint(app: AppDef) -> str:
    return (f"{app.title} is not installed yet. Use Settings > Emulators > Install emulators and apps "
            f"(or: flatpak install flathub {app.flatpak}).")


def app_command(cfg, app: AppDef, home: Path | None = None,
                which: Callable[[str], str | None] = shutil.which) -> tuple[list[str], str]:
    """(command, how): how is 'custom' | 'flatpak' | 'native' | '' (not installed; command is the best guess).
    A command in the config file ([emulators] <id> = "...") always wins."""
    custom = (cfg.emulator_commands.get(app.id) or "").strip()
    if custom:
        return shlex.split(custom), "custom"
    if emulators.flatpak_installed(app.flatpak, home):
        return ["flatpak", "run", app.flatpak], "flatpak"
    for exe in app.exes:
        if which(exe):
            return [exe], "native"
    return ["flatpak", "run", app.flatpak], ""


def app_status(cfg, app: AppDef, home: Path | None = None, which=shutil.which) -> tuple[bool, str]:
    cmd, how = app_command(cfg, app, home, which)
    if how:
        return True, app.title + {"flatpak": " (Flatpak)", "custom": " (your command)"}.get(how, "")
    return False, install_hint(app)


# ------------------------------------------------------------------ imported games
@dataclass
class StoreGame:
    gid: str
    title: str
    store: str            # "heroic" | "lutris"
    store_name: str
    uri: str              # heroic://launch/<runner>/<id>  |  lutris:rungameid/<id>
    played: float = 0.0


def _json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def heroic_config_dirs(home: Path) -> list[Path]:
    return [home / ".var/app/com.heroicgameslauncher.hgl/config/heroic", home / ".config/heroic"]


def _titles_from_cache(base: Path) -> dict[str, str]:
    """{app id: title} from Heroic's cached store libraries (best effort; formats differ per store)."""
    out: dict[str, str] = {}
    for name in ("legendary_library.json", "gog_library.json", "nile_library.json"):
        data = _json(base / "store_cache" / name)
        items = []
        if isinstance(data, dict):
            for key in ("library", "games"):
                if isinstance(data.get(key), list):
                    items = data[key]
        elif isinstance(data, list):
            items = data
        for g in items:
            if isinstance(g, dict):
                gid = g.get("app_name") or g.get("appName") or g.get("id")
                if gid and g.get("title"):
                    out[str(gid)] = str(g["title"])
    return out


def _iter_installed(runner: str, data) -> list[tuple[str, str, str]]:
    """[(app id, title or '', install path)] from one installed.json (dict of games, {'installed': [...]}, or a list)."""
    rows: list = []
    if isinstance(data, dict):
        if isinstance(data.get("installed"), list):
            rows = data["installed"]
        elif isinstance(data.get("games"), list):
            rows = data["games"]
        else:
            rows = [dict(v, app_name=v.get("app_name") or k) for k, v in data.items() if isinstance(v, dict)]
    elif isinstance(data, list):
        rows = data
    out = []
    for g in rows:
        if not isinstance(g, dict):
            continue
        aid = g.get("app_name") or g.get("appName") or g.get("id")
        if not aid:
            continue
        path = str(g.get("install_path") or g.get("path") or "")
        out.append((str(aid), str(g.get("title") or ""), path))
    return out


def heroic_games(home: Path | None = None) -> list[StoreGame]:
    """Installed Heroic games (Epic / GOG / Amazon / added by hand), read from Heroic's own JSON files."""
    home = home or Path.home()
    out: list[StoreGame] = []
    seen: set[str] = set()
    for base in heroic_config_dirs(home):
        if not base.is_dir():
            continue
        titles = _titles_from_cache(base)
        files = {
            "legendary": [base / "legendaryConfig/legendary/installed.json"],
            "gog": [base / "gog_store/installed.json"],
            "nile": [base / "nile_config/nile/installed.json"],
            "sideload": [base / "sideload_apps/library.json"],
        }
        for runner, paths_ in files.items():
            for f in paths_:
                data = _json(f) if f.is_file() else None
                if data is None:
                    continue
                for aid, title, path in _iter_installed(runner, data):
                    gid = f"heroic:{runner}:{aid}"
                    if gid in seen:
                        continue
                    seen.add(gid)
                    name = title or titles.get(aid) or (Path(path).name if path else "") or aid
                    out.append(StoreGame(gid, name, HEROIC, "Heroic (Epic / GOG)", f"heroic://launch/{runner}/{aid}"))
    return out


def lutris_dbs(home: Path) -> list[Path]:
    return [home / ".var/app/net.lutris.Lutris/data/lutris/pga.db", home / ".local/share/lutris/pga.db"]


def lutris_games(home: Path | None = None) -> list[StoreGame]:
    """Installed Lutris games from its pga.db (read only). Steam entries are skipped: Code already lists Steam."""
    home = home or Path.home()
    out: list[StoreGame] = []
    seen: set[str] = set()
    for db in lutris_dbs(home):
        if not db.is_file():
            continue
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
            try:
                rows = con.execute("SELECT id, name, runner, lastplayed FROM games "
                                   "WHERE installed = 1 AND (hidden IS NULL OR hidden = 0)").fetchall()
            finally:
                con.close()
        except sqlite3.Error:
            continue
        for gid, name, runner, last in rows:
            if (runner or "") == "steam" or not name:
                continue
            key = f"lutris:{gid}"
            if key in seen:
                continue
            seen.add(key)
            out.append(StoreGame(key, str(name), LUTRIS, "Lutris", f"lutris:rungameid/{gid}",
                                 float(last or 0)))
    return out


def store_command(cfg, game_uri: str, store: str, home: Path | None = None) -> tuple[list[str], str]:
    cmd, how = app_command(cfg, BY_ID[store], home)
    return cmd + [game_uri], how
