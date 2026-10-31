"""Original Xbox helpers: xemu only starts a disc image (.iso / .xiso), not an unpacked game folder
(the one with default.xbe). For such a folder we build an .xiso image once (with `extract-xiso`) and start that."""
from __future__ import annotations

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


def rewrite_redump(rom: str, runner=subprocess.run, cache_dir: Path | None = None) -> str:
    """A full Redump .iso -> an XISO in CodeAque's cache (extract-xiso -r -d <dir>); the original is never touched."""
    out_dir = cache_dir or paths.data_dir() / "xiso"
    target = out_dir / Path(rom).name
    if target.is_file() and iso_kind(str(target)) == "xiso":
        return str(target)
    tool = find_extract_xiso()
    if not tool:
        raise RuntimeError(NOT_XISO)
    out_dir.mkdir(parents=True, exist_ok=True)
    res = runner([tool, "-r", "-d", str(out_dir), rom], capture_output=True, text=True, timeout=3600)
    if res.returncode != 0 or not target.is_file() or iso_kind(str(target)) != "xiso":
        raise RuntimeError("Could not turn this disc dump into an XISO. " + ((res.stderr or res.stdout or "").strip()[:200]))
    return str(target)
