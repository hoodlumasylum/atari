"""Find my games: look through Downloads, Desktop, Documents and plugged-in drives (every subfolder, whole game folders and archives) for
your own games and backups, tell which console each one is for, and - after one confirm - copy or move them into
~/Games/CodeAque/<system> (or the folder set for that console), so the next scan shows them.

How the console is told: the file type, then a look inside disc images (PlayStation / Saturn / Dreamcast / Xbox ...), then the folder
names, exactly as Add games does (importer.scan_for_roms). Disc sets ("Disc 1", "Disc 2" ...) stay together in one folder. A folder with a
Windows game (.exe) becomes a PC game; a Windows installer (setup.exe) is listed for the PC Games Installer. Unknown files and games you
already have are skipped and counted. Nothing is ever downloaded. Never raises."""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import archives, importer, windows
from .config import Config

PC = "windows"
MAX_ARCHIVES = 300
DISC_RE = re.compile(r"\s*[\(\[]\s*(disc|disk|cd)\s*(\d+)(\s*of\s*\d+)?\s*[\)\]]", re.I)
PC_SKIP_DIRS = {"windows", "program files", "program files (x86)", "appdata", "steamapps", "node_modules", ".git"}
GAME_HOME = "Games/CodeAque"


@dataclass
class Entry:
    kind: str                        # rom | archive | pc | installer
    system: str                      # system id ("windows" for PC games, "" = unknown yet for archives)
    title: str
    source: Path
    rel: str
    size: int
    dest: str = ""
    item: importer.ImportItem | None = None
    exe: str = ""                    # PC game: the program that starts it (relative to the folder)
    exes: list = field(default_factory=list)


@dataclass
class Found:
    entries: list[Entry] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    unknown: int = 0
    roots: list[str] = field(default_factory=list)

    def by_system(self) -> dict[str, list[Entry]]:
        out: dict[str, list[Entry]] = {}
        for e in self.entries:
            out.setdefault(e.system or "?", []).append(e)
        return out


def default_roots(home: Path | None = None, drives: Callable | None = None) -> list[Path]:
    home = home or Path.home()
    roots = [home / n for n in ("Downloads", "Desktop", "Documents")]
    try:
        for d in (drives or importer.detect_drives)():
            roots.append(Path(d.path))
    except Exception:
        pass
    return [r for r in roots if r.is_dir()]


def games_home(home: Path | None = None) -> Path:
    return (home or Path.home()) / GAME_HOME


def destination(cfg: Config, system: str, home: Path | None = None) -> Path:
    if system == PC:
        return games_home(home) / "pc"
    return importer.destination_for(cfg, system, games_home(home))


def _disc_groups(items: list[importer.ImportItem]) -> list[importer.ImportItem]:
    """Merge "Game (Disc 1).cue" / "(Disc 2)" ... of one console in one folder into one entry (all files kept together)."""
    groups: dict[tuple, list[importer.ImportItem]] = {}
    out = []
    for it in items:
        m = DISC_RE.search(it.path.stem)
        if m and not it.is_dir:
            key = (it.system, str(it.path.parent), DISC_RE.sub("", it.path.stem).strip().lower(), it.path.suffix.lower())
            groups.setdefault(key, []).append(it)
        else:
            out.append(it)
    for key, its in groups.items():
        if len(its) == 1:
            out.append(its[0])
            continue
        its.sort(key=lambda i: int(DISC_RE.search(i.path.stem).group(2)))
        first = its[0]
        comp = list(first.companions)
        for other in its[1:]:
            comp += [other.path, *other.companions]
        out.append(importer.ImportItem(first.path, first.rel, first.system, sum(i.size for i in its), comp))
    return out


def _title(it_path: Path) -> str:
    return DISC_RE.sub("", windows.clean_name(it_path.stem if it_path.is_file() else it_path.name)).strip() or it_path.name


def _pc_folders(root: Path, claimed: set[str], cancel) -> tuple[list[Entry], list[Entry]]:
    games, installers = [], []
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
        if cancel is not None and cancel.is_set():
            break
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d.lower() not in PC_SKIP_DIRS
                       and str(Path(dirpath) / d) not in claimed]
        exes = [f for f in filenames if f.lower().endswith(".exe")]
        if not exes:
            continue
        here = Path(dirpath)
        if here == root:                          # loose .exe files in Downloads: installers only (a lone .exe is usually a program setup)
            for f in exes:
                if windows._INSTALLER.search(f):
                    p = here / f
                    installers.append(Entry("installer", PC, windows.clean_name(p.stem), p, f, _size(p)))
            continue
        cands = windows.find_exes(here, max_depth=3)
        if not cands:
            continue
        best = cands[0]
        if windows._INSTALLER.search(best.path.name):
            installers.append(Entry("installer", PC, windows.clean_name(here.name), best.path, str(best.path.relative_to(root)), best.size))
        else:
            games.append(Entry("pc", PC, windows.clean_name(here.name), here, str(here.relative_to(root)), _tree_size(here),
                               exe=best.rel, exes=[c.rel for c in cands[:8]]))
        dirnames[:] = []                          # a game folder is one game: do not look further inside
    return games, installers


def _size(p: Path) -> int:
    try:
        return p.stat().st_size
    except OSError:
        return 0


def _tree_size(p: Path) -> int:
    total = 0
    for dp, _dn, fns in os.walk(p):
        for f in fns:
            total += _size(Path(dp) / f)
    return total


def find(cfg: Config, roots: list[Path] | None = None, home: Path | None = None, cancel: threading.Event | None = None,
         which: Callable = shutil.which, say: Callable[[str], None] | None = None) -> Found:
    say = say or (lambda t: None)
    home = home or Path.home()
    roots = roots if roots is not None else default_roots(home)
    res = Found(roots=[str(r) for r in roots])
    ext_table = importer._extension_table(cfg)
    mine = os.path.realpath(home / "Games")
    seen_paths: set[str] = set()
    for root in roots:
        if os.path.realpath(root).startswith(mine):
            continue
        say(f"Looking in {root}...")
        scan = importer.scan_for_roms(root, cfg, cancel)
        claimed = {str(it.path) for it in scan.items if it.is_dir}
        for it in _disc_groups(scan.items):
            if str(it.path) in seen_paths:
                continue
            seen_paths.add(str(it.path))
            res.entries.append(Entry("rom", it.system, _title(it.path), it.path, it.rel, it.size,
                                     str(destination(cfg, it.system, home)), it))
        res.unknown += len(scan.skipped)
        res.skipped += [f"{k.rel}: {k.reason}" for k in scan.skipped[:40]]
        # PC games and installers
        pcs, inst = _pc_folders(root, claimed, cancel)
        for e in pcs + inst:
            e.dest = str(destination(cfg, PC, home) / re.sub(r'[\\/:*?"<>|]', "_", e.title)) if e.kind == "pc" else ""
            res.entries.append(e)
        # archives
        n = 0
        for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and str(Path(dirpath) / d) not in claimed]
            for fn in filenames:
                if not archives.is_archive(fn) or n >= MAX_ARCHIVES:
                    continue
                n += 1
                p = Path(dirpath) / fn
                mem, why = archives.members(p, which)
                if why:
                    res.skipped.append(f"{p.relative_to(root)}: not looked inside - {why}.")
                    continue
                exts = [m.rsplit(".", 1)[-1].lower() for m, _s in mem if "." in m.rsplit("/", 1)[-1]]
                if any(e == "exe" for e in exts):
                    res.entries.append(Entry("archive", PC, windows.clean_name(p.name), p, str(p.relative_to(root)), _size(p),
                                             str(destination(cfg, PC, home) / windows.clean_name(p.name))))
                    continue
                systems = {s for e in exts for s in ext_table.get(e, [])}
                roms = [e for e in exts if e in ext_table]
                if not roms:
                    continue                      # not a game archive (music, documents, BIOS packs ...)
                cands = {s for e in roms for s in ext_table[e]}
                sysid = next(iter(cands)) if len(cands) == 1 else ""
                res.entries.append(Entry("archive", sysid, windows.clean_name(p.name), p, str(p.relative_to(root)), _size(p),
                                         str(destination(cfg, sysid, home)) if sysid else "the right console folder (told after unpacking)"))
                del systems
    taken = {str(e.source) for e in res.entries}
    before = len(res.skipped)
    res.skipped = [k for k in res.skipped if not any(k.startswith(os.path.relpath(t, r) + ":") for t in taken for r in res.roots
                                                      if t.startswith(r))]
    res.unknown = max(0, res.unknown - (before - len(res.skipped)))
    order = {sid: i for i, sid in enumerate(cfg.systems)}
    res.entries.sort(key=lambda e: (e.kind == "installer", order.get(e.system, 998 if e.system == PC else 999), e.title.lower()))
    return res


@dataclass
class Done:
    added: int = 0
    duplicates: int = 0
    unknown: int = 0
    failed: list[str] = field(default_factory=list)
    pc_added: list[str] = field(default_factory=list)
    systems: set = field(default_factory=set)


def _remove_source(e: Entry) -> None:
    try:
        if e.source.is_dir():
            shutil.rmtree(e.source)
        else:
            files = [e.source] + (list(e.item.companions) if e.item else [])
            for f in files:
                f.unlink(missing_ok=True)
    except OSError:
        pass


def install(found: Found, cfg: Config, move: bool = False, home: Path | None = None, which: Callable = shutil.which,
            cancel: threading.Event | None = None, say: Callable[[str], None] | None = None) -> Done:
    """Copy (or move) every game entry into place. Installers are not run here (that is the PC Games Installer's job)."""
    say = say or (lambda t: None)
    home = home or Path.home()
    out = Done()
    groot = games_home(home)
    for e in found.entries:
        if cancel is not None and cancel.is_set():
            break
        if e.kind == "installer":
            continue
        say(("Moving " if move else "Copying ") + e.title + "...")
        try:
            if e.kind == "rom":
                r = importer.copy_items([e.item], cfg, games_root=groot)
                out.duplicates += r.skipped_duplicates
                out.failed += r.failed
                if r.copied:
                    out.added += 1
                    out.systems.add(e.system)
                    if move:
                        _remove_source(e)
            elif e.kind == "pc":
                dest = Path(e.dest)
                if dest.exists():
                    out.duplicates += 1
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                (shutil.move if move else shutil.copytree)(str(e.source), str(dest))
                exe = dest / e.exe
                if exe.is_file():
                    windows.add_game(e.title, str(exe))
                    out.pc_added.append(e.title)
                    out.added += 1
                    out.systems.add(PC)
            elif e.kind == "archive":
                tmp = Path(tempfile.mkdtemp(prefix="codeaque-games-"))
                try:
                    ok, why = archives.extract(e.source, None, tmp, which)
                    if not ok:
                        out.failed.append(f"{e.source.name}: {why}")
                        continue
                    if e.system == PC:
                        dest = Path(e.dest)
                        if dest.exists():
                            out.duplicates += 1
                            continue
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        inner = [p for p in tmp.iterdir()]
                        src = inner[0] if len(inner) == 1 and inner[0].is_dir() else tmp
                        shutil.copytree(src, dest)
                        cands = windows.find_exes(dest)
                        if cands and not windows._INSTALLER.search(cands[0].path.name):
                            windows.add_game(e.title, str(cands[0].path))
                            out.pc_added.append(e.title)
                            out.added += 1
                            out.systems.add(PC)
                        else:
                            out.failed.append(f"{e.title}: unpacked to {dest}, but it is an installer - use the PC Games Installer on it")
                    else:
                        scan = importer.scan_for_roms(tmp, cfg)
                        out.unknown += len(scan.skipped)
                        items = _disc_groups(scan.items)
                        if not items:
                            out.unknown += 1
                            continue
                        r = importer.copy_items(items, cfg, games_root=groot)
                        out.duplicates += r.skipped_duplicates
                        out.failed += r.failed
                        out.added += r.copied
                        out.systems.update(r.systems.keys())
                        if r.copied == 0 and r.skipped_duplicates:
                            continue
                    if move:
                        e.source.unlink(missing_ok=True)
                finally:
                    shutil.rmtree(tmp, ignore_errors=True)
        except OSError as exc:
            out.failed.append(f"{e.title}: {exc.strerror or exc}")
    return out
