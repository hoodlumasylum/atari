"""Original Xbox helpers: xemu only starts a disc image (.iso / .xiso), not an unpacked game folder
(the one with default.xbe). For such a folder we build an .xiso image once (with `extract-xiso`) and start that."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from . import paths


def is_xbe_folder_game(rom: str) -> bool:
    return Path(rom).name.lower() == "default.xbe"


def find_extract_xiso() -> str:
    return shutil.which("extract-xiso") or shutil.which("extract-xiso.AppImage") or ""


def cache_image_path(rom: str, cache_dir: Path | None = None) -> Path:
    folder = Path(rom).parent
    safe = re.sub(r'[\\/:*?"<>|]', "_", folder.name) or "xbox-game"
    return (cache_dir or paths.data_dir() / "xiso") / f"{safe}.xiso"


NEEDS_TOOL = ("This Xbox game is an unpacked folder (it has a default.xbe), but xemu can only start a disc image. "
              "CodeAque can turn the folder into one with the small free tool 'extract-xiso', which is not installed. "
              "Easiest: use the game as a single .iso file instead (put the .iso in your Xbox folder).")


MAGIC = b"MICROSOFT*XBOX*MEDIA"
XISO_AT = 0x10000                 # XDVDFS header of an XISO (sector 32)
REDUMP_AT = 0x18300000 + 0x10000  # same header inside a full Redump disc dump (video partition first)


def iso_kind(path: str) -> str:
    """'xiso' (xemu can start it), 'redump' (a full disc dump: needs turning into an XISO), 'unknown' (not an Xbox disc / unreadable)."""
    try:
        with open(path, "rb") as f:
            for kind, at in (("xiso", XISO_AT), ("redump", REDUMP_AT)):
                f.seek(at)
                if f.read(len(MAGIC)) == MAGIC:
                    return kind
    except OSError:
        pass
    return "unknown"


NOT_XISO = ("This Xbox game is a full disc dump, not an XISO, and xemu can only start XISO images (it shows the Xbox logo and stops). "
            "CodeAque can convert it once with the free tool 'extract-xiso' (not installed - get it from github.com/XboxDev/extract-xiso), "
            "or convert it on another computer. The original file is kept.")


def disc_image_for(rom: str, runner=subprocess.run, cache_dir: Path | None = None) -> str:
    """Path of a disc image xemu can start for this game. Returns `rom` unchanged for normal .iso games.
    Raises RuntimeError with a plain-English message when the folder cannot be converted."""
    if not is_xbe_folder_game(rom):
        fx = fixed_path(rom)
        if Path(rom).suffix.lower() == ".iso" and fx.is_file() and iso_kind(str(fx)) == "xiso":
            return str(fx)
        if Path(rom).suffix.lower() == ".iso" and iso_kind(rom) == "redump":
            return rewrite_redump(rom, runner, cache_dir)
        return rom
    target = cache_image_path(rom, cache_dir)
    if target.is_file() and target.stat().st_size > 0:
        return str(target)
    tool = find_extract_xiso()
    if not tool:
        raise RuntimeError(NEEDS_TOOL)
    target.parent.mkdir(parents=True, exist_ok=True)
    folder = Path(rom).parent
    res = runner([tool, "-c", str(folder), str(target)], capture_output=True, text=True, timeout=1800)
    if res.returncode != 0 or not target.is_file():
        try:
            target.unlink()
        except OSError:
            pass
        raise RuntimeError("Could not turn this Xbox game folder into a disc image. "
                           + ((res.stderr or res.stdout or "").strip()[:200]))
    return str(target)


def _linked_input(rom: str, folder: Path) -> Path:
    """extract-xiso -r RENAMES its input to '<name>.old' when it finishes. So it is never given the user's file: it gets a
    hard link (same disk, no copy) - or a symbolic link - in a private folder, and only that link is renamed."""
    folder.mkdir(parents=True, exist_ok=True)
    ln = folder / Path(rom).name
    try:
        os.link(rom, ln)
    except OSError:
        os.symlink(os.path.abspath(rom), ln)
    return ln


def rewrite_redump(rom: str, runner=subprocess.run, cache_dir: Path | None = None) -> str:
    """A full Redump .iso -> an XISO in CodeAque's cache (extract-xiso -r -d <dir>); the original is never touched."""
    out_dir = cache_dir or paths.data_dir() / "xiso"
    target = out_dir / Path(rom).name
    if target.is_file() and iso_kind(str(target)) == "xiso":
        return str(target)
    tool = find_extract_xiso() or (str(tool_path()) if tool_path().is_file() else "")
    if not tool:
        raise RuntimeError(NOT_XISO.replace("(not installed - get it from github.com/XboxDev/extract-xiso)", "") +
                           " Open Options > Fix my game > Fix game file.")
    out_dir.mkdir(parents=True, exist_ok=True)
    import tempfile
    with tempfile.TemporaryDirectory(dir=out_dir, prefix=".in-") as tin:
        res = runner([tool, "-r", "-d", str(out_dir), str(_linked_input(rom, Path(tin)))], capture_output=True, text=True, timeout=3600)
    if res.returncode != 0 or not target.is_file() or iso_kind(str(target)) != "xiso":
        raise RuntimeError("Could not turn this disc dump into an XISO. " + ((res.stderr or res.stdout or "").strip()[:200]))
    return str(target)


# ---- 0.5.7: one-tap "Fix game file" -------------------------------------------------------------------------------------------
# extract-xiso is open source (XboxDev/extract-xiso, BSD-style licence). Pinned official Linux build, checked 31 Oct 2026.
EXTRACT_XISO_URL = "https://github.com/XboxDev/extract-xiso/releases/download/build-202609111233/extract-xiso_Linux.zip"
EXTRACT_XISO_ZIP_SHA256 = "c4b9fbf86b57c74d07fb643522740ae82034d8280ccde24528752cd1cb0b798d"
EXTRACT_XISO_BIN_SHA256 = "ba6d6c8bf48670277476a67324521090758a8c928386b183f09f1281fc2e8818"
DC_MAGIC = b"SEGA SEGAKATANA"


def tool_path() -> Path:
    return paths.data_dir() / "tools" / "extract-xiso"


def find_tool() -> str:
    t = tool_path()
    return find_extract_xiso() or (str(t) if t.is_file() else "")


def game_kind(path: str) -> str:
    """'xiso' | 'redump' | 'dreamcast' | 'other-disc' (a CD/DVD image of another console) | 'unknown'."""
    p = Path(path)
    if p.suffix.lower() in (".gdi", ".cdi", ".chd"):
        return "dreamcast" if p.suffix.lower() != ".chd" else "other-disc"
    k = iso_kind(path)
    if k != "unknown":
        return k
    try:
        with open(path, "rb") as f:
            head = f.read(0x8010)
            if DC_MAGIC in head[:0x100] or DC_MAGIC in head[0x10:0x200]:
                return "dreamcast"
            if head[0x8001:0x8006] == b"CD001":
                f.seek(0)
                big = f.read(0x40000)
                return "dreamcast" if DC_MAGIC in big else "other-disc"
    except OSError:
        pass
    return "unknown"


def problem_text(kind: str) -> str:
    return {
        "redump": "Full disc dump, not an XISO - xemu stops at the Xbox logo. Press \"Fix game file\" (makes a working copy; the original stays).",
        "dreamcast": "This looks like a Dreamcast game, not an Xbox game (Shenmue 1 is a Dreamcast game). Move it to your Dreamcast folder.",
        "other-disc": "This is a disc image of another console (not an Xbox disc), so xemu cannot start it.",
        "unknown": "This file does not look like an Xbox disc image (it may be damaged or not fully copied). xemu would stop at the Xbox logo.",
    }.get(kind, "")


def fixed_path(rom: str) -> Path:
    return Path(rom).with_suffix(".xiso")


def install_tool(fetch=None, say=None) -> str:
    """Download the pinned extract-xiso build, check both checksums, keep it in CodeAque's own tools folder. -> path."""
    import hashlib
    import tempfile
    import urllib.request
    import zipfile
    say = say or (lambda t: None)

    def dl(url, dest):
        req = urllib.request.Request(url, headers={"User-Agent": "CodeAque"})
        with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f)
    fetch = fetch or dl
    t = tool_path()
    t.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=t.parent) as td:
        z = Path(td) / "x.zip"
        say("Getting the free tool extract-xiso...")
        fetch(EXTRACT_XISO_URL, z)
        if hashlib.sha256(z.read_bytes()).hexdigest() != EXTRACT_XISO_ZIP_SHA256:
            raise RuntimeError("The extract-xiso download did not match its checksum - nothing was installed.")
        with zipfile.ZipFile(z) as zf:
            data = zf.read("extract-xiso")
        if hashlib.sha256(data).hexdigest() != EXTRACT_XISO_BIN_SHA256:
            raise RuntimeError("The extract-xiso program did not match its checksum - nothing was installed.")
        tmp = Path(td) / "extract-xiso"
        tmp.write_bytes(data)
        tmp.chmod(0o755)
        os.replace(tmp, t)
    return str(t)


def fix_game_file(rom: str, runner=subprocess.run, say=None, tool: str | None = None, fetch=None) -> tuple[bool, str, str]:
    """A full Redump .iso -> a trimmed XISO COPY next to it ("<name>.xiso"); the original is never changed or deleted.
    -> (ok, plain message, new path)."""
    import tempfile
    say = say or (lambda t: None)
    kind = game_kind(rom)
    if kind == "xiso":
        return True, "This file is already an XISO - nothing to fix.", rom
    if kind != "redump":
        return False, problem_text(kind) or "Not an Xbox disc image.", ""
    dest = fixed_path(rom)
    if dest.is_file() and iso_kind(str(dest)) == "xiso":
        return True, f"Done (already fixed earlier): {dest.name}.", str(dest)
    try:
        free = shutil.disk_usage(dest.parent).free
        if free < max(0, Path(rom).stat().st_size - 0x18300000):
            return False, f"Not enough free space next to the game for the fixed copy (needs up to {Path(rom).stat().st_size // 2**30 + 1} GB).", ""
        tool = tool or find_tool()
        if not tool:
            tool = install_tool(fetch, say)
        say("Making a working copy (this takes a few minutes)...")
        with tempfile.TemporaryDirectory(dir=dest.parent, prefix=".codeaque-xiso-") as td:
            before = os.stat(rom)
            inp = _linked_input(rom, Path(td) / "in")
            (Path(td) / "out").mkdir()
            res = runner([tool, "-r", "-d", str(Path(td) / "out"), str(inp)], capture_output=True, text=True, timeout=3 * 3600)
            out = Path(td) / "out" / Path(rom).name
            after = os.stat(rom)
            if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
                return False, "Stopped: the original file changed while converting - the copy was not used.", ""
            if res.returncode != 0 or not out.is_file() or iso_kind(str(out)) != "xiso":
                return False, "extract-xiso could not convert it: " + ((res.stderr or res.stdout or "").strip()[-200:] or "no output"), ""
            say("Checking the copy...")
            os.replace(out, dest)
    except RuntimeError as exc:
        return False, str(exc), ""
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"Could not make the copy: {exc}", ""
    return True, f"Done. Made {dest.name} next to the original (kept, unchanged). CodeAque now starts the fixed copy.", str(dest)
