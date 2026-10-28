"""BIOS / firmware helper: finds the files YOU already own on a USB stick or folder, checks them, and copies them
to the places the emulators look. Code never downloads, bundles or links to BIOS files, firmware, keys or games -
you must use files dumped from consoles you own.

Pure Python (no Qt) so it can be tested. The stick is only ever read.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import emulators
from .config import Config

MAX_FILES = 60000
MD5_LIMIT = 64 * 1024 * 1024
SKIP_DIRS = {"system volume information", "$recycle.bin", "lost+found", "recycler", ".trashes", "found.000"}

LEGAL = ("Only use BIOS files and keys dumped from consoles you own. Code does not download or include them, "
         "and does not link to places that do.")


@dataclass(frozen=True)
class Known:
    name: str                      # canonical file name
    system: str                    # Code system id
    label: str
    md5: tuple = ()                # known good checksums (public lists, e.g. libretro's System.dat)
    strict: bool = True            # False: the file differs per console, so a different checksum is fine
    optional: bool = False
    targets: tuple = ()            # where it is copied (see TARGETS)
    alts: tuple = ()               # other accepted file names (lower case)


def _k(name, system, label, md5=(), targets=("ra",), strict=True, optional=False, alts=()):
    return Known(name, system, label, tuple(md5), strict, optional, tuple(targets), tuple(a.lower() for a in alts))


_PS1 = {
    "scph1000.bin": "239665b1a3dade1b5a52c06338011044", "scph1001.bin": "924e392ed05558ffdb115408c263dccf",
    "scph1002.bin": "54847e693405ffeb0359c6287434cbef", "scph100.bin": "8abc1b549a4a80954addc48ef02c4521",
    "scph101.bin": "6e3735ff4c7dc899ee98981385f6f3d0", "scph3000.bin": "849515939161e62f6b866f6853006780",
    "scph3500.bin": "cba733ceeff5aef5c32254f1d617fa62", "scph5000.bin": "eb201d2d98251a598af467d4347bb62f",
    "scph5500.bin": "8dd7d5296a650fac7319bce665a6a53c", "scph5501.bin": "490f666e1afb15b7362b406ed1cea246",
    "scph5502.bin": "32736f17079d0b2b7024407c39bd3050", "scph5552.bin": "32736f17079d0b2b7024407c39bd3050",
    "scph7001.bin": "1e68c231d0896b7eadcad1d7d8e76129", "scph7002.bin": "b9d9a0286c33dc6b7237bb13cd46fdee",
    "scph7003.bin": "490f666e1afb15b7362b406ed1cea246", "scph7502.bin": "b9d9a0286c33dc6b7237bb13cd46fdee",
    "scph102a.bin": "b10f5e0e3d9eb60e5159690680b1e774", "scph102b.bin": "de93caec13d1a141a40a79f5c86168d6",
    "scph102c.bin": "de93caec13d1a141a40a79f5c86168d6",
}
_AMIGA = {
    "kick33180.A500": "85ad74194e87c08904327de1a9443b7a", "kick34005.A500": "82a21c1890cae844b3df741f2762d48d",
    "kick37175.A500": "dc10d7bdd1b6f450773dfb558477c230", "kick40063.A600": "e40a5dfb3d017ba8779faba30cbd1c8e",
    "kick37350.A600": "465646c9b6729f77eea5314d1f057951", "kick40068.A1200": "646773759326fbac3b2311fd8c8793ee",
    "kick39106.A1200": "b7cc148386aa631136f510cd29e42fc3",
}

KNOWN: list[Known] = (
    [_k(n, "ps1", "PlayStation BIOS " + n[:-4].upper(), (m,), ("ra", "duckstation")) for n, m in _PS1.items()]
    + [
        _k("gba_bios.bin", "gba", "Game Boy Advance BIOS", ("a860e8c0b6d573d191e4ec7db1b1e4f6",), ("ra", "mgba"), optional=True),
        _k("bios7.bin", "nds", "Nintendo DS ARM7 BIOS", ("df692a80a5b1bc90728bc3dfc76cd948",), ("ra", "melonds"), alts=("nds7.bin",)),
        _k("bios9.bin", "nds", "Nintendo DS ARM9 BIOS", ("a392174eb3e572fed6447e956bde4b25",), ("ra", "melonds"), alts=("nds9.bin",)),
        _k("firmware.bin", "nds", "Nintendo DS firmware", ("e45033d9b0fa6b0de071292bba7c9d13",), ("ra", "melonds"), strict=False),
        _k("dc_boot.bin", "dreamcast", "Dreamcast boot ROM", ("e10c53c2f8b90bab96ead2d368858623",), ("ra:dc", "flycast"),
           alts=("dc_bios.bin", "boot.bin")),
        _k("dc_flash.bin", "dreamcast", "Dreamcast flash memory", ("0a93f7940c455905bea6e392dfde92a4",), ("ra:dc", "flycast"),
           strict=False, optional=True, alts=("flash.bin", "dc_nvmem.bin")),
        _k("sega_101.bin", "saturn", "Saturn BIOS (Japan)", ("85ec9ca47d8f6807718151cbcca8b964",), ("ra", "mednafen")),
        _k("mpr-17933.bin", "saturn", "Saturn BIOS (USA/Europe)", ("3240872c70984b6cbfda1586cab68dbe",), ("ra", "mednafen")),
        _k("saturn_bios.bin", "saturn", "Saturn BIOS (Kronos)", ("af5828fdff51384f99b3c4926be27762",), ("ra",)),
        _k("bios_CD_U.bin", "segacd", "Sega CD BIOS (USA)", ("2efd74e3232ff260e371b99f84024f7f",)),
        _k("bios_CD_E.bin", "segacd", "Mega-CD BIOS (Europe)", ("e66fa1dc5820d254611fdcdba0662372",)),
        _k("bios_CD_J.bin", "segacd", "Mega-CD BIOS (Japan)", ("278a9397d192149e84e820ac621a8edd",)),
        _k("neogeo.zip", "neogeo", "Neo Geo BIOS", ("00dad01abdbf8ea9e79ad2fe11bdb182",), ("ra:fbneo", "romdir"), strict=False),
        _k("syscard3.pce", "pce", "PC Engine CD System Card 3", ("38179df8f4ac870017db21ebcbf53114",), optional=True),
        _k("lynxboot.img", "atarilynx", "Atari Lynx boot ROM", ("fcd403db69f54290b51035d82f835e7b",)),
        _k("5200.rom", "atari5200", "Atari 5200 BIOS", ("281f20ea4320404ec820fb7ec0693b38",)),
        _k("7800 BIOS (U).rom", "atari7800", "Atari 7800 BIOS (USA)", ("0763f1ffb006ddbe32e52d497ee848ae",), optional=True),
        _k("panafz10.bin", "3do", "3DO BIOS (Panasonic FZ-10)", ("51f2f43ae2f3508a14d9f56597e2d3ce",)),
        _k("panafz1.bin", "3do", "3DO BIOS (Panasonic FZ-1)", ("f47264dd47fe30f73ab3c010015c155b",)),
        # Xbox (xemu): files are matched by name only (many valid dumps exist)
        _k("mcpx_1.0.bin", "xbox", "Xbox boot ROM (MCPX)", (), ("xemu",)),
        _k("Complex_4627v1.03.bin", "xbox", "Xbox BIOS (flash)", (), ("xemu",),
           alts=("complex_4627.bin", "xbox_bios.bin", "xboxbios.bin")),
        _k("xbox_hdd.qcow2", "xbox", "Xbox hard-disk image", (), ("xemu",)),
        _k("eeprom.bin", "xbox", "Xbox EEPROM", (), ("xemu",), optional=True),
        # Switch keys
        _k("prod.keys", "switch", "Switch keys (prod.keys)", (), ("ryujinx", "eden")),
        _k("title.keys", "switch", "Switch title keys", (), ("ryujinx", "eden"), optional=True),
    ]
    + [_k(n, "amiga", "Amiga Kickstart " + n.split(".")[0], (m,), ("ra",)) for n, m in _AMIGA.items()]
)
KNOWN_BY_NAME: dict[str, Known] = {}
for _kn in KNOWN:
    KNOWN_BY_NAME.setdefault(_kn.name.lower(), _kn)
    for _a in _kn.alts:
        KNOWN_BY_NAME.setdefault(_a, _kn)

PS2_RE = re.compile(r"^(scph[-_ ]?\d{5}.*|ps2[-_ ].*bios.*|ps2-\d{4}[a-z]{1,2}-\d{8}.*)\.bin$", re.I)
PS2_SIZES = (4 * 1024 * 1024, 4 * 1024 * 1024 + 1024)
PS2_COMPANIONS = (".nvm", ".rom1", ".rom2", ".erom", ".mec")
PS3_FILE = "ps3updat.pup"

# What each console needs: ("any"|"all", file names). "recommended" consoles still run (the emulator has a fallback).
NEEDS: dict[str, dict] = {
    "ps1": {"mode": "any", "names": [n for n in _PS1], "text": "PlayStation"},
    "ps2": {"mode": "ps2", "names": [], "text": "PlayStation 2"},
    "dreamcast": {"mode": "all", "names": ["dc_boot.bin"], "text": "Dreamcast", "recommended": True},
    "saturn": {"mode": "any", "names": ["sega_101.bin", "mpr-17933.bin", "saturn_bios.bin"], "text": "Sega Saturn"},
    "segacd": {"mode": "any", "names": ["bios_CD_U.bin", "bios_CD_E.bin", "bios_CD_J.bin"], "text": "Sega CD"},
    "neogeo": {"mode": "all", "names": ["neogeo.zip"], "text": "Neo Geo"},
    "nds": {"mode": "all", "names": ["bios7.bin", "bios9.bin", "firmware.bin"], "text": "Nintendo DS", "recommended": True},
    "gba": {"mode": "all", "names": ["gba_bios.bin"], "text": "Game Boy Advance", "recommended": True},
    "atarilynx": {"mode": "all", "names": ["lynxboot.img"], "text": "Atari Lynx"},
    "atari5200": {"mode": "all", "names": ["5200.rom"], "text": "Atari 5200"},
    "3do": {"mode": "any", "names": ["panafz10.bin", "panafz1.bin"], "text": "3DO"},
    "xbox": {"mode": "all", "names": ["mcpx_1.0.bin", "Complex_4627v1.03.bin", "xbox_hdd.qcow2"], "text": "Xbox Classic"},
    "switch": {"mode": "all", "names": ["prod.keys"], "text": "Nintendo Switch"},
    "ps3": {"mode": "note", "names": [], "text": "PlayStation 3"},
}

# --------------------------------------------------------------------------- where files go
# target id -> (emulator id, flatpak id, native folders, flatpak folders relative to ~/.var/app/<id>/)
TARGETS: dict[str, tuple] = {
    "ra": ("retroarch", "org.libretro.RetroArch", (".config/retroarch/system",), ("config/retroarch/system",)),
    "ra:dc": ("retroarch", "org.libretro.RetroArch", (".config/retroarch/system/dc",), ("config/retroarch/system/dc",)),
    "ra:fbneo": ("retroarch", "org.libretro.RetroArch", (".config/retroarch/system/fbneo",),
                 ("config/retroarch/system/fbneo",)),
    "duckstation": ("duckstation", "org.duckstation.DuckStation",
                    (".local/share/duckstation/bios", ".config/duckstation/bios"),
                    ("config/duckstation/bios", "data/duckstation/bios")),
    "pcsx2": ("pcsx2", "net.pcsx2.PCSX2", (".config/PCSX2/bios",), ("config/PCSX2/bios",)),
    "flycast": ("flycast", "org.flycast.Flycast", (".local/share/flycast",), ("data/flycast",)),
    "melonds": ("melonds", "net.kuribo64.melonDS", (".config/melonDS",), ("config/melonDS",)),
    "mgba": ("mgba", "io.mgba.mGBA", (".config/mgba",), ("config/mgba",)),
    "xemu": ("xemu", "app.xemu.xemu", (".local/share/xemu/xemu",), ("data/xemu/xemu",)),
    "mednafen": ("mednafen", "", (".mednafen/firmware",), ()),
    "ryujinx": ("ryujinx", "io.github.ryubing.Ryujinx", (".config/Ryujinx/system",), ("config/Ryujinx/system",)),
    "eden": ("switchfork", "dev.eden_emu.eden", (".local/share/eden/keys",), ("data/eden/keys",)),
}
TARGET_NAMES = {"ra": "RetroArch", "ra:dc": "RetroArch", "ra:fbneo": "RetroArch", "duckstation": "DuckStation",
                "pcsx2": "PCSX2", "flycast": "Flycast", "melonds": "melonDS", "mgba": "mGBA", "xemu": "xemu",
                "mednafen": "Mednafen", "ryujinx": "Ryujinx", "eden": "Eden", "romdir": "your game folder"}


def _pick(cands: list[Path]) -> list[Path]:
    present = [c for c in cands if c.parent.is_dir() or c.is_dir()]
    return present or cands[:1]


def target_dirs(target: str, home: Path | None = None, rom_dir: Path | None = None,
                which: Callable[[str], str | None] = shutil.which) -> list[Path]:
    """The folder(s) a file for this target goes to: the Flatpak's when it is installed, a native install's when
    that exists, and (when neither exists yet) the Flatpak folder, because that is what Code's installer installs."""
    home = home or Path.home()
    if target == "romdir":
        return [rom_dir] if rom_dir else []
    emu_id, fp_id, native, flat = TARGETS[target]
    emu = emulators.EMUS.get(emu_id)
    out: list[Path] = []
    fl_dirs = [home / ".var/app" / fp_id / rel for rel in flat] if fp_id else []
    nat_dirs = [home / rel for rel in native]
    if fp_id and emulators.flatpak_installed(fp_id, home):
        out += _pick(fl_dirs)
    shared = {home, home / ".config", home / ".local/share", home / ".local"}
    native_there = bool(emu and any(which(x) for x in emu.exes)) or any(
        d.exists() or (d.parent not in shared and d.parent.exists()) for d in nat_dirs)
    if native_there or not fl_dirs:
        out += _pick(nat_dirs)
    if not out:
        out = _pick(fl_dirs) if fl_dirs else _pick(nat_dirs)
    seen, res = set(), []
    for p in out:
        if p not in seen:
            seen.add(p)
            res.append(p)
    return res


# --------------------------------------------------------------------------- scanning
def md5_of(path: Path, limit: int = MD5_LIMIT) -> str:
    try:
        if path.stat().st_size > limit:
            return ""
        h = hashlib.md5()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


@dataclass
class BiosItem:
    path: Path
    name: str               # file name as found
    system: str
    label: str
    status: str             # ok | named | odd | note
    size: int
    rel: str = ""           # shown under the name
    known: Known | None = None
    is_dir: bool = False
    targets: tuple = ()
    note: str = ""
    companions: list = field(default_factory=list)

    @property
    def sizeText(self) -> str:
        from .importer import human_size
        return human_size(self.size)


@dataclass
class BiosScan:
    items: list[BiosItem] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    cancelled: bool = False
    truncated: bool = False


STATUS_TEXT = {"ok": "verified", "named": "name matches", "odd": "unusual file - check it", "note": "note"}


def identify(path: Path, size: int | None = None) -> BiosItem | None:
    name = path.name
    low = name.lower()
    try:
        size = path.stat().st_size if size is None else size
    except OSError:
        return None
    if low == PS3_FILE:
        return BiosItem(path, name, "ps3", "PlayStation 3 firmware", "note", size, note=(
            "PS3 firmware cannot be copied automatically. In RPCS3 choose File > Install Firmware and pick this file."))
    kn = KNOWN_BY_NAME.get(low)
    if kn is None and low.endswith(".qcow2"):  # any xemu hard-disk image: xemu is told to use it as xbox_hdd.qcow2
        kn = KNOWN_BY_NAME.get("xbox_hdd.qcow2")
    if kn is not None:
        if size == 0:
            return None
        digest = md5_of(path) if kn.md5 else ""
        if kn.md5 and digest:
            status = "ok" if digest in kn.md5 else ("named" if not kn.strict else "odd")
        else:
            status = "named"
        return BiosItem(path, kn.name, kn.system, kn.label, status, size, known=kn, targets=kn.targets)
    if PS2_RE.match(low) and size in PS2_SIZES:
        comps = [path.with_suffix(ext) for ext in PS2_COMPANIONS if path.with_suffix(ext).is_file()]
        # PCSX2 recognises the BIOS by content; a 4 MB file with a PS2-style name is the usual case
        k = Known(name, "ps2", "PlayStation 2 BIOS", (), False, False, ("pcsx2",))
        return BiosItem(path, name, "ps2", "PlayStation 2 BIOS", "named", size, known=k, targets=("pcsx2",),
                        companions=comps)
    return None


def scan_for_bios(root: str | Path, cancel: threading.Event | None = None) -> BiosScan:
    """Walk `root` read-only and list known BIOS files. The best copy of each file name wins."""
    root = Path(root)
    res = BiosScan()
    best: dict[str, BiosItem] = {}
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False, onerror=lambda e: None):
        if cancel is not None and cancel.is_set():
            res.cancelled = True
            return res
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d.lower() not in SKIP_DIRS)
        for fn in sorted(filenames):
            seen += 1
            if seen > MAX_FILES:
                res.truncated = True
                break
            low = fn.lower()
            if not (low in KNOWN_BY_NAME or low == PS3_FILE or low.endswith((".bin", ".qcow2"))):
                continue
            item = identify(Path(dirpath) / fn)
            if item is None:
                continue
            try:
                item.rel = str(Path(dirpath).relative_to(root)) if Path(dirpath) != root else ""
            except ValueError:
                item.rel = ""
            key = (item.known.name.lower() if item.known else item.name.lower()) if item.system != "ps2" else item.name.lower()
            old = best.get(key)
            rank = {"ok": 0, "named": 1, "odd": 2, "note": 1}
            if old is None or rank[item.status] < rank[old.status]:
                best[key] = item
        if res.truncated:
            break
    order = {sid: i for i, sid in enumerate(emulators_order())}
    res.items = sorted(best.values(), key=lambda it: (order.get(it.system, 999), it.name.lower()))
    return res


def missing_detail(system_id: str, extra=(), home: Path | None = None, which=shutil.which) -> list[str]:
    """Names still missing for one console, counting `extra` (canonical names found in a pack but not copied yet). [] = nothing missing."""
    need = NEEDS.get(system_id)
    if need is None or need["mode"] == "note":
        return []
    extra = set(extra)
    have = _have(system_id, need["names"], home, which) | extra
    if need["mode"] == "ps2":
        return [] if "ps2-bios" in have else ["a PS2 BIOS (scph*.bin)"]
    if need["mode"] == "any":
        if have & set(need["names"]):
            return []
        names = need["names"]
        return ["one of: " + ", ".join(names[:4]) + (", ..." if len(names) > 4 else "")]
    return [n for n in need["names"] if n not in have]


def pack_summary(items: list, home: Path | None = None, which=shutil.which) -> list[str]:
    """Plain lines for the checklist after a BIOS pack was opened: what was found, and what each console in it still lacks."""
    lines: list[str] = []
    systems: dict[str, set] = {}
    for it in items:
        if it.status == "note" or not it.targets:
            continue
        systems.setdefault(it.system, set()).add(
            "ps2-bios" if it.system == "ps2" else (it.known.name if it.known else it.name))
    names = {s.id: s.name for s in emulators.SYSTEMS}
    for sid, have in systems.items():
        miss = missing_detail(sid, have, home, which)
        lines.append(f"{names.get(sid, sid)}: " + ("found everything it needs." if not miss else "still missing " + ", ".join(miss) + "."))
    return lines


def emulators_order() -> list[str]:
    return [s.id for s in emulators.SYSTEMS]


# --------------------------------------------------------------------------- copying
@dataclass
class BiosCopyResult:
    copied: int = 0
    skipped_same: int = 0
    failed: list[str] = field(default_factory=list)
    written: list[str] = field(default_factory=list)   # "<system>:<canonical name>"
    folders: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    cancelled: bool = False
    error: str = ""


def _same(a: Path, b: Path) -> bool:
    try:
        return a.stat().st_size == b.stat().st_size and md5_of(a, 512 * 1024 * 1024) == md5_of(b, 512 * 1024 * 1024)
    except OSError:
        return False


def copy_items(items: list[BiosItem], cfg: Config | None = None, home: Path | None = None,
               progress: Callable[[int, int, str], None] | None = None, cancel: threading.Event | None = None,
               which: Callable[[str], str | None] = shutil.which) -> BiosCopyResult:
    res = BiosCopyResult()
    total = max(1, len(items))
    for n, it in enumerate(items, 1):
        if cancel is not None and cancel.is_set():
            res.cancelled = True
            break
        if progress:
            progress(n - 1, total, it.name)
        if it.status == "note" or not it.targets:
            if it.note:
                res.notes.append(it.note)
            continue
        rom_dir = None
        if cfg is not None and it.system in cfg.systems and cfg.systems[it.system].roms:
            rom_dir = Path(cfg.systems[it.system].roms[0]).expanduser()
        elif it.system == "neogeo":
            rom_dir = (home or Path.home()) / "Games" / "Atari" / "neogeo"
        dest_name = (it.known.name if it.known else it.name)
        placed = False
        for tid in it.targets:
            for folder in target_dirs(tid, home, rom_dir, which):
                target = folder / dest_name
                try:
                    folder.mkdir(parents=True, exist_ok=True)
                    if target.is_file() and _same(it.path, target):
                        res.skipped_same += 1
                        placed = True
                        continue
                    tmp = target.with_name(target.name + ".part")
                    shutil.copyfile(it.path, tmp)
                    os.replace(tmp, target)
                    for comp in it.companions:
                        shutil.copyfile(comp, folder / comp.name)
                    res.copied += 1
                    placed = True
                    if str(folder) not in res.folders:
                        res.folders.append(str(folder))
                except OSError as exc:
                    res.failed.append(f"{it.name} -> {folder}: {exc.strerror or exc}")
        if placed:
            res.written.append(f"{it.system}:{dest_name}")
        if it.system == "xbox" or it.system == "switch":
            res.notes.append(XBOX_NOTE if it.system == "xbox" else SWITCH_NOTE)
        if it.system == "nds":
            res.notes.append("melonDS: turn on  Config > Emu settings > DS-mode > Use external BIOS/firmware files.")
    if progress:
        progress(total, total, "")
    # xemu reads its files from xemu.toml: write one only if the user has none yet
    if any(w.startswith("xbox:") for w in res.written):
        try:
            _maybe_write_xemu_config(home, which)
        except OSError:
            pass
    res.notes = list(dict.fromkeys(res.notes))
    return res


XBOX_NOTE = ("xemu: if it does not find the files by itself, open  Machine > System  in xemu and pick the BIOS, boot ROM "
             "and hard-disk files (they were copied to its data folder).")
SWITCH_NOTE = ("Switch: the firmware is installed inside the emulator (Tools > Install Firmware); the keys were "
               "copied for you.")


XBOX_FILES = (
    ("mcpx_1.0.bin", "boot ROM (MCPX), 512 bytes - from your own Xbox", True),
    ("Complex_4627v1.03.bin", "BIOS, 256 KB (any other genuine Xbox BIOS dump also works if you rename it) - from your own Xbox", True),
    ("xbox_hdd.qcow2", "hard-disk image: an empty formatted Xbox disk (xemu's own setup page explains how to make one)", True),
    ("eeprom.bin", "EEPROM - optional, xemu makes one by itself", False),
)


def xbox_guide(home: Path | None = None, which=shutil.which) -> list[str]:
    """Plain lines telling what the user must supply for original-Xbox games, with what is already found."""
    names = [n for n, _t, _r in XBOX_FILES]
    have = _have("xbox", names, home, which)
    lines = ["Xbox Classic: Code never includes the Xbox BIOS, boot ROM, hard-disk image or games - you supply them "
             "from your own console:"]
    for n, text, required in XBOX_FILES:
        ok = n in have or (n == "Complex_4627v1.03.bin" and "complex_4627.bin" in have)
        lines.append(("[found] " if ok else ("[needed] " if required else "[optional] ")) + f"{n}: {text}")
    lines.append("Use \"Add BIOS files\" to copy them to xemu (USB stick or folder). Games: put the .iso (or .xiso) "
                 "- or an unpacked game folder with default.xbe - into  ~/Games/Atari/xbox  and press Rescan.")
    return lines


def _maybe_write_xemu_config(home: Path | None, which) -> None:
    for folder in target_dirs("xemu", home, None, which):
        toml = folder / "xemu.toml"
        if toml.exists():
            continue
        paths = {}
        for key, names in (("bootrom_path", ("mcpx_1.0.bin",)),
                           ("flashrom_path", ("Complex_4627v1.03.bin", "Complex_4627.bin")),
                           ("hdd_path", ("xbox_hdd.qcow2",)), ("eeprom_path", ("eeprom.bin",))):
            for n in names:
                if (folder / n).is_file():
                    paths[key] = str(folder / n)
                    break
        if {"bootrom_path", "flashrom_path", "hdd_path"} <= set(paths):
            body = "[sys.files]\n" + "".join(f"{k} = '{v}'\n" for k, v in paths.items())
            toml.write_text(body, encoding="utf-8")


# --------------------------------------------------------------------------- what is still missing
def _have(sid: str, names: list[str], home: Path | None, which) -> set[str]:
    """Canonical names of BIOS files for this system that already sit in a place an emulator looks."""
    found: set[str] = set()
    folders: list[Path] = []
    for k in KNOWN:
        if k.system != sid:
            continue
        for tid in k.targets:
            if tid == "romdir":
                continue
            folders += target_dirs(tid, home, None, which)
            if tid in TARGETS:  # also the other variant, so a native file counts when the Flatpak is not installed
                emu_id, fp_id, native, flat = TARGETS[tid]
                h = home or Path.home()
                folders += [h / r for r in native] + ([h / ".var/app" / fp_id / r for r in flat] if fp_id else [])
        for folder in dict.fromkeys(folders):
            for nm in (k.name, *k.alts):
                try:
                    if (folder / nm).is_file():
                        found.add(k.name)
                except OSError:
                    pass
    if sid == "ps2":
        for tid in ("pcsx2",):
            h = home or Path.home()
            emu_id, fp_id, native, flat = TARGETS[tid]
            for folder in [h / r for r in native] + [h / ".var/app" / fp_id / r for r in flat]:
                try:
                    if folder.is_dir() and any(PS2_RE.match(p.name) and p.stat().st_size in PS2_SIZES
                                               for p in folder.iterdir()):
                        found.add("ps2-bios")
                except OSError:
                    pass
    return found


def missing_for(system_id: str, home: Path | None = None, which=shutil.which) -> tuple[str, str]:
    """(state, plain-English text). state: 'ok' | 'missing' | 'recommended' | 'none' (nothing needed) | 'note'."""
    need = NEEDS.get(system_id)
    if need is None:
        return "none", ""
    name = need["text"]
    mode = need["mode"]
    if mode == "note":
        return "note", (f"{name} needs firmware from your own console (PS3UPDAT.PUP): in RPCS3 choose File > Install "
                        f"Firmware. \"Add BIOS files\" can find the file for you.")
    have = _have(system_id, need["names"], home, which)
    if mode == "ps2":
        if "ps2-bios" in have:
            return "ok", f"{name} BIOS found."
        return "missing", f"{name} needs a BIOS file from your own console - use Add BIOS files."
    names = need["names"]
    if mode == "any":
        okay = bool(have & set(names))
        miss = names
    else:
        miss = [n for n in names if n not in have]
        okay = not miss
    if okay:
        return "ok", f"{name} BIOS found."
    if system_id == "switch":
        return "missing", "Nintendo Switch needs the keys (prod.keys) from your own console - use Add BIOS files."
    if need.get("recommended"):
        return "recommended", (f"{name} works better with BIOS files from your own console - use Add BIOS files.")
    if system_id == "xbox":
        return "missing", ("Xbox Classic needs a BIOS, boot ROM and hard-disk image from your own console - "
                           "use Add BIOS files.")
    return "missing", f"{name} needs a BIOS file from your own console - use Add BIOS files."
