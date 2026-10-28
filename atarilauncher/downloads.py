"""Files you downloaded from the web (in ~/Downloads) and a one-press way to move a finished file into your games.

CodeAque does not curate, bookmark or link to any download site: the Web Browser tile opens a neutral search engine and you browse
yourself. Downloads are saved by the browser into ~/Downloads (its normal place); this screen lists them, shows the ones that are
still arriving (a growing .crdownload / .part file) and moves a finished file into ~/Games/Atari/<system>/ - the folder CodeAque's game
scanner reads (~/Games/Code is made as a second name for it). Only files you own or have the right to use belong here.
Pure Python, injectable folders, so it is testable."""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from . import apps, importer

PARTIAL = (".crdownload", ".part", ".partial", ".download", ".tmp", ".opdownload")
LIMIT = 40
GAME_ARCHIVES = ("zip", "7z", "rar")


@dataclass
class Item:
    path: Path
    size: int
    mtime: float
    partial: bool = False
    is_dir: bool = False
    guess: list = None          # system ids this file name / extension could belong to

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def is_torrent(self) -> bool:
        return not self.is_dir and self.path.name.lower().endswith(".torrent")

    @property
    def shown_name(self) -> str:
        n = self.path.name
        for ext in PARTIAL:
            if n.lower().endswith(ext):
                return n[: -len(ext)] or n
        return n


def downloads_dir(home: Path | None = None) -> Path:
    return (home or Path.home()) / "Downloads"


def scan(cfg, home: Path | None = None, limit: int = LIMIT) -> list[Item]:
    """Newest first: files still arriving, then finished ones. Folders and hidden files are ignored."""
    d = downloads_dir(home)
    table = importer._extension_table(cfg)
    out: list[Item] = []
    try:
        entries = list(os.scandir(d))
    except OSError:
        return []
    for e in entries:
        try:
            if e.name.startswith("."):
                continue
            is_dir = e.is_dir(follow_symlinks=False)
            if not is_dir and not e.is_file(follow_symlinks=False):
                continue
            st = e.stat()
        except OSError:
            continue
        low = e.name.lower()
        if is_dir:                                  # a torrent (or unpacked game) folder: size and "still arriving?" from inside
            size, partial = folder_info(Path(e.path))
            out.append(Item(Path(e.path), size, st.st_mtime, partial, True, []))
            continue
        partial = low.endswith(PARTIAL)
        ext = low.rsplit(".", 1)[-1] if "." in low else ""
        out.append(Item(Path(e.path), st.st_size, st.st_mtime, partial, False, [] if partial else table.get(ext, [])))
    out.sort(key=lambda i: (not i.partial, -i.mtime))
    return out[:limit]


def item_for(cfg, path: Path) -> Item | None:
    """An Item for any file or folder (what "Add to my games" needs), with the likely systems guessed from the extension."""
    try:
        st = path.stat()
    except OSError:
        return None
    if path.is_dir():
        size, partial = folder_info(path)
        return Item(path, size, st.st_mtime, partial, True, [])
    low = path.name.lower()
    ext = low.rsplit(".", 1)[-1] if "." in low else ""
    return Item(path, st.st_size, st.st_mtime, low.endswith(PARTIAL), False, importer._extension_table(cfg).get(ext, []))


def folder_info(path: Path, cap: int = 500) -> tuple[int, bool]:
    """(bytes, still arriving?) of a folder: a torrent client keeps unfinished files as *.part. Looks at `cap` files at most."""
    total, partial, n = 0, False, 0
    for dirpath, _dirs, files in os.walk(path):
        for f in files:
            n += 1
            if n > cap:
                return total, partial
            if f.lower().endswith(PARTIAL):
                partial = True
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total, partial


def games_alias(home: Path | None = None) -> Path | None:
    """Make ~/Games/Code a second name for ~/Games/Atari (never replaces anything that exists). Returns the alias if it is there."""
    base = (home or Path.home()) / "Games"
    old, new = base / "Atari", base / "Code"
    try:
        if old.is_dir() and not new.exists() and not new.is_symlink():
            new.symlink_to(old, target_is_directory=True)
    except OSError:
        pass
    return new if new.exists() else None


def candidates(cfg, item: Item) -> list[tuple[str, str]]:
    """(system id, name) pairs: the likely ones first, then every system, so the person can always choose."""
    likely = [s for s in (item.guess or []) if s in cfg.systems]
    rest = sorted((s for s in cfg.systems if s not in likely), key=lambda s: cfg.systems[s].name.lower())
    return [(s, cfg.systems[s].name) for s in likely + rest]


def add_to_games(cfg, item_path: Path, system: str, home: Path | None = None, games_root: Path | None = None) -> tuple[bool, str, Path | None]:
    """Move a finished download into the system's game folder. Never overwrites: a name that exists gets " (2)". Never raises."""
    try:
        if cfg.systems.get(system) is None:
            return False, "Choose a system first.", None
        if item_path.name.lower().endswith(PARTIAL):
            return False, "That file is still downloading. Wait until it is finished.", None
        if not item_path.exists():
            return False, "That file is gone (moved or deleted).", None
        root = games_root
        if root is None:
            root = (home or Path.home()) / "Games" / "Atari"
        dest_dir = importer.destination_for(cfg, system, root)
        dest_dir.mkdir(parents=True, exist_ok=True)
        target = dest_dir / item_path.name
        if target.exists():
            target = importer._unique(target) if item_path.is_file() else target.with_name(f"{target.name} (2)")
        shutil.move(str(item_path), str(target))
        games_alias(home)
        return True, f"Moved {target.name} to {dest_dir}. It is in your games now.", target
    except OSError as exc:
        return False, f"Could not move it: {exc.strerror or exc}", None


def human_age(mtime: float, now: float | None = None) -> str:
    s = max(0, int((now if now is not None else time.time()) - mtime))
    if s < 90:
        return "just now"
    if s < 3600:
        return f"{s // 60} min ago"
    if s < 86400:
        return f"{s // 3600} h ago"
    return f"{s // 86400} d ago"


def open_torrent(cfg, path: Path | None = None, home: Path | None = None, which=shutil.which, popen=subprocess.Popen) -> tuple[bool, str]:
    """Start the torrent client (Transmission), with a .torrent file or magnet link when given. Never raises."""
    app = apps.BY_ID["transmission"]
    cmd, how = apps.app_command(cfg, app, home, which)
    if not how:
        return False, apps.install_hint(app)
    arg = [str(path)] if path is not None else []
    try:
        popen(cmd + arg, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        return False, f"Could not start the torrent client: {exc.strerror or exc}"
    return True, "Opening Transmission..." if path is None else f"Adding {Path(path).name} to Transmission..."
