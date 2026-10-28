"""Find Steam on Linux and list installed games (read-only; never touches Steam's files)."""
from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import vdf

NTFS_FSTYPES = {"ntfs", "ntfs3", "fuseblk", "fuse.ntfs-3g", "fuse.ntfs3g", "lowntfs-3g"}

# Things Steam installs that are not games.
SKIP_APPIDS = {"228980", "1070560", "1391110", "1493710", "1628350", "1826330", "2180100"}
SKIP_NAME_PREFIXES = ("Proton ", "Steam Linux Runtime", "Steamworks Common", "Proton-")


def steam_root_candidates(home: Path | None = None) -> list[Path]:
    home = home or Path.home()
    return [
        home / ".steam" / "steam",
        home / ".steam" / "root",
        home / ".local" / "share" / "Steam",
        home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",
        home / ".var" / "app" / "com.valvesoftware.Steam" / "data" / "Steam",
        home / "snap" / "steam" / "common" / ".local" / "share" / "Steam",
    ]


def find_steam_root(home: Path | None = None, override: str = "") -> Path | None:
    """Return the first candidate that really looks like a Steam install."""
    cands = [Path(override).expanduser()] if override else steam_root_candidates(home)
    for cand in cands:
        try:
            if (cand / "steamapps").is_dir() or (cand / "config" / "libraryfolders.vdf").is_file():
                return Path(os.path.realpath(cand))
        except OSError:
            continue
    return None


def is_flatpak_root(root: Path) -> bool:
    return "com.valvesoftware.Steam" in str(root)


def parse_libraryfolders(path: Path) -> list[str]:
    """Return library paths from libraryfolders.vdf (handles old and new formats)."""
    data = vdf.load(path)
    node = data.get("libraryfolders", data)
    paths: list[str] = []
    for key, val in node.items():
        if not key.isdigit():
            continue
        if isinstance(val, dict):
            p = val.get("path")
            if p:
                paths.append(p)
        elif isinstance(val, str) and val:  # old format: "1" "/path"
            paths.append(val)
    return paths


def read_mounts(mounts_file: str = "/proc/mounts") -> list[tuple[str, str]]:
    """List of (mountpoint, fstype)."""
    out = []
    try:
        with open(mounts_file, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) >= 3:
                    mp = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), parts[1])
                    out.append((mp, parts[2]))
    except OSError:
        pass
    return out


LINUX_FS = {"ext4", "ext3", "ext2", "btrfs", "xfs", "f2fs"}
BAD_FS = NTFS_FSTYPES | {"exfat", "vfat", "msdos"}


def drive_advice(mounts: list[tuple[str, str]] | None = None, home: Path | None = None) -> list[dict]:
    """Where to keep Steam games: one entry per mounted drive that matters, {path, fs, ok, text}.
    Linux file systems (ext4, btrfs, xfs) are right for games; NTFS / exFAT / FAT drives (a Windows drive or a
    USB stick) make Proton games fail or run badly."""
    mounts = read_mounts() if mounts is None else mounts
    home = home or Path.home()
    roots = ("/media", "/mnt", "/run/media")
    out: list[dict] = []
    seen: set[str] = set()
    for mp, fs in mounts:
        mp_n = mp.rstrip("/") or "/"
        user_drive = mp_n.startswith(roots) or mp_n == str(home) or mp_n == "/home"
        if fs not in LINUX_FS | BAD_FS or mp_n in seen:
            continue
        if not user_drive and mp_n != "/":
            continue
        seen.add(mp_n)
        label = "your main disk" if mp_n in ("/", "/home", str(home)) else mp_n
        if fs in LINUX_FS:
            out.append({"path": mp_n, "fs": fs, "ok": True,
                        "text": f"{label} ({fs}): good for Steam games."})
        else:
            out.append({"path": mp_n, "fs": fs, "ok": False,
                        "text": f"{label} ({fs.upper()}): avoid for Steam games - Windows / USB-style drives often make Proton games fail. "
                                "Keep games on a Linux (ext4) drive."})
    out.sort(key=lambda d: (not d["ok"], d["path"]))
    return out


def filesystem_of(path: Path, mounts: list[tuple[str, str]]) -> str:
    real = os.path.realpath(path)
    best, best_len = "", -1
    for mp, fs in mounts:
        norm = mp.rstrip("/") or "/"
        if real == norm or real.startswith(norm.rstrip("/") + "/") or norm == "/":
            if len(norm) > best_len:
                best, best_len = fs, len(norm)
    return best


@dataclass
class Library:
    path: Path
    exists: bool
    fstype: str = ""
    on_ntfs: bool = False
    game_count: int = 0


@dataclass
class SteamGame:
    appid: str
    name: str
    install_dir: str
    library: Path
    size_on_disk: int = 0
    on_ntfs: bool = False
    has_compatdata: bool = False  # a Proton prefix exists => runs through Proton
    added: float = 0.0  # when the game's manifest was created/modified (used for "Recently added")


@dataclass
class SteamScan:
    root: Path | None = None
    flatpak: bool = False
    libraries: list[Library] = field(default_factory=list)
    games: list[SteamGame] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return self.root is not None

    @property
    def missing_libraries(self) -> list[Library]:
        return [lib for lib in self.libraries if not lib.exists]


def parse_appmanifest(path: Path) -> dict | None:
    try:
        state = vdf.load(path).get("appstate")
    except (OSError, vdf.VDFError):
        return None
    if not isinstance(state, dict) or not state.get("appid"):
        return None
    return state


def _int(v, default=0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def scan_library_dir(lib_path: Path, on_ntfs: bool = False) -> list[SteamGame]:
    games = []
    steamapps = lib_path / "steamapps"
    for manifest in sorted(glob.glob(str(steamapps / "appmanifest_*.acf"))):
        st = parse_appmanifest(Path(manifest))
        if not st:
            continue
        appid = str(st["appid"])
        name = st.get("name") or st.get("installdir") or f"App {appid}"
        flags = _int(st.get("stateflags"))
        if not flags & 4:  # 4 = fully installed
            continue
        if appid in SKIP_APPIDS or name.startswith(SKIP_NAME_PREFIXES):
            continue
        try:
            added = os.stat(manifest).st_mtime
        except OSError:
            added = 0.0
        games.append(
            SteamGame(
                appid=appid,
                name=name,
                install_dir=st.get("installdir", ""),
                library=lib_path,
                size_on_disk=_int(st.get("sizeondisk")),
                on_ntfs=on_ntfs,
                has_compatdata=(steamapps / "compatdata" / appid).is_dir(),
                added=added,
            )
        )
    return games


def scan_steam(home: Path | None = None, root_override: str = "", extra_libraries=(),
               mounts_file: str = "/proc/mounts") -> SteamScan:
    scan = SteamScan()
    root = find_steam_root(home, root_override)
    if root is None and not extra_libraries:
        return scan
    scan.root = root
    scan.flatpak = bool(root and is_flatpak_root(root))
    mounts = read_mounts(mounts_file)

    lib_paths: list[Path] = []
    if root:
        lib_paths.append(root)
        for vdf_path in (root / "steamapps" / "libraryfolders.vdf", root / "config" / "libraryfolders.vdf"):
            if vdf_path.is_file():
                try:
                    lib_paths += [Path(p) for p in parse_libraryfolders(vdf_path)]
                except (OSError, vdf.VDFError):
                    pass
    lib_paths += [Path(p).expanduser() for p in extra_libraries]

    seen_libs: set[str] = set()
    seen_apps: set[str] = set()
    for lp in lib_paths:
        key = os.path.realpath(lp)
        if key in seen_libs:
            continue
        seen_libs.add(key)
        exists = lp.is_dir()
        fs = filesystem_of(lp, mounts) if exists else ""
        lib = Library(path=lp, exists=exists, fstype=fs, on_ntfs=fs in NTFS_FSTYPES)
        if exists:
            for g in scan_library_dir(lp, lib.on_ntfs):
                if g.appid not in seen_apps:
                    seen_apps.add(g.appid)
                    scan.games.append(g)
                    lib.game_count += 1
        scan.libraries.append(lib)
    scan.games.sort(key=lambda g: g.name.lower())
    return scan


def find_art(root: Path | None, appid: str) -> str:
    """Path of the best portrait art in Steam's local cache ('' if none)."""
    if root is None:
        return ""
    cache = root / "appcache" / "librarycache"
    if not cache.is_dir():
        return ""
    wanted = ("library_600x900.jpg", "library_600x900_2x.jpg", "library_600x900.png",
              "header.jpg", "library_header.jpg")
    flat = [cache / f"{appid}_library_600x900.jpg", cache / f"{appid}_library_600x900_2x.jpg",
            cache / f"{appid}_header.jpg"]
    for p in flat:
        if p.is_file():
            return str(p)
    sub = cache / appid
    if sub.is_dir():
        for name in wanted:  # newer layout: <appid>/<hash>/<file> or <appid>/<file>
            direct = sub / name
            if direct.is_file():
                return str(direct)
            hits = sorted(glob.glob(str(sub / "*" / name)))
            if hits:
                return hits[0]
    return ""


def find_header(root: Path | None, appid: str) -> str:
    """Path of a wide banner image (header.jpg) in Steam's local cache ('' if none)."""
    if root is None:
        return ""
    cache = root / "appcache" / "librarycache"
    if not cache.is_dir():
        return ""
    for p in (cache / f"{appid}_header.jpg", cache / f"{appid}_library_header.jpg"):
        if p.is_file():
            return str(p)
    sub = cache / appid
    if sub.is_dir():
        for name in ("header.jpg", "library_header.jpg", "library_hero.jpg"):
            direct = sub / name
            if direct.is_file():
                return str(direct)
            hits = sorted(glob.glob(str(sub / "*" / name)))
            if hits:
                return hits[0]
    return ""


# ------------------------------------------------------------------ Big Picture
def _cmdlines(proc_root: str = "/proc"):
    try:
        entries = os.listdir(proc_root)
    except OSError:
        return
    for e in entries:
        if e.isdigit():
            try:
                with open(f"{proc_root}/{e}/cmdline", "rb") as fh:
                    yield int(e), [a for a in fh.read().split(b"\0") if a]
            except OSError:
                continue


def steam_running(proc_root: str = "/proc") -> bool:
    """True while the Steam client itself is running (native, or Flatpak - its processes show on the host too)."""
    for _pid, parts in _cmdlines(proc_root):
        if any(os.path.basename(a.decode("utf-8", "replace")) in ("steam", "steamwebhelper") for a in parts[:2]):
            return True
    return False


def steam_ui_ready(proc_root: str = "/proc") -> bool:
    """True once Steam's own window process (steamwebhelper) exists: the client is past its start-up / update and can take a game request."""
    for _pid, parts in _cmdlines(proc_root):
        if any(os.path.basename(a.decode("utf-8", "replace")) == "steamwebhelper" for a in parts[:1]):
            return True
    return False


def steam_game_running(proc_root: str = "/proc") -> bool:
    """True while a game started by Steam is running (its 'reaper' wrapper carries AppId=<id>)."""
    for _pid, parts in _cmdlines(proc_root):
        if any(os.path.basename(a) == b"reaper" for a in parts[:1]) and any(a.startswith(b"AppId=") for a in parts):
            return True
    return False
