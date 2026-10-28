"""Add games from a USB stick (or any folder): find the stick, find ROM files, copy them into your library.

Pure Python (no Qt) so it can be tested. The stick is only ever READ - nothing on it is changed.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import roms
from .config import Config

# These file types are shared by several consoles (or are generic), so the folder name decides
# (a "snes" or "PS1" folder on the stick). Without a clear folder name they are skipped.
AMBIGUOUS_EXT = {"bin", "zip", "7z", "iso", "cue", "chd", "m3u", "gz"}
DISC_EXT = {"iso", "xiso"}  # disc images we can look inside to tell the console
SKIP_DIRS = {"system volume information", "$recycle.bin", "lost+found", "recycler", ".trashes", "found.000"}
MAX_FILES = 20000
CHUNK = 1024 * 1024
FS_NAMES = {"vfat": "FAT32", "msdos": "FAT", "exfat": "exFAT", "ntfs": "NTFS", "ntfs3": "NTFS",
            "fuseblk": "NTFS/exFAT", "fuse.ntfs-3g": "NTFS", "ext4": "ext4", "ext3": "ext3", "btrfs": "Btrfs",
            "f2fs": "F2FS", "udf": "UDF", "iso9660": "CD/DVD"}


def human_size(n: float) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{int(n)} B" if unit == "B" else (f"{n:.0f} {unit}" if n >= 100 else f"{n:.1f} {unit}")
        n /= 1024
    return f"{n:.1f} TB"


# ------------------------------------------------------------------ drives
@dataclass
class Drive:
    path: str
    label: str
    fstype: str = ""
    size: int = 0
    removable: bool = True

    @property
    def fs_name(self) -> str:
        return FS_NAMES.get(self.fstype, self.fstype.upper() if self.fstype else "")

    @property
    def detail(self) -> str:
        bits = [self.path]
        if self.fs_name:
            bits.append(self.fs_name)
        if self.size:
            bits.append(human_size(self.size))
        return "  \u00b7  ".join(bits)


def _read_mounts(mounts_file: str) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        with open(mounts_file, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) >= 3:
                    mp = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), parts[1])
                    out[mp] = parts[2]
    except OSError:
        pass
    return out


def _lsblk_mounts() -> dict[str, dict]:
    """{mountpoint: {label, fstype, removable}} for removable/hot-plugged disks, via `lsblk` (best effort)."""
    try:
        res = subprocess.run(["lsblk", "-J", "-b", "-o", "NAME,MOUNTPOINT,MOUNTPOINTS,FSTYPE,RM,HOTPLUG,TRAN,LABEL,SIZE"],
                             capture_output=True, text=True, timeout=4)
        data = json.loads(res.stdout or "{}")
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}
    found: dict[str, dict] = {}

    def truthy(v) -> bool:
        return v in (True, 1, "1", "true")

    def walk(nodes, removable):
        for n in nodes or []:
            rem = removable or truthy(n.get("rm")) or truthy(n.get("hotplug")) or n.get("tran") == "usb"
            mps = [m for m in (n.get("mountpoints") or [n.get("mountpoint")]) if m]
            for mp in mps:
                found[mp] = {"label": n.get("label") or "", "fstype": n.get("fstype") or "", "removable": rem}
            walk(n.get("children"), rem)

    walk(data.get("blockdevices"), False)
    return found


def detect_drives(user: str | None = None, roots: list[str] | None = None, mounts_file: str = "/proc/mounts",
                  use_lsblk: bool = True, require_mount: bool = True) -> list[Drive]:
    """Mounted USB sticks / memory cards: /media/$USER/*, /run/media/$USER/*, /media/* and
    removable disks mounted anywhere else (found with lsblk). A system drive is never listed."""
    user = user or os.environ.get("USER") or Path.home().name
    override = os.environ.get("ATARI_MEDIA_ROOTS")  # testing aid: folders to treat as mount directories
    if override and roots is None:
        roots, require_mount, use_lsblk = [r for r in override.split(os.pathsep) if r], False, False
    roots = roots if roots is not None else [f"/media/{user}", f"/run/media/{user}", "/media"]
    mounts = _read_mounts(mounts_file)
    lsblk = _lsblk_mounts() if use_lsblk else {}
    seen: dict[str, Drive] = {}

    def add(path: str, label: str = ""):
        real = os.path.realpath(path)
        if real in seen or real in ("/", "/boot", "/home") or real.startswith(("/boot/", "/proc", "/sys")):
            return
        if not os.path.isdir(path):
            return
        info = lsblk.get(path, {})
        fstype = info.get("fstype") or mounts.get(path, "")
        try:
            size = shutil.disk_usage(path).total
        except OSError:
            size = 0
        seen[real] = Drive(path, info.get("label") or label or os.path.basename(path.rstrip("/")) or path,
                           fstype, size, bool(info.get("removable", True)))

    for root in roots:
        try:
            names = sorted(os.listdir(root))
        except OSError:
            continue
        for name in names:
            full = os.path.join(root, name)
            if name.startswith(".") or not os.path.isdir(full):
                continue
            if require_mount and not (os.path.ismount(full) or full in mounts):
                continue
            if root == "/media" and name == user:  # /media/<user> is itself a folder of mounts
                continue
            add(full, name)
    for mp, info in lsblk.items():
        if info.get("removable") and mp.startswith(("/mnt", "/media", "/run/media")):
            add(mp, info.get("label", ""))
    return list(seen.values())


# ------------------------------------------------------------------ scanning
@dataclass
class ImportItem:
    path: Path
    rel: str  # path below the scanned folder (for display)
    system: str
    size: int  # including companion files
    companions: list[Path] = field(default_factory=list)  # e.g. the .bin files of a .cue (or a game folder's files)
    is_dir: bool = False  # a whole game folder (PlayStation 3 PS3_GAME folders)

    @property
    def name(self) -> str:
        return self.path.name


@dataclass
class Skipped:
    """A game-like file we did not add (yet), and why. `candidates` non-empty = we can ask "Which system is this?"."""
    path: Path
    rel: str
    reason: str
    size: int = 0
    candidates: list[str] = field(default_factory=list)
    companions: list[Path] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.path.name

    def to_item(self, system: str) -> "ImportItem":
        return ImportItem(self.path, self.rel, system, self.size, list(self.companions))


@dataclass
class ScanResult:
    items: list[ImportItem] = field(default_factory=list)
    unclear: int = 0  # ROM-like files (zip, iso...) whose console could not be told
    truncated: bool = False
    cancelled: bool = False
    skipped: list[Skipped] = field(default_factory=list)  # everything game-like we did not add, with the reason
    seen: dict = field(default_factory=dict)  # file type -> how many files of it were in the folder
    files_seen: int = 0

    @property
    def ambiguous(self) -> list[Skipped]:
        """Skipped files that the user can sort out by naming the system."""
        return [k for k in self.skipped if k.candidates]

    def seen_text(self) -> str:
        """'1 .iso, 1 .txt' - what was in the folder, so an empty result is never a mystery."""
        if not self.seen:
            return "no files"
        bits = [f"{n} .{e}" if e else f"{n} without a file type"
                for e, n in sorted(self.seen.items(), key=lambda kv: (-kv[1], kv[0]))[:8]]
        more = len(self.seen) - 8
        return ", ".join(bits) + (f" and {more} other types" if more > 0 else "")


# ------------------------------------------------------------------ looking inside disc images
XBOX_MAGIC = b"MICROSOFT*XBOX*MEDIA"
# where the Xbox "XDVDFS" volume starts inside the image: plain .iso, and the 3 layouts of full disc dumps
XBOX_OFFSETS = (0x0, 0x18300000, 0x0FD90000, 0x02090000)


def _read_at(fh, offset: int, n: int) -> bytes:
    try:
        fh.seek(offset)
        return fh.read(n)
    except (OSError, ValueError):
        return b""


def sniff_disc(path: Path) -> str:
    """Tell which console a disc image is for by LOOKING INSIDE it (never by trusting the name).
    Returns a system id ("xbox", "gamecube", "wii", "ps2", "ps1", "psp", "segacd", "saturn") or "" when unsure."""
    try:
        with open(path, "rb") as fh:
            for off in XBOX_OFFSETS:  # Xbox: "MICROSOFT*XBOX*MEDIA" at sector 32 of the volume
                if _read_at(fh, off + 0x10000, 20) == XBOX_MAGIC:
                    return "xbox"
            head = _read_at(fh, 0, 0x30)
            if len(head) >= 0x20:
                if head[0x1C:0x20] == bytes.fromhex("C2339F3D"):
                    return "gamecube"
                if head[0x18:0x1C] == bytes.fromhex("5D1C9EA3"):
                    return "wii"
            if head.startswith(b"SEGADISCSYSTEM"):
                return "segacd"
            if head.startswith(b"SEGA SEGASATURN"):
                return "saturn"
            return _sniff_iso9660(fh)
    except OSError:
        return ""


def _sniff_iso9660(fh) -> str:
    pvd = _read_at(fh, 0x8000, 2048)
    if len(pvd) < 190 or pvd[1:6] != b"CD001":
        return ""
    lba = int.from_bytes(pvd[158:162], "little")
    size = int.from_bytes(pvd[166:170], "little")
    if not 0 < size <= 1024 * 1024:
        return ""
    names: dict[str, tuple[int, int]] = {}
    data = _read_at(fh, lba * 2048, size)
    i = 0
    while i < len(data):
        ln = data[i]
        if ln == 0:  # records never straddle a sector: skip to the next one
            i = (i // 2048 + 1) * 2048
            continue
        rec = data[i:i + ln]
        if len(rec) >= 34:
            nlen = rec[32]
            nm = rec[33:33 + nlen].decode("ascii", "replace").split(";")[0].upper()
            names[nm] = (int.from_bytes(rec[2:6], "little"), int.from_bytes(rec[10:14], "little"))
        i += ln
    if "PSP_GAME" in names or "UMD_DATA.BIN" in names:
        return "psp"
    if "SYSTEM.CNF" in names:
        lba2, size2 = names["SYSTEM.CNF"]
        text = _read_at(fh, lba2 * 2048, min(size2, 2048)).decode("ascii", "replace").upper()
        if "BOOT2" in text:
            return "ps2"
        if re.search(r"\bBOOT\s*=", text):
            return "ps1"
    return ""


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _hint_table(cfg: Config) -> dict[str, str]:
    """normalised folder name -> system id"""
    table: dict[str, str] = {}
    extra = {"megadrive": "genesis", "sega": "", "psx": "ps1", "psone": "ps1", "playstation1": "ps1",
             "superfamicom": "snes", "famicom": "nes", "sfc": "snes", "gameboyadvance": "gba",
             "gameboycolor": "gb", "gbc": "gb", "nintendods": "nds", "dolphin": "gamecube", "ngc": "gamecube",
             "turbografx16": "pce", "pcengine": "pce", "atari": "", "ps": "ps1", "psone": "ps1",
             "sega32x": "", "naomi": "arcade", "fbneo": "arcade", "xbox": "xbox", "wiiu": "wiiu",
             "playstationportable": "psp", "amiga500": "amiga", "c64": "c64", "dosbox": "dos"}
    for sc in cfg.systems.values():
        for name in (sc.id, sc.name, *sc.aliases):
            n = _norm(name)
            if n:
                table.setdefault(n, sc.id)
    for k, v in extra.items():
        if v and v in cfg.systems:
            table.setdefault(k, v)
    return table


def _extension_table(cfg: Config) -> dict[str, list[str]]:
    table: dict[str, list[str]] = {}
    for sc in cfg.systems.values():
        for e in sc.extensions:
            table.setdefault(e.lower().lstrip("."), []).append(sc.id)
    return table


def _companions(path: Path) -> list[Path]:
    """Extra files a disc image needs: tracks listed in a .cue / .gdi sheet."""
    ext = path.suffix.lower()
    out: list[Path] = []
    try:
        if path.stat().st_size > 2 * 1024 * 1024:
            return out
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    names: list[str] = []
    if ext == ".cue":
        names = re.findall(r'^\s*FILE\s+"([^"]+)"', text, flags=re.I | re.M)
        names += [m for m in re.findall(r"^\s*FILE\s+([^\s\"]+)\s", text, flags=re.I | re.M)]
    elif ext == ".gdi":
        for line in text.splitlines()[1:]:
            m = re.match(r'\s*\d+\s+\d+\s+\d+\s+\d+\s+("([^"]+)"|(\S+))', line)
            if m:
                names.append(m.group(2) or m.group(3))
    for n in dict.fromkeys(names):
        cand = path.parent / n
        try:
            if cand.is_file() and cand != path:
                out.append(cand)
        except OSError:
            pass
    return out


def scan_for_roms(root: str | Path, cfg: Config, cancel: threading.Event | None = None,
                  progress: Callable[[int], None] | None = None) -> ScanResult:
    """Walk `root` (read-only) and list the game files we recognise."""
    root = Path(root)
    res = ScanResult()
    ext_table = _extension_table(cfg)
    hints = _hint_table(cfg)
    found: list[tuple[Path, str]] = []  # (path, ext)
    folder_games: list[tuple[Path, str]] = []
    seen_files = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False, onerror=lambda e: None):
        if cancel is not None and cancel.is_set():
            res.cancelled = True
            return res
        if "ps3" in cfg.systems and roms._ps3_game_in(dirpath, dirnames, filenames):
            folder_games.append((Path(dirpath), "ps3"))  # a PS3 game folder is one game: do not look inside
            dirnames[:] = []
            continue
        if "xbox" in cfg.systems and any(f.lower() == "default.xbe" for f in filenames):
            folder_games.append((Path(dirpath), "xbox"))  # an unpacked original-Xbox game (default.xbe)
            dirnames[:] = []
            continue
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d.lower() not in SKIP_DIRS)
        for fn in sorted(filenames):
            seen_files += 1
            if fn.startswith("."):  # also macOS "._junk" files
                continue
            ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
            res.files_seen += 1
            res.seen[ext] = res.seen.get(ext, 0) + 1
            if ext in ext_table:
                found.append((Path(dirpath) / fn, ext))
                if len(found) >= MAX_FILES:
                    res.truncated = True
                    break
        if progress and seen_files % 50 == 0:
            progress(len(found))
        if res.truncated:
            break

    # disc sheets first: their track files must not show up as separate games
    claimed: set[Path] = set()
    sheet_companions: dict[Path, list[Path]] = {}
    for path, ext in found:
        if ext in ("cue", "gdi"):
            comp = _companions(path)
            sheet_companions[path] = comp
            claimed.update(comp)

    def hint_for(path: Path) -> str:
        try:
            parts = list(path.relative_to(root).parts[:-1])
        except ValueError:
            parts = list(path.parts[:-1])
        parts.append(root.name)  # the folder you picked may itself be called "snes"
        for comp in reversed(parts):
            sid = hints.get(_norm(comp), "")
            if sid:
                return sid
        return ""

    for path, ext in found:
        if path in claimed and ext not in ("cue", "gdi"):
            continue
        cands = ext_table.get(ext, [])
        system = ""
        if ext in DISC_EXT:  # look inside the image first: that is the only reliable way
            sniffed = sniff_disc(path)
            if sniffed in cands:
                system = sniffed
        if not system and (ext in AMBIGUOUS_EXT or len(cands) != 1):
            hinted = hint_for(path)
            if hinted and (hinted in cands or ext in AMBIGUOUS_EXT):
                system = hinted
            if not system and len(cands) == 1 and ext not in AMBIGUOUS_EXT:
                system = cands[0]
        elif not system:
            system = cands[0]
        comp = sheet_companions.get(path, [])
        try:
            size = path.stat().st_size + sum(c.stat().st_size for c in comp)
            rel = str(path.relative_to(root))
        except (OSError, ValueError):
            continue
        if not system:
            res.unclear += 1
            res.skipped.append(Skipped(path, rel, "Could not tell which console this is for (." + ext + " files are "
                                       "used by several). Choose the system, or put it in a folder named after "
                                       "the console.", size, list(cands), comp))
            continue
        res.items.append(ImportItem(path, rel, system, size, comp))
    for folder, fsys in folder_games:
        files: list[Path] = []
        for dp, _dn, fns in os.walk(folder):
            files += [Path(dp) / f for f in fns]
        try:
            size = sum(f.stat().st_size for f in files)
            rel = str(folder.relative_to(root)) if folder != root else folder.name
        except (OSError, ValueError):
            continue
        res.items.append(ImportItem(folder, rel, fsys, size, files, True))
    order = {sid: i for i, sid in enumerate(cfg.systems)}
    res.items.sort(key=lambda it: (order.get(it.system, 999), it.name.lower()))
    return res


# ------------------------------------------------------------------ copying
def default_games_root() -> Path:
    return Path.home() / "Games" / "Atari"


def destination_for(cfg: Config, system: str, games_root: Path | None = None) -> Path:
    """Configured ROM folder for the system if there is one, else ~/Games/Atari/<system>."""
    sc = cfg.systems.get(system)
    if sc and sc.roms:
        return Path(sc.roms[0]).expanduser()
    return (games_root or default_games_root()) / system


@dataclass
class CopyResult:
    copied: int = 0
    skipped_duplicates: int = 0
    failed: list[str] = field(default_factory=list)
    bytes_copied: int = 0
    cancelled: bool = False
    systems: dict[str, Path] = field(default_factory=dict)  # system id -> folder files went into
    error: str = ""


def _existing_index(folder: Path) -> set[tuple[str, int]]:
    seen: set[tuple[str, int]] = set()
    for dirpath, _dirs, files in os.walk(folder):
        for f in files:
            try:
                seen.add((f.lower(), os.path.getsize(os.path.join(dirpath, f))))
            except OSError:
                pass
    return seen


def _unique(path: Path) -> Path:
    n = 2
    while True:
        cand = path.with_name(f"{path.stem} ({n}){path.suffix}")
        if not cand.exists():
            return cand
        n += 1


def _nearest_existing(p: Path) -> Path:
    while not p.exists() and p.parent != p:
        p = p.parent
    return p


def copy_items(items: list[ImportItem], cfg: Config, progress: Callable[[int, int, str, int], None] | None = None,
               cancel: threading.Event | None = None, games_root: Path | None = None) -> CopyResult:
    """Copy the chosen games. progress(bytes_done, bytes_total, file name, files_done).
    Reads the stick, never writes to it. Already-present files (same name and size) are skipped."""
    res = CopyResult()
    index: dict[str, set] = {}
    plan: list[tuple[ImportItem, Path, list[tuple[Path, Path]]]] = []
    for it in items:
        dest_dir = destination_for(cfg, it.system, games_root)
        if it.system not in index:
            index[it.system] = _existing_index(dest_dir) if dest_dir.is_dir() else set()
        idx = index[it.system]
        files = [it.path, *it.companions]
        pairs: list[tuple[Path, Path]] = []
        if it.is_dir:  # whole game folder: copy the tree below <dest>/<folder name>
            sub = dest_dir / re.sub(r'[\\/:*?"<>|]', "_", it.path.name)
            if sub.exists():
                res.skipped_duplicates += 1
                continue
            plan.append((it, dest_dir, [(f, sub / f.relative_to(it.path)) for f in it.companions]))
            continue
        if it.companions:  # keep a disc image with its tracks together in its own folder
            sub = dest_dir / re.sub(r'[\\/:*?"<>|]', "_", it.path.stem)
            pairs = [(f, sub / f.name) for f in files]
        else:
            target = dest_dir / it.path.name
            pairs = [(it.path, target)]
        try:
            main_size = it.path.stat().st_size
        except OSError:
            res.failed.append(f"{it.name} (cannot be read)")
            continue
        if (it.path.name.lower(), main_size) in idx:
            res.skipped_duplicates += 1
            continue
        if not it.companions and pairs[0][1].exists():  # same name, different size: keep both
            pairs = [(it.path, _unique(pairs[0][1]))]
        plan.append((it, dest_dir, pairs))

    total = 0
    for _it, _d, pairs in plan:
        for src, _dst in pairs:
            try:
                total += src.stat().st_size
            except OSError:
                pass
    # enough room?
    needed_by_dir: dict[Path, int] = {}
    for it, dest_dir, pairs in plan:
        needed_by_dir[dest_dir] = needed_by_dir.get(dest_dir, 0) + it.size
    for d, need in needed_by_dir.items():
        try:
            free = shutil.disk_usage(_nearest_existing(d)).free
        except OSError:
            continue
        if need > free:
            res.error = (f"Not enough free space on this computer: {human_size(need)} needed in {d}, "
                         f"only {human_size(free)} free.")
            return res

    done = 0
    files_done = 0
    for it, dest_dir, pairs in plan:
        if cancel is not None and cancel.is_set():
            res.cancelled = True
            break
        ok = True
        written: list[Path] = []
        for src, dst in pairs:
            tmp = dst.with_name(dst.name + ".part")
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                with open(src, "rb") as fin, open(tmp, "wb") as fout:
                    while True:
                        if cancel is not None and cancel.is_set():
                            raise InterruptedError
                        buf = fin.read(CHUNK)
                        if not buf:
                            break
                        fout.write(buf)
                        done += len(buf)
                        if progress:
                            progress(done, total, it.name, files_done)
                os.replace(tmp, dst)
                written.append(dst)
            except InterruptedError:
                res.cancelled = True
                ok = False
            except OSError as exc:
                res.failed.append(f"{it.name}: {exc.strerror or exc}")
                ok = False
            if not ok:
                try:
                    tmp.unlink()
                except OSError:
                    pass
                for w in written:  # do not leave half a game behind
                    try:
                        w.unlink()
                    except OSError:
                        pass
                if it.is_dir:
                    shutil.rmtree(dest_dir / re.sub(r'[\\/:*?"<>|]', "_", it.path.name), ignore_errors=True)
                break
        if ok:
            res.copied += 1
            files_done += 1
            res.bytes_copied += it.size
            res.systems.setdefault(it.system, dest_dir)
            if not it.is_dir:
                index[it.system].add((it.path.name.lower(), it.path.stat().st_size))
        if res.cancelled:
            break
    if progress:
        progress(done, total, "", files_done)
    return res
