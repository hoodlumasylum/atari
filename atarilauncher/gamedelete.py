"""Delete a game from inside CodeAque - safely.

Rules (all checked again right before anything is removed):
  * only things INSIDE a games folder are ever deleted: ~/Games/Atari, ~/Games/CodeAque, ~/Games/CodeAque and the folders saved in Settings for a system.
    Never the folder itself, never your home folder or a system folder, never anything a path or a symlink leads outside to;
  * a game is its file (plus the .bin tracks a .cue / .gdi lists), or - for an unpacked Xbox game or a PS3 game - its own folder;
  * saves are KEPT unless you say otherwise (and then only save files lying next to the game with the same name are removed:
    saves an emulator keeps in its own folders are never touched);
  * Steam games are never deleted by Code: it offers to open Steam's own uninstall window;
  * games from other launchers (Heroic, Lutris), apps and tools are not deletable here.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import covers, gamesroot, importer, paths, steam as steam_mod, windows
from .config import Config

SAVE_RE = re.compile(r"^(srm|sav|rtc|eep|fla|mpk|mcr|mcd|mc|sta|bsv|dsv|nvram|fs|sram|state\d*|ss\d|st\d|frz)$", re.I)
_SYSTEM_TOP = {"bin", "boot", "dev", "etc", "lib", "lib32", "lib64", "proc", "root", "run", "sbin", "sys", "usr", "var", "opt", "srv",
               "snap", "home", "media", "mnt", "tmp"}
KINDS = ("rom", "windows", "steam")


def _real(p: Path | str) -> Path:
    return Path(os.path.realpath(p))


def safe_root(p: Path, home: Path) -> bool:
    """A folder CodeAque may delete things inside: not '/', not a system folder, not your home folder or one above it, not another user's
    home, not the mount area itself (/media/<user>)."""
    r, h = _real(p), _real(home)
    if r == h or r in h.parents or len(r.parts) < 3 or r.parent == h.parent:
        return False
    top = r.parts[1]
    if top in _SYSTEM_TOP and top not in ("home", "media", "mnt", "run", "tmp"):
        return False
    if top in ("media", "mnt") and len(r.parts) < 4:
        return False
    if top == "run" and len(r.parts) < 5:
        return False
    return True


def allowed_roots(cfg: Config, home: Path | None = None) -> list[Path]:
    home = Path(home) if home is not None else Path.home()
    cands = [home / r for r in gamesroot.ROOTS]
    for sc in cfg.systems.values():
        cands += [Path(os.path.expanduser(r)) for r in sc.roms]
    out: list[Path] = []
    for c in cands:
        try:
            if c.is_dir() and safe_root(c, home) and _real(c) not in out:
                out.append(_real(c))
        except OSError:
            pass
    return out


def root_of(path: Path, roots: list[Path]) -> Path | None:
    """The games folder this path is strictly inside of (the folder it sits in is resolved, so a symlinked parent cannot lead out)."""
    try:
        target = _real(path.parent) / path.name
    except OSError:
        return None
    for r in roots:
        if r in target.parents:
            return r
    return None


def tree_size(path: Path) -> tuple[int, int]:
    """(bytes, number of files) of a file or a whole folder (symlinks are counted as the link, never followed)."""
    try:
        if path.is_symlink() or path.is_file():
            return (0 if path.is_symlink() else path.stat().st_size), 1
    except OSError:
        return 0, 0
    total = n = 0
    for dp, dn, fn in os.walk(path, followlinks=False):
        for f in fn:
            n += 1
            try:
                fp = os.path.join(dp, f)
                if not os.path.islink(fp):
                    total += os.path.getsize(fp)
            except OSError:
                pass
    return total, n


@dataclass
class Plan:
    kind: str = "none"                 # rom | windows | winref | steam | none
    title: str = ""
    system: str = ""
    deletable: bool = False            # files will be removed
    removable: bool = False            # the game can be removed from the library (winref: files stay)
    message: str = ""                  # why not, or what will happen (plain English)
    targets: list = field(default_factory=list)   # files / folders to delete
    folder: bool = False               # the game is a whole folder
    where: str = ""
    size: int = 0
    nfiles: int = 0
    saves: list = field(default_factory=list)
    saves_size: int = 0
    cover: Path | None = None
    cover_size: int = 0
    root: Path | None = None
    gid: str = ""
    appid: str = ""
    win_id: str = ""

    def size_text(self) -> str:
        n = f"{self.nfiles} file{'s' if self.nfiles != 1 else ''}"
        return f"{importer.human_size(self.size)} in {n}" if self.nfiles else importer.human_size(self.size)


def kind_of(game) -> str:
    gid = getattr(game, "gid", "") or ""
    if gid.startswith("steam:"):
        return "steam"
    if gid.startswith("win:"):
        return "windows"
    if gid.startswith("rom:") and getattr(game, "rom_path", ""):
        return "rom"
    return "none"


def _game_unit(game) -> tuple[Path, bool]:
    """(the file or folder that IS the game, is it a folder)."""
    p = Path(game.rom_path)
    if game.platform == "xbox" and p.name.lower() == "default.xbe":
        return p.parent, True
    if game.platform == "ps3" and p.name.upper() == "EBOOT.BIN":
        base = p.parent.parent if p.parent.name.upper() == "USRDIR" else p.parent
        if base.name.upper() == "PS3_GAME":
            base = base.parent
        return base, True
    return p, False


def _saves_next_to(unit: Path, skip: set) -> list[Path]:
    stem = unit.stem.lower()
    out = []
    try:
        for c in unit.parent.iterdir():
            if c in skip or c == unit or not c.is_file():
                continue
            name = c.name.lower()
            base, _, ext = name.rpartition(".")
            if base == stem and SAVE_RE.match(ext):
                out.append(c)
            elif name.startswith(stem + ".") and name.count(".") >= 2 and SAVE_RE.match(ext) and name[len(stem) + 1:].split(".")[0] in ("", "sav", "srm", "state"):
                out.append(c)
    except OSError:
        pass
    return sorted(out)


def plan_for(game, cfg: Config, home: Path | None = None, covers_root: Path | None = None) -> Plan:
    home = Path(home) if home is not None else Path.home()
    kind = kind_of(game)
    pl = Plan(title=game.title, system=game.platform_name, gid=game.gid)
    if kind == "steam":
        pl.kind, pl.appid = "steam", game.steam_appid
        pl.message = ("Steam manages this game's files, so CodeAque will not delete them. Press the button to open Steam's own "
                      "uninstall window for it.")
        return pl
    if kind == "none":
        pl.message = ("CodeAque can only delete games it found in your games folders (and Windows games you added). "
                      "Apps, tools and games installed by other launchers (Heroic, Lutris) are removed in their own program.")
        return pl
    roots = allowed_roots(cfg, home)
    if kind == "windows":
        return _plan_windows(game, pl, roots, home)
    unit, is_dir = _game_unit(game)
    pl.kind, pl.folder = "rom", is_dir
    pl.where = str(unit)
    if not (unit.exists() or unit.is_symlink()):
        pl.message = "That game file is already gone. Press Rescan to update the list."
        return pl
    root = root_of(unit, roots)
    if root is None:
        pl.message = (f"This game is in {unit.parent}, which is not one of your games folders (~/Games/Atari, ~/Games/CodeAque, ~/Games/CodeAque or a folder "
                      "set in Settings). CodeAque only deletes inside those, so nothing was changed.")
        return pl
    if is_dir and _is_system_folder(unit, cfg, roots, home):
        pl.message = (f"The game's files sit directly in your games folder ({unit}), so CodeAque will not delete the whole folder. "
                      "Delete the game's files one by one in My files.")
        return pl
    pl.root = root
    targets = [unit]
    if not is_dir:
        for c in importer._companions(unit):
            if root_of(c, roots) is not None:
                targets.append(c)
    pl.targets = targets
    for t in targets:
        b, n = tree_size(t)
        pl.size += b
        pl.nfiles += n
    if not is_dir:
        pl.saves = [s for s in _saves_next_to(unit, set(targets)) if root_of(s, roots) is not None]
        pl.saves_size = sum(tree_size(s)[0] for s in pl.saves)
    pl.cover = _own_cover(game, covers_root)
    pl.cover_size = tree_size(pl.cover)[0] if pl.cover else 0
    pl.deletable = pl.removable = True
    return pl


def _is_system_folder(unit: Path, cfg: Config, roots: list[Path], home: Path) -> bool:
    """A folder that holds a whole console's games (a games folder, a folder set in Settings, or ~/Games/Atari/xbox and the like)."""
    r = _real(unit)
    if r in roots:
        return True
    configured = {_real(os.path.expanduser(x)) for sc in cfg.systems.values() for x in sc.roms}
    if r in configured:
        return True
    table = importer._hint_table(cfg)
    return re.sub(r"[^a-z0-9]", "", unit.name.lower()) in table and _real(unit.parent) in roots


def _own_cover(game, covers_root: Path | None) -> Path | None:
    try:
        dest = covers.dest_for_game(game, covers_root)
    except Exception:
        return None
    return dest if dest is not None and dest.is_file() else None


def _plan_windows(game, pl: Plan, roots: list[Path], home: Path) -> Plan:
    pl.kind = "winref"
    pl.win_id = game.gid[4:]
    pl.removable = True
    exe = Path(game.rom_path)
    pl.where = str(exe)
    gdir = _real(windows.games_dir(home))
    folder = None
    try:
        rel = _real(exe.parent) / exe.name
        if gdir in rel.parents:
            folder = gdir / rel.relative_to(gdir).parts[0]
            if folder == rel:                      # a single .exe lying straight in the Windows games folder
                folder = None
    except (OSError, ValueError):
        folder = None
    if folder is not None and folder.is_dir() and not folder.is_symlink() and root_of(folder, roots) is not None:
        pl.kind, pl.folder, pl.deletable, pl.targets, pl.root = "windows", True, True, [folder], root_of(folder, roots)
        pl.where = str(folder)
        pl.size, pl.nfiles = tree_size(folder)
    else:
        pl.message = ("This Windows game's files are not in a folder CodeAque made inside your games folder, so CodeAque only removes it from "
                      "your library. The files stay where they are.")
    pl.cover = None
    return pl


@dataclass
class Result:
    ok: bool
    text: str
    freed: int = 0
    deleted: int = 0
    errors: list = field(default_factory=list)


def _remove(path: Path, roots: list[Path], cfg: Config, home: Path) -> tuple[int, int, str]:
    """(bytes, files, error). Re-checks that the path is inside a games folder, as late as possible."""
    if root_of(path, roots) is None:
        return 0, 0, f"{path.name}: outside your games folders - left alone"
    if path.is_dir() and not path.is_symlink() and _is_system_folder(path, cfg, roots, home):
        return 0, 0, f"{path.name}: is a games folder itself - left alone"
    try:
        if path.is_symlink() or path.is_file():
            b, n = tree_size(path)
            path.unlink()
            return b, n, ""
        if path.is_dir():
            b, n = tree_size(path)
            errs: list[str] = []
            shutil.rmtree(path, onerror=lambda f, p, e: errs.append(str(e[1])))
            if errs or path.exists():
                return b, n, f"{path.name}: {errs[0] if errs else 'could not be removed completely'}"
            return b, n, ""
        return 0, 0, ""
    except OSError as exc:
        return 0, 0, f"{path.name}: {exc.strerror or exc}"


def delete(plan: Plan, cfg: Config, with_saves: bool = False, with_cover: bool = False, home: Path | None = None,
           covers_root: Path | None = None) -> Result:
    """Do it. Never raises. The caller removes the game from favourites and rescans."""
    home = Path(home) if home is not None else Path.home()
    if not plan.removable:
        return Result(False, plan.message or "Nothing was deleted.")
    roots = allowed_roots(cfg, home)
    res = Result(True, "")
    todo = list(plan.targets) if plan.deletable else []
    if with_saves:
        todo += plan.saves
    for t in todo:
        b, n, err = _remove(t, roots, cfg, home)
        res.freed += b
        res.deleted += n
        if err:
            res.errors.append(err)
    if with_cover and plan.cover is not None:
        user = _real(covers_root or paths.user_covers_dir())
        try:
            if user in _real(plan.cover).parents or _real(plan.cover.parent) == user:
                plan.cover.unlink()
        except OSError as exc:
            res.errors.append(f"cover: {exc.strerror or exc}")
    if plan.kind in ("winref", "windows") and plan.win_id:
        windows.remove_game(plan.win_id)
    if res.errors:
        res.ok = False
        res.text = (f"Could not delete everything for {plan.title}: " + "; ".join(res.errors[:3])
                    + (f" (removed {res.deleted} file{'s' if res.deleted != 1 else ''}, {importer.human_size(res.freed)})." if res.deleted else "."))
    elif plan.kind == "winref" and not plan.deletable:
        res.text = f"{plan.title} was removed from your library. Its files were left where they are."
    else:
        extra = []
        if with_saves and plan.saves:
            extra.append(f"{len(plan.saves)} save file{'s' if len(plan.saves) != 1 else ''}")
        if with_cover and plan.cover is not None:
            extra.append("its cover picture")
        res.text = (f"Deleted {plan.title}: {importer.human_size(res.freed)} freed ({res.deleted} file{'s' if res.deleted != 1 else ''})."
                    + (" Also deleted " + " and ".join(extra) + "." if extra else "")
                    + (" Saves were kept." if plan.saves and not with_saves else ""))
    return res


def open_steam_uninstall(cfg: Config, appid: str, home: Path | None = None, popen: Callable | None = None,
                         running: Callable[[], bool] | None = None, sleep: Callable[[float], None] = time.sleep,
                         big_picture: bool = False, wait: float = 40.0) -> tuple[bool, str]:
    """Open Steam's own uninstall window for this game (steam://uninstall/<id>). Starts Steam first when it is not running.
    CodeAque deletes nothing itself."""
    from . import launcher
    if not str(appid).isdigit():
        return False, "That Steam game has no number CodeAque can hand to Steam."
    popen = popen or subprocess.Popen
    running = running or steam_mod.steam_running
    base = launcher.steam_base_command(cfg, home)
    env = launcher.clean_env()

    def spawn(extra: list[str]) -> None:
        popen(base + extra, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
              start_new_session=True)
    try:
        if not running():
            spawn(["-gamepadui"] if big_picture else [])
            end = time.monotonic() + wait
            while time.monotonic() < end and not running():
                sleep(1.0)
            sleep(4.0)                                 # Steam's window exists a moment before it listens for steam:// links
        spawn([f"steam://uninstall/{appid}"])
    except (OSError, ValueError) as exc:
        return False, f"Could not start Steam: {getattr(exc, 'strerror', None) or exc}. Install Steam first (Settings > Steam)."
    return True, "Steam is opening its uninstall window for this game. Confirm there; come back to CodeAque afterwards and press Rescan."
