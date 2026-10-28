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


def disc_image_for(rom: str, runner=subprocess.run, cache_dir: Path | None = None) -> str:
    """Path of a disc image xemu can start for this game. Returns `rom` unchanged for normal .iso games.
    Raises RuntimeError with a plain-English message when the folder cannot be converted."""
    if not is_xbe_folder_game(rom):
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
