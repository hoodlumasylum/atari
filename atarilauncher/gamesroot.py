"""The default games folder (~/Games/Atari, also ~/Games/Code).

Code used to scan only the folders saved in Settings. A game dropped by hand into ~/Games/Atari/xbox was therefore
never shown (the folder was only remembered after Code itself had copied a game there). Now:
  * ~/Games/Atari/<system> is always scanned, when <system> is an id, a name or an alias Code knows
    ("xbox", "Xbox Classic", "xbox-classic", "xiso", "PS2", "playstation2" ...; upper/lower case does not matter);
  * a folder that matches no system is reported with a hint (and the system it most probably is), and so is a game
    file lying loose in ~/Games/Atari.
Nothing here writes anything except `fix()`, which only renames/moves inside the games folder and never overwrites."""
from __future__ import annotations

import difflib
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import importer
from .config import Config

ROOTS = ("Games/Atari", "Games/Code")
# files that are not games: art, notes, saves, Windows leftovers
_NOT_GAMES = {"txt", "nfo", "md", "jpg", "jpeg", "png", "gif", "bmp", "webp", "pdf", "url", "ini", "db", "log",
              "sav", "srm", "state", "cfg", "xml", "json", "html", "htm", "part", "crdownload", "tmp", "sfv", "md5",
              "sha1", "sha256", "dat", "diz", "lnk", "desktop"}
MAX_LOOK = 400  # files looked at per unknown folder


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def roots(home: Path | None = None) -> list[Path]:
    """The games folders that exist (a symlink to another one is only listed once)."""
    base = Path(home) if home is not None else Path.home()
    out, seen = [], set()
    for r in ROOTS:
        p = base / r
        try:
            if p.is_dir() and os.path.realpath(p) not in seen:
                seen.add(os.path.realpath(p))
                out.append(p)
        except OSError:
            pass
    return out


def _children(root: Path) -> list[Path]:
    try:
        return sorted((p for p in root.iterdir() if not p.name.startswith(".")), key=lambda p: p.name.lower())
    except OSError:
        return []


def auto_folders(cfg: Config, system_id: str, home: Path | None = None) -> list[str]:
    """Existing ~/Games/Atari/<name> folders that belong to this system."""
    table = importer._hint_table(cfg)
    out: list[str] = []
    for root in roots(home):
        for child in _children(root):
            try:
                if child.is_dir() and table.get(_norm(child.name)) == system_id:
                    out.append(str(child))
            except OSError:
                pass
    return out


@dataclass
class Unknown:
    path: str
    is_file: bool
    files: int          # game-like files inside (1 for a loose file)
    guess: str = ""     # system id it probably is ("" = no idea)
    why: str = ""       # how we know

    @property
    def name(self) -> str:
        return Path(self.path).name


def _is_game_name(name: str) -> bool:
    if name.startswith(".") or "." not in name:
        return False
    return name.rsplit(".", 1)[-1].lower() not in _NOT_GAMES


def _guess_from_files(cfg: Config, files: list[Path]) -> tuple[str, str]:
    """Look at the file types (and inside disc images) to tell which system a folder is for."""
    ext_table = importer._extension_table(cfg)
    votes: dict[str, int] = {}
    for f in files:
        low = f.name.lower()
        if low == "default.xbe":
            votes["xbox"] = votes.get("xbox", 0) + 5
            continue
        ext = low.rsplit(".", 1)[-1] if "." in low else ""
        if ext in ("iso", "bin", "img"):
            try:
                sid = importer.sniff_disc(f)
            except OSError:
                sid = ""
            if sid and sid in cfg.systems:
                votes[sid] = votes.get(sid, 0) + 3
                continue
        owners = ext_table.get(ext, [])
        if len(owners) == 1:
            votes[owners[0]] = votes.get(owners[0], 0) + 1
    if not votes:
        return "", ""
    best = max(votes, key=votes.get)
    return best, "from the kind of files inside"


def unknown_items(cfg: Config, home: Path | None = None) -> list[Unknown]:
    """Folders (and loose game files) in ~/Games/Atari that no system claims."""
    table = importer._hint_table(cfg)
    out: list[Unknown] = []
    for root in roots(home):
        for child in _children(root):
            try:
                if child.is_file():
                    if _is_game_name(child.name):
                        g, why = _guess_from_files(cfg, [child])
                        out.append(Unknown(str(child), True, 1, g, why))
                    continue
                if not child.is_dir() or table.get(_norm(child.name)):
                    continue
                games: list[Path] = []
                seen = 0
                for dp, dn, fn in os.walk(child, followlinks=False):
                    for n in fn:
                        seen += 1
                        if n.lower() == "default.xbe" or _is_game_name(n):
                            games.append(Path(dp) / n)
                    if seen > MAX_LOOK:
                        break
                if not games:
                    continue
                guess, why = "", ""
                close = difflib.get_close_matches(_norm(child.name), list(table), n=1, cutoff=0.72)
                if close:
                    guess, why = table[close[0]], "from the folder name"
                else:
                    for k, sid in table.items():  # "Xbox games", "My PS2 discs": a system word inside the name
                        if len(k) >= 3 and k in _norm(child.name) and k not in ("atari", "sega", "ps"):
                            guess, why = sid, "from the folder name"
                            break
                if not guess:
                    guess, why = _guess_from_files(cfg, games)
                out.append(Unknown(str(child), False, len(games), guess, why))
            except OSError:
                continue
    return out


def hint_text(cfg: Config, u: Unknown) -> str:
    where = "the file" if u.is_file else f"the folder ({u.files} game file{'s' if u.files != 1 else ''})"
    if u.guess and u.guess in cfg.systems:
        sc = cfg.systems[u.guess]
        return (f"Code does not know {where} \"{u.name}\" in Games/Atari, so those games are not shown. "
                f"It looks like {sc.name} ({u.why}): "
                + (f"move it into a folder called \"{u.guess}\"." if u.is_file else f"rename it to \"{u.guess}\"."))
    return (f"Code does not know {where} \"{u.name}\" in Games/Atari, so those games are not shown. "
            "Put games in a folder named after the system, for example xbox, ps2, snes, n64, gamecube.")


def fix(cfg: Config, path: str, home: Path | None = None) -> tuple[bool, str]:
    """Rename the folder (or move the loose file into a new folder) to the system we guessed. Never overwrites."""
    items = {u.path: u for u in unknown_items(cfg, home)}
    u = items.get(path)
    if u is None:
        return False, "That item is not there any more. Press Rescan."
    if not u.guess or u.guess not in cfg.systems:
        return False, "Code could not tell which system this is: rename the folder yourself in My files."
    src = Path(u.path)
    root = src.parent
    dst_dir = root / u.guess
    try:
        if u.is_file:
            if (dst_dir / src.name).exists():
                return False, f"\"{u.guess}/{src.name}\" already exists, so nothing was moved."
            dst_dir.mkdir(exist_ok=True)
            shutil.move(str(src), str(dst_dir / src.name))
            return True, f"Moved {src.name} into {u.guess}."
        if dst_dir.exists():
            return False, (f"A folder called \"{u.guess}\" already exists. Open My files and move the games from "
                           f"\"{src.name}\" into it.")
        src.rename(dst_dir)
        return True, f"Renamed \"{src.name}\" to \"{u.guess}\"."
    except OSError as exc:
        return False, f"Could not do that: {exc.strerror or exc}"
