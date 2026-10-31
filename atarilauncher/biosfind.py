"""Find my BIOS files: one press looks through ~/Downloads (every subfolder, and inside .zip / .7z / .rar archives) for the BIOS and
firmware files the emulators need - recognised by name, size and (where known) checksum, exactly like Add BIOS files - and shows what was
found and where each file goes. A second press copies them into place (and fixes xemu's settings for the Xbox). Your own files only:
nothing is ever downloaded. Never raises."""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import archives, bios, xemuconfig

MAX_ARCHIVES = 400
MAX_ARCHIVE_BYTES = 8 * 1024 ** 3
MAX_MEMBER_BYTES = 64 * 1024 ** 2          # BIOS files are small; an Xbox disk image (.qcow2) may be bigger
MAX_QCOW_BYTES = 12 * 1024 ** 3


def default_roots(home: Path | None = None) -> list[Path]:
    home = home or Path.home()
    return [home / "Downloads"]


def _wanted(name: str, size: int) -> bool:
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    low = base.lower()
    if low.endswith(".qcow2"):
        return size <= MAX_QCOW_BYTES
    if size > MAX_MEMBER_BYTES:
        return False
    return low in bios.KNOWN_BY_NAME or low == bios.PS3_FILE or low.endswith((".bin", ".rom")) or bios.xemuconfig_name(base)


@dataclass
class Found:
    item: bios.BiosItem
    source: str                      # where it is, for the screen ("Downloads/xbox.zip > Complex 4627.bin")
    dest: str = ""                   # first folder it goes to


@dataclass
class Result:
    found: list[Found] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    archives_seen: int = 0
    tmp: str = ""                    # unpacked candidates live here until copied

    def cleanup(self) -> None:
        if self.tmp:
            shutil.rmtree(self.tmp, ignore_errors=True)
            self.tmp = ""


def _key(it: bios.BiosItem) -> str:
    return (it.known.name.lower() if it.known else it.name.lower()) if it.system != "ps2" else it.name.lower()


def _dest(it: bios.BiosItem, home: Path | None, which) -> str:
    for tid in it.targets:
        for folder in bios.target_dirs(tid, home, None, which):
            return str(folder)
    return ""


def find(roots: list[Path] | None = None, home: Path | None = None, cancel: threading.Event | None = None,
         which: Callable = shutil.which, say: Callable[[str], None] | None = None) -> Result:
    say = say or (lambda t: None)
    home = home or Path.home()
    roots = roots or default_roots(home)
    res = Result()
    best: dict[str, Found] = {}
    rank = {"ok": 0, "named": 1, "note": 1, "odd": 2}

    def offer(it: bios.BiosItem, source: str) -> None:
        k = _key(it)
        old = best.get(k)
        if old is None or rank.get(it.status, 3) < rank.get(old.item.status, 3):
            best[k] = Found(it, source, _dest(it, home, which))

    for root in roots:
        if not root.is_dir():
            res.notes.append(f"{root} does not exist.")
            continue
        say(f"Looking in {root.name}...")
        scan = bios.scan_for_bios(root, cancel)
        for it in scan.items:
            offer(it, f"{root.name}/{it.rel + '/' if it.rel else ''}{it.name}")
        # archives
        for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
            if cancel is not None and cancel.is_set():
                break
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for fn in filenames:
                p = Path(dirpath) / fn
                if not archives.is_archive(fn) or res.archives_seen >= MAX_ARCHIVES:
                    continue
                try:
                    if p.stat().st_size > MAX_ARCHIVE_BYTES:
                        continue
                except OSError:
                    continue
                res.archives_seen += 1
                mem, why = archives.members(p, which)
                if why:
                    res.notes.append(f"{fn}: not looked inside - {why}.")
                    continue
                pick = [n for n, s in mem if _wanted(n, s)]
                if not pick:
                    continue
                say(f"Looking inside {fn}...")
                if not res.tmp:
                    res.tmp = tempfile.mkdtemp(prefix="codeaque-bios-")
                out = Path(res.tmp) / str(res.archives_seen)
                ok, why = archives.extract(p, pick, out, which)
                if not ok:
                    res.notes.append(f"{fn}: {why}.")
                    continue
                for it in bios.scan_for_bios(out).items:
                    rel = str(p.relative_to(root)) if p.is_relative_to(root) else fn
                    offer(it, f"{root.name}/{rel} > {(it.rel + '/') if it.rel else ''}{it.name}")
    order = {sid: i for i, sid in enumerate(bios.emulators_order())}
    res.found = sorted(best.values(), key=lambda f: (order.get(f.item.system, 999), f.item.name.lower()))
    return res


def install(res: Result, cfg=None, home: Path | None = None, which: Callable = shutil.which) -> tuple[bios.BiosCopyResult, list[str]]:
    """Copy everything found into place; for the Xbox also write xemu's settings. -> (copy result, xemu lines)."""
    items = [f.item for f in res.found if f.item.status != "note"]
    out = bios.copy_items(items, cfg, home, which=which)
    lines: list[str] = []
    if any(f.item.system == "xbox" for f in res.found):
        try:
            rep = xemuconfig.repair(home, which)
            lines = rep.lines()
        except Exception as exc:  # pragma: no cover
            lines = [f"xemu settings could not be checked: {exc}"]
    res.cleanup()
    return out, lines
