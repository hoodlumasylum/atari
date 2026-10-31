"""Looking inside .zip / .7z / .rar (and .tar.*) archives without unpacking all of them, and unpacking only chosen files.

zip and tar are read by Python itself; 7z and rar need the 7-Zip program (`7z`, from p7zip-full; rar also needs p7zip-rar on some
systems). Nothing here raises: a damaged, password-protected or unreadable archive just gives an empty list and a reason."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path
from typing import Callable

ARCHIVE_EXT = (".zip", ".7z", ".rar", ".tar.gz", ".tgz", ".tar.xz", ".tar.bz2", ".tar")


def is_archive(path: str | Path) -> bool:
    return str(path).lower().endswith(ARCHIVE_EXT)


def seven_zip(which: Callable = shutil.which) -> str:
    return next((which(x) for x in ("7z", "7zz", "7za") if which(x)), "") or ""


def _safe(name: str) -> bool:
    n = name.replace("\\", "/")
    return bool(n) and not n.startswith("/") and ".." not in n.split("/")


def members(path: Path, which: Callable = shutil.which, runner: Callable | None = None) -> tuple[list[tuple[str, int]], str]:
    """([(name inside the archive, size)], problem text). Folders are left out."""
    low = str(path).lower()
    try:
        if low.endswith(".zip"):
            with zipfile.ZipFile(path) as zf:
                if any(i.flag_bits & 0x1 for i in zf.infolist()):
                    return [], "it has a password"
                return [(i.filename, i.file_size) for i in zf.infolist() if not i.is_dir() and _safe(i.filename)], ""
        if low.endswith((".tar.gz", ".tgz", ".tar.xz", ".tar.bz2", ".tar")):
            with tarfile.open(path) as tf:
                return [(m.name, m.size) for m in tf.getmembers() if m.isreg() and _safe(m.name)], ""
    except (zipfile.BadZipFile, tarfile.TarError, OSError, EOFError, RuntimeError) as exc:
        return [], f"it could not be opened ({exc})"
    seven = seven_zip(which)
    if not seven:
        return [], "the 7-Zip program is needed for this kind of archive (sudo apt install p7zip-full)"
    runner = runner or subprocess.run
    try:
        p = runner([seven, "l", "-slt", "-ba", "-p", str(path)], capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        return [], f"7-Zip could not run ({exc})"
    if p.returncode != 0:
        return [], "7-Zip could not open it (damaged, or it needs a password)"
    out = []
    for block in re.split(r"\n\s*\n", p.stdout or ""):
        name = re.search(r"^Path = (.+)$", block, re.M)
        size = re.search(r"^Size = (\d+)$", block, re.M)
        attrs = re.search(r"^Attributes = (\S*)", block, re.M)
        folder = re.search(r"^Folder = \+", block, re.M) or (attrs and attrs.group(1).startswith("D"))
        if name and not folder and _safe(name.group(1)):
            out.append((name.group(1), int(size.group(1)) if size else 0))
    return out, ""


def extract(path: Path, names: list[str] | None, dest: Path, which: Callable = shutil.which, runner: Callable | None = None) -> tuple[bool, str]:
    """Unpack these members (None = everything) into dest, keeping their folders. -> (worked, problem text)."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    low = str(path).lower()
    want = set(names) if names is not None else None
    try:
        if low.endswith(".zip"):
            with zipfile.ZipFile(path) as zf:
                for i in zf.infolist():
                    if (want is None or i.filename in want) and _safe(i.filename):
                        zf.extract(i, dest)
            return True, ""
        if low.endswith((".tar.gz", ".tgz", ".tar.xz", ".tar.bz2", ".tar")):
            with tarfile.open(path) as tf:
                for m in tf.getmembers():
                    if (m.isreg() or m.isdir()) and (want is None or m.name in want) and _safe(m.name):
                        tf.extract(m, dest)
            return True, ""
    except (zipfile.BadZipFile, tarfile.TarError, OSError, EOFError, RuntimeError) as exc:
        return False, f"could not unpack ({exc})"
    seven = seven_zip(which)
    if not seven:
        return False, "the 7-Zip program is needed (sudo apt install p7zip-full)"
    runner = runner or subprocess.run
    cmd = [seven, "x", "-y", "-p", f"-o{dest}", str(path)] + (["--", *sorted(want)] if want else [])
    try:
        p = runner(cmd, capture_output=True, text=True, timeout=3600, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"7-Zip could not run ({exc})"
    if p.returncode != 0:
        return False, "7-Zip could not unpack it (damaged, or it needs a password)"
    # never keep anything that ended up outside dest (a hostile archive)
    root = os.path.realpath(dest)
    for dp, _dn, fns in os.walk(dest):
        for f in fns:
            if not os.path.realpath(os.path.join(dp, f)).startswith(root + os.sep):
                return False, "the archive contains unsafe paths"
    return True, ""
