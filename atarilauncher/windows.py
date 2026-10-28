"""Windows games: add a .exe (or a .zip / .7z with one inside) and start it through umu / Proton / Wine.

Each game gets its own Wine prefix under ~/.local/share/atari/prefixes/<name>/. Code stores the list of Windows games in
~/.local/share/atari/windows_games.json (your own file, written only when you add or remove a game).

Runner order (the simplest that is robust): umu-launcher's ``umu-run`` -> a Proton found on this PC (ProtonUp-Qt's
GE-Proton, or Steam's Proton) -> ``wine``. Nothing here downloads games; "Dreams of Saturn"-style fan games are fetched by the
user from the author's own page.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import tarfile
import threading
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import emulators, paths, steam

PLATFORM = "windows"
PLATFORM_NAME = "Windows / PC"
ARCHIVE_EXT = (".zip", ".7z", ".rar", ".tar.gz", ".tgz", ".tar.xz", ".tar.bz2")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")
PROTONUP_ID = "net.davidotek.pupgui2"          # ProtonUp-Qt on Flathub
UMU_HINT = ("Windows games need a helper program. Easiest: Settings > Emulators > Install emulators and apps "
            "(it installs umu-launcher, Wine and ProtonUp-Qt for you).")


class WinError(Exception):
    """A problem with a plain-English message."""


# ------------------------------------------------------------------ names and places
def slugify(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", name.strip()).strip("-").lower()
    return s or "game"


def games_file() -> Path:
    return paths.data_dir() / "windows_games.json"


def prefixes_dir() -> Path:
    return paths.data_dir() / "prefixes"


def games_dir(home: Path | None = None) -> Path:
    return (home or Path.home()) / "Games" / "Atari" / "windows"


def clean_name(stem: str) -> str:
    """'Dreams_of_Saturn_v1.2.zip' -> 'Dreams of Saturn v1.2'."""
    s = stem
    for ext in ARCHIVE_EXT + (".exe",):
        if s.lower().endswith(ext):
            s = s[: -len(ext)]
    s = re.sub(r"[_]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" -")
    return s or "Windows game"


# ------------------------------------------------------------------ the stored list
@dataclass
class WinGame:
    id: str
    name: str
    exe: str
    cover: str = ""

    @property
    def gid(self) -> str:
        return f"win:{self.id}"


def load_games() -> list[WinGame]:
    try:
        data = json.loads(games_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for g in data.get("games", []) if isinstance(data, dict) else []:
        if isinstance(g, dict) and g.get("id") and g.get("exe"):
            out.append(WinGame(str(g["id"]), str(g.get("name") or g["id"]), str(g["exe"]), str(g.get("cover") or "")))
    return out


def _save(games: list[WinGame]) -> None:
    f = games_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f.name + ".tmp")
    tmp.write_text(json.dumps({"games": [g.__dict__ for g in games]}, indent=2), encoding="utf-8")
    tmp.replace(f)


def add_game(name: str, exe: str, cover: str = "") -> WinGame:
    games = load_games()
    base = slugify(name)
    ids = {g.id for g in games}
    gid, n = base, 2
    while gid in ids:
        gid, n = f"{base}-{n}", n + 1
    if cover:  # copy the picture next to Code's own covers so it survives the original being moved
        try:
            dest = paths.user_covers_dir() / "windows" / (gid + Path(cover).suffix.lower())
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cover, dest)
            cover = str(dest)
        except OSError:
            cover = ""
    g = WinGame(gid, name.strip() or "Windows game", exe, cover)
    games.append(g)
    _save(games)
    return g


def remove_game(gid: str) -> bool:
    """Forget a game in Code. Its files and Wine prefix are left alone."""
    games = load_games()
    keep = [g for g in games if g.gid != gid and g.id != gid]
    if len(keep) == len(games):
        return False
    _save(keep)
    return True


# ------------------------------------------------------------------ finding the right .exe
_SKIP = re.compile(r"(unins\d*|uninstall|crashhandler|crashpad|crash_?reporter|vc_?redist|vcredist|dxsetup|dxwebsetup|"
                   r"dotnet|ndp\d|oalinst|notification_helper|cefprocess|ue4prereq|directx|physx)", re.I)
_INSTALLER = re.compile(r"(setup|install)", re.I)


@dataclass
class ExeCandidate:
    path: Path
    rel: str
    size: int
    score: float = 0.0


def find_exes(folder: Path, max_depth: int = 4) -> list[ExeCandidate]:
    """Likely game programs in a folder, best guess first (Unity games: the .exe that has a <name>_Data folder next to it)."""
    folder = Path(folder)
    found: list[ExeCandidate] = []
    base_depth = len(folder.parts)
    for dirpath, dirnames, filenames in os.walk(folder, followlinks=False):
        depth = len(Path(dirpath).parts) - base_depth
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        if depth >= max_depth:
            dirnames[:] = []
        for fn in sorted(filenames):
            if not fn.lower().endswith(".exe") or _SKIP.search(fn):
                continue
            p = Path(dirpath) / fn
            try:
                size = p.stat().st_size
            except OSError:
                continue
            score = float(size) / (1 + depth * 0.5)
            if (Path(dirpath) / (p.stem + "_Data")).is_dir():
                score += 1e12                       # Unity standalone
            if (Path(dirpath) / (p.stem + "_Data")).is_dir() is False and (Path(dirpath) / "UnityPlayer.dll").is_file():
                score += 5e11
            if _INSTALLER.search(fn):
                score *= 0.01
            found.append(ExeCandidate(p, str(p.relative_to(folder)), size, score))
    return sorted(found, key=lambda c: (-c.score, c.rel.lower()))


# ------------------------------------------------------------------ archives
def is_archive(path: str | Path) -> bool:
    return str(path).lower().endswith(ARCHIVE_EXT)


def unique_dir(base: Path) -> Path:
    if not base.exists() or not any(base.iterdir()):
        return base
    n = 2
    while (base.parent / f"{base.name} {n}").exists():
        n += 1
    return base.parent / f"{base.name} {n}"


def _inside(dest: Path, name: str) -> bool:
    root = dest.resolve()
    target = (dest / name).resolve()
    return target == root or str(target).startswith(str(root) + os.sep)


def extract_archive(archive: Path, dest: Path, progress: Callable[[int, int], None] | None = None,
                    cancel: threading.Event | None = None, which=shutil.which) -> None:
    """Unpack into dest. zip and tar via Python, everything else (7z, rar) through the 7z program if it is installed."""
    archive, dest = Path(archive), Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    low = archive.name.lower()
    try:
        if low.endswith(".zip"):
            with zipfile.ZipFile(archive) as zf:
                infos = zf.infolist()
                for i, info in enumerate(infos):
                    if cancel is not None and cancel.is_set():
                        raise WinError("Cancelled.")
                    if not _inside(dest, info.filename):
                        raise WinError("That archive contains an unsafe path, so it was not opened.")
                    zf.extract(info, dest)
                    if progress:
                        progress(i + 1, len(infos))
            return
        if low.endswith((".tar.gz", ".tgz", ".tar.xz", ".tar.bz2")):
            with tarfile.open(archive) as tf:
                members = [m for m in tf.getmembers() if (m.isdir() or m.isreg()) and _inside(dest, m.name)]
                for i, m in enumerate(members):
                    if cancel is not None and cancel.is_set():
                        raise WinError("Cancelled.")
                    tf.extract(m, dest)
                    if progress:
                        progress(i + 1, len(members))
            return
    except (zipfile.BadZipFile, tarfile.TarError, OSError, EOFError) as exc:
        raise WinError(f"That archive could not be opened ({exc}). Is the download complete?")
    seven = next((which(x) for x in ("7z", "7zz", "7za", "7zr") if which(x)), None)
    if not seven:
        raise WinError("Code needs the 7-Zip program to open this kind of archive. Use Settings > Emulators > "
                       "Install emulators and apps, or run:  sudo apt install p7zip-full")
    if progress:
        progress(0, 0)
    try:
        r = subprocess.run([seven, "x", "-y", f"-o{dest}", str(archive)], stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=3600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WinError(f"7-Zip could not run ({exc}).")
    if r.returncode != 0:
        raise WinError("7-Zip could not open that archive (it may be damaged or need a password).")
    if progress:
        progress(1, 1)


# ------------------------------------------------------------------ runners
@dataclass
class Runner:
    kind: str                 # custom | umu | proton | wine | "" (none)
    cmd: list[str] = field(default_factory=list)
    label: str = ""
    steam_root: str = ""


def umu_path(home: Path | None = None, which=shutil.which) -> str:
    p = which("umu-run")
    if p:
        return p
    cand = (home or Path.home()) / ".local/bin/umu-run"
    return str(cand) if cand.exists() and os.access(cand, os.X_OK) else ""


def _version_key(name: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", name)) or (0,)


def find_proton(home: Path | None = None, cfg_steam_root: str = "") -> tuple[str, str]:
    """(path to the 'proton' script, Steam root) - GE-Proton (ProtonUp-Qt) first, then Steam's own Proton."""
    home = home or Path.home()
    roots: list[Path] = []
    try:
        roots = steam.steam_root_candidates(home)
    except Exception:
        pass
    if cfg_steam_root:
        roots.insert(0, Path(cfg_steam_root).expanduser())
    seen, uniq = set(), []
    for r in roots:
        try:
            key = r.resolve()
        except OSError:
            continue
        if key not in seen and r.is_dir():
            seen.add(key)
            uniq.append(r)
    ge, official = [], []
    for root in uniq:
        tools = root / "compatibilitytools.d"
        if tools.is_dir():
            for d in tools.iterdir():
                if (d / "proton").is_file() and ("proton" in d.name.lower()):
                    ge.append((d.name, str(d / "proton"), str(root)))
        common = root / "steamapps" / "common"
        if common.is_dir():
            for d in common.iterdir():
                if d.name.lower().startswith("proton") and (d / "proton").is_file():
                    official.append((d.name, str(d / "proton"), str(root)))
    for pool in (ge, [o for o in official if "experimental" not in o[0].lower()], official):
        if pool:
            name, script, root = max(pool, key=lambda t: _version_key(t[0]))
            return script, root
    return "", ""


def find_runner(cfg=None, home: Path | None = None, which=shutil.which) -> Runner:
    custom = (cfg.emulator_commands.get("windows") or "").strip() if cfg is not None else ""
    if custom:
        return Runner("custom", shlex.split(custom), "your command")
    umu = umu_path(home, which)
    if umu:
        return Runner("umu", [umu], "umu-launcher")
    script, root = find_proton(home, getattr(cfg, "steam_root", "") if cfg is not None else "")
    if script:
        return Runner("proton", [script, "run"], "Proton (" + Path(script).parent.name + ")", root)
    wine = which("wine")
    if wine:
        return Runner("wine", [wine], "Wine")
    return Runner("", [], "")


def runner_status(cfg=None, home: Path | None = None, which=shutil.which) -> tuple[bool, str]:
    r = find_runner(cfg, home, which)
    return (True, r.label) if r.kind else (False, UMU_HINT)


def build_launch(cfg, game: WinGame, home: Path | None = None, which=shutil.which,
                 prefix_root: Path | None = None) -> tuple[list[str], dict[str, str], Path, str]:
    """(command, extra environment, working folder, runner label). Raises WinError with plain advice."""
    exe = Path(game.exe)
    if not exe.is_file():
        raise WinError("The game's .exe is missing. Is the drive plugged in, or was the folder moved? "
                       "Use Options > Fix my game for help, or add the game again.")
    r = find_runner(cfg, home, which)
    if not r.kind:
        raise WinError(UMU_HINT)
    prefix = (prefix_root or prefixes_dir()) / slugify(game.id)
    prefix.mkdir(parents=True, exist_ok=True)
    env: dict[str, str] = {}
    if r.kind == "umu":
        env = {"WINEPREFIX": str(prefix), "GAMEID": "umu-0", "PROTONPATH": os.environ.get("PROTONPATH", "GE-Proton")}
        cmd = r.cmd + [str(exe)]
    elif r.kind == "proton":
        env = {"STEAM_COMPAT_DATA_PATH": str(prefix), "STEAM_COMPAT_CLIENT_INSTALL_PATH": r.steam_root}
        cmd = r.cmd + [str(exe)]
    elif r.kind == "wine":
        env = {"WINEPREFIX": str(prefix), "WINEDEBUG": "-all"}
        cmd = r.cmd + [str(exe)]
    else:  # custom: {exe} / {prefix} words, else the exe is appended
        text = " ".join(shlex.quote(c) for c in r.cmd)
        if "{exe}" in text:
            cmd = shlex.split(text.replace("{exe}", shlex.quote(str(exe))).replace("{prefix}", shlex.quote(str(prefix))))
        else:
            cmd = r.cmd + [str(exe)]
        env = {"WINEPREFIX": str(prefix), "STEAM_COMPAT_DATA_PATH": str(prefix)}
    return cmd, env, exe.parent, r.label
