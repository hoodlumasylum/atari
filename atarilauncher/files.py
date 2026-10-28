"""A small, safe file viewer for the places a game lives: ~/Downloads, ~/Games and ~/Videos.

Everything works on one button per job so it can be driven with a controller: list a folder with sizes and free disk space, Open,
Extract here (zip, tar, 7z, rar - one press), Add to my games, Rename and Delete (with a confirm step in the screen).
Safety: every action is limited to the three places above (``inside_roots``), a place itself can never be renamed or deleted, symlinks
are never followed out of them, archives are unpacked into a NEW folder beside the archive (never over anything), a path inside an
archive that would leave that folder stops the whole unpack, and nothing here ever raises (every result is a plain sentence).
Pure Python with injectable tools, so it can be tested. No download sites, no games and no BIOS files are known to this module."""
from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import threading
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import downloads, importer

ARCHIVE_SUFFIXES = {
    ".zip": "zip", ".tar": "tar", ".tar.gz": "tar", ".tgz": "tar", ".tar.xz": "tar", ".txz": "tar", ".tar.bz2": "tar", ".tbz2": "tar",
    ".7z": "7z", ".rar": "rar",
}
VIDEO_EXT = (".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v")
SEVEN = ("7z", "7zz", "7za", "7zr")
LIST_CAP = 400


class FileError(Exception):
    """A plain-English reason shown on screen."""


class NeedPassword(Exception):
    pass


# ------------------------------------------------------------------ places
def roots(home: Path | None = None) -> list[tuple[str, Path]]:
    """(label, folder) of the places that exist. ~/Games/Code is only a second name for ~/Games/Atari, so it is not listed twice."""
    h = home or Path.home()
    out: list[tuple[str, Path]] = []
    for label, rel in (("Downloads", "Downloads"), ("Games", "Games"), ("Videos", "Videos")):
        p = h / rel
        if p.is_dir():
            out.append((label, p))
    return out


def inside_roots(path: Path, home: Path | None = None) -> bool:
    """True when path (symlinks resolved) is a place or inside one."""
    try:
        real = path.resolve()
    except OSError:
        return False
    for _label, r in roots(home):
        try:
            rr = r.resolve()
        except OSError:
            continue
        if real == rr or str(real).startswith(str(rr) + os.sep):
            return True
    return False


def is_root(path: Path, home: Path | None = None) -> bool:
    try:
        return any(path.resolve() == r.resolve() for _l, r in roots(home))
    except OSError:
        return True


def free_space(path: Path) -> tuple[int, int]:
    """(free bytes, total bytes) of the disk the folder is on; (0, 0) when unknown."""
    try:
        u = shutil.disk_usage(path)
        return u.free, u.total
    except OSError:
        return 0, 0


def free_text(path: Path) -> str:
    free, total = free_space(path)
    return f"Free space here: {importer.human_size(free)} of {importer.human_size(total)}" if total else "Free space: unknown"


# ------------------------------------------------------------------ listing
@dataclass
class Entry:
    path: Path
    is_dir: bool
    size: int
    mtime: float
    count: int = 0              # folders: number of items directly inside

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def kind(self) -> str:
        return "folder" if self.is_dir else (archive_kind(self.path) or ("video" if self.name.lower().endswith(VIDEO_EXT) else "file"))


def archive_kind(path: Path | str) -> str:
    low = Path(path).name.lower()
    for suf in sorted(ARCHIVE_SUFFIXES, key=len, reverse=True):
        if low.endswith(suf):
            return ARCHIVE_SUFFIXES[suf]
    return ""


def archive_stem(path: Path | str) -> str:
    n = Path(path).name
    low = n.lower()
    for suf in sorted(ARCHIVE_SUFFIXES, key=len, reverse=True):
        if low.endswith(suf):
            return n[: -len(suf)] or n
    return n


def list_dir(path: Path, cap: int = LIST_CAP) -> tuple[list[Entry], bool]:
    """(entries, more than cap?) folders first (A-Z), then files (A-Z). Hidden files are not shown."""
    dirs: list[Entry] = []
    files: list[Entry] = []
    try:
        entries = list(os.scandir(path))
    except OSError:
        return [], False
    for e in entries:
        if e.name.startswith("."):
            continue
        try:
            is_dir = e.is_dir(follow_symlinks=False)
            if not is_dir and not e.is_file(follow_symlinks=False):
                continue                                    # symlinks and special files are not shown
            st = e.stat(follow_symlinks=False)
        except OSError:
            continue
        if is_dir:
            try:
                n = sum(1 for _ in os.scandir(e.path))
            except OSError:
                n = 0
            dirs.append(Entry(Path(e.path), True, 0, st.st_mtime, n))
        else:
            files.append(Entry(Path(e.path), False, st.st_size, st.st_mtime))
    dirs.sort(key=lambda x: x.name.lower())
    files.sort(key=lambda x: x.name.lower())
    both = dirs + files
    return both[:cap], len(both) > cap


def folder_size(path: Path, cap: int = 2000) -> int:
    return downloads.folder_info(path, cap)[0]


# ------------------------------------------------------------------ rename / delete
def check_new_name(path: Path, new: str) -> str:
    """'' when new is a good name for path (same folder, nothing there yet); otherwise the reason."""
    new = new.strip()
    if not new or new in (".", ".."):
        return "Type a name first."
    if "/" in new or "\0" in new:
        return "A name cannot contain a slash (/)."
    if len(new.encode()) > 240:
        return "That name is too long."
    if new == path.name:
        return "That is the same name."
    if (path.parent / new).exists() or (path.parent / new).is_symlink():
        return f"\"{new}\" already exists here."
    return ""


def rename(path: Path, new: str, home: Path | None = None) -> tuple[bool, str]:
    try:
        if not inside_roots(path, home) or is_root(path, home):
            return False, "Code only renames things inside Downloads, Games and Videos."
        why = check_new_name(path, new)
        if why:
            return False, why
        target = path.parent / new.strip()
        os.rename(path, target)
        return True, f"Renamed to {target.name}."
    except OSError as exc:
        return False, f"Could not rename it: {exc.strerror or exc}"


def delete(path: Path, home: Path | None = None) -> tuple[bool, str]:
    """Delete a file or a folder with everything in it. Never a place itself, never anything outside the places, never through a symlink."""
    try:
        if not inside_roots(path, home) or is_root(path, home):
            return False, "Code only deletes things inside Downloads, Games and Videos (never those folders themselves)."
        if path.is_symlink():
            path.unlink()                                       # only the link, never what it points to
            return True, f"Removed the link {path.name}."
        if not path.exists():
            return False, "That is already gone."
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        return True, f"Deleted {path.name}."
    except OSError as exc:
        return False, f"Could not delete it: {exc.strerror or exc}"


# ------------------------------------------------------------------ open
def opener(path: Path, which: Callable | None = None) -> list[str]:
    """The command that opens a file: a video in mpv / VLC full screen, anything else with the system's default (xdg-open)."""
    which = which or shutil.which
    p = str(path)
    if path.name.lower().endswith(VIDEO_EXT):
        if which("mpv"):
            return ["mpv", "--fs", "--", p]
        if which("vlc"):
            return ["vlc", "--fullscreen", p]
    if which("xdg-open"):
        return ["xdg-open", p]
    return []


def open_file(path: Path, which: Callable | None = None, popen: Callable | None = None, home: Path | None = None) -> tuple[bool, str]:
    which = which or shutil.which
    popen = popen or subprocess.Popen
    cmd = opener(path, which)
    if not inside_roots(path, home):
        return False, "Code only opens things inside Downloads, Games and Videos."
    if not cmd:
        return False, "No program is set up to open this kind of file (xdg-open is missing)."
    try:
        popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        return False, f"Could not open it: {exc.strerror or exc}"
    return True, f"Opened {path.name}. Close that window to come back here."


# ------------------------------------------------------------------ extract
def tool_for(kind: str, which: Callable | None = None) -> tuple[str, str]:
    """(program, how) able to unpack this kind, '' when none. zip and tar need nothing (Python); rar prefers unrar; 7z / rar use 7-Zip."""
    which = which or shutil.which
    if kind in ("zip", "tar"):
        return "python", ""
    if kind == "rar":
        for exe in ("unrar", "unrar-free", "unar"):
            if which(exe):
                return which(exe), exe
    seven = next((which(x) for x in SEVEN if which(x)), "")
    if seven:
        return seven, "7z"
    return "", ""


def missing_tool(kind: str, which: Callable | None = None) -> str:
    """The id of the app Code can install for this kind ('7zip' / 'unrar'), '' when nothing is missing."""
    if tool_for(kind, which)[0]:
        return ""
    return "unrar" if kind == "rar" else "7zip"


def _inside(dest: Path, name: str) -> bool:
    root = dest.resolve()
    target = (dest / name).resolve()
    return target == root or str(target).startswith(str(root) + os.sep)


def unique_folder(archive: Path) -> Path:
    base = archive.parent / archive_stem(archive)
    if not base.exists() and not base.is_symlink():
        return base
    n = 2
    while (archive.parent / f"{base.name} ({n})").exists():
        n += 1
    return archive.parent / f"{base.name} ({n})"


def _zip_needs_password(zf: zipfile.ZipFile) -> bool:
    return any(i.flag_bits & 0x1 for i in zf.infolist())


def _extract_zip(archive: Path, dest: Path, password: str, progress, cancel) -> None:
    with zipfile.ZipFile(archive) as zf:
        infos = zf.infolist()
        for i in infos:
            if not _inside(dest, i.filename):
                raise FileError("That archive contains an unsafe path, so nothing was unpacked.")
        if _zip_needs_password(zf) and not password:
            raise NeedPassword()
        pw = password.encode() if password else None
        for n, info in enumerate(infos):
            if cancel is not None and cancel.is_set():
                raise FileError("Cancelled.")
            try:
                zf.extract(info, dest, pwd=pw)
            except RuntimeError as exc:
                if "password" in str(exc).lower() or "encrypted" in str(exc).lower():
                    raise NeedPassword()
                raise
            except NotImplementedError:
                raise FileError("NEED7Z")                          # e.g. AES encryption or a compression Python lacks: 7-Zip can do it
            if progress:
                progress(n + 1, len(infos))


def _extract_tar(archive: Path, dest: Path, progress, cancel) -> None:
    with tarfile.open(archive) as tf:
        members = tf.getmembers()
        for m in members:
            if not _inside(dest, m.name):
                raise FileError("That archive contains an unsafe path, so nothing was unpacked.")
        keep = [m for m in members if m.isdir() or m.isreg()]      # no links, devices or fifos
        for n, m in enumerate(keep):
            if cancel is not None and cancel.is_set():
                raise FileError("Cancelled.")
            try:
                tf.extract(m, dest, filter="data")          # Python 3.12+: also refuses odd permissions / absolute names
            except TypeError:
                tf.extract(m, dest)
            if progress:
                progress(n + 1, len(keep))


def _extract_external(kind: str, exe: str, how: str, archive: Path, dest: Path, password: str, run: Callable) -> None:
    """7z / unrar / unar. A password goes on the command line (it is visible to this computer's other users for the seconds this runs)."""
    if how == "7z":
        cmd = [exe, "x", "-y", "-bd", f"-o{dest}"] + ([f"-p{password}"] if password else ["-p"]) + [str(archive)]
    elif how in ("unrar", "unrar-free"):
        cmd = [exe, "x", "-y"] + ([f"-p{password}"] if password else ["-p-"]) + [str(archive), str(dest) + os.sep]
    else:                                                                                   # unar
        cmd = [exe, "-o", str(dest), "-q"] + (["-p", password] if password else []) + [str(archive)]
    r = run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=7200)
    if r.returncode == 0:
        return
    text = ((r.stdout or "") + (r.stderr or "")).lower()
    if any(w in text for w in ("wrong password", "enter password", "password is incorrect", "encrypted", "incorrect password", "need password", "password required")):
        raise NeedPassword()
    raise FileError("The archive could not be unpacked (it may be damaged, or the download is not finished).")


@dataclass
class Extraction:
    ok: bool
    text: str
    dest: Path | None = None
    needs_password: bool = False
    needs_tool: str = ""          # app id to install ("7zip" / "unrar")


def extract(archive: Path, password: str = "", progress: Callable[[int, int], None] | None = None, cancel: threading.Event | None = None,
            which: Callable | None = None, run: Callable | None = None, home: Path | None = None) -> Extraction:
    """Unpack an archive into a new folder beside it. Never raises. On a password problem, needs_password is set; the half-made folder is removed."""
    which = which or shutil.which
    run = run or subprocess.run
    kind = archive_kind(archive)
    if not kind:
        return Extraction(False, "That is not an archive Code can unpack (zip, tar, 7z, rar).")
    if not inside_roots(archive, home):
        return Extraction(False, "Code only unpacks things inside Downloads, Games and Videos.")
    if not archive.is_file():
        return Extraction(False, "That file is gone.")
    if archive.name.lower().endswith(downloads.PARTIAL):
        return Extraction(False, "That file is still downloading. Wait until it is finished.")
    exe, how = tool_for(kind, which)
    if not exe:
        name = "7-Zip" if kind != "rar" else "unrar (or 7-Zip)"
        return Extraction(False, f"Code needs {name} to open .{kind} files. Press the Install button below.", needs_tool=missing_tool(kind, which))
    dest = unique_folder(archive)
    made = False
    try:
        dest.mkdir(parents=True)
        made = True
        try:
            if kind == "zip":
                _extract_zip(archive, dest, password, progress, cancel)
            elif kind == "tar":
                _extract_tar(archive, dest, progress, cancel)
            else:
                if progress:
                    progress(0, 0)
                _extract_external(kind, exe, how, archive, dest, password, run)
        except FileError as exc:
            if str(exc) != "NEED7Z":
                raise
            seven, _ = tool_for("7z", which)
            if not seven:
                raise FileError("This zip needs 7-Zip (it is encrypted in a way Code's own unzip cannot read). Install 7-Zip below.")
            _extract_external("7z", seven, "7z", archive, dest, password, run)
        if progress:
            progress(1, 1)
        return Extraction(True, f"Unpacked into the folder \"{dest.name}\" ({_count(dest)} items).", dest)
    except NeedPassword:
        _cleanup(dest, made)
        return Extraction(False, "This archive is protected with a password." if not password else "That password did not work.", needs_password=True)
    except FileError as exc:
        _cleanup(dest, made)
        t = str(exc)
        return Extraction(False, t, needs_tool=("7zip" if "Install 7-Zip" in t else ""))
    except (zipfile.BadZipFile, tarfile.TarError, EOFError) as exc:
        _cleanup(dest, made)
        return Extraction(False, "That archive could not be opened. Is the download complete? (" + str(exc)[:80] + ")")
    except subprocess.TimeoutExpired:
        _cleanup(dest, made)
        return Extraction(False, "Unpacking took too long and was stopped.")
    except OSError as exc:
        _cleanup(dest, made)
        return Extraction(False, f"Could not unpack it: {exc.strerror or exc}")


def _count(dest: Path) -> int:
    try:
        return sum(len(f) + len(d) for _r, d, f in os.walk(dest))
    except OSError:
        return 0


def _cleanup(dest: Path, made: bool) -> None:
    if made:
        shutil.rmtree(dest, ignore_errors=True)
