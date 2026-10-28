"""Build and run launch commands, and measure play time."""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable

from . import paths
from .config import Config, SystemConfig
from .library import Game


class LaunchError(Exception):
    """Raised with a friendly, human-readable message."""


# ---------- helpers -------------------------------------------------------

_STRIP_ENV = ("QT_QPA_PLATFORM", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QML_IMPORT_PATH",
              "QML2_IMPORT_PATH", "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "QT_QUICK_BACKEND")


def clean_env() -> dict[str, str]:
    """Environment for child programs, without our Python/Qt settings leaking in."""
    env = {k: v for k, v in os.environ.items() if k not in _STRIP_ENV}
    venv = os.environ.get("VIRTUAL_ENV")
    if venv:
        env["PATH"] = os.pathsep.join(p for p in env.get("PATH", "").split(os.pathsep)
                                      if not p.startswith(venv))
    return env


def flatpak_installed(app_id: str, home: Path | None = None) -> bool:
    home = home or Path.home()
    return any(p.exists() for p in (home / ".var" / "app" / app_id,
                                    Path("/var/lib/flatpak/app") / app_id,
                                    home / ".local/share/flatpak/app" / app_id))


def resolve_retroarch(cfg: Config, home: Path | None = None) -> list[str]:
    if cfg.retroarch_command.strip():
        return shlex.split(cfg.retroarch_command)
    if shutil.which("retroarch"):
        return ["retroarch"]
    if shutil.which("flatpak") and flatpak_installed("org.libretro.RetroArch", home):
        return ["flatpak", "run", "org.libretro.RetroArch"]
    return ["retroarch"]


def cores_dirs(cfg: Config, home: Path | None = None) -> list[Path]:
    home = home or Path.home()
    if cfg.cores_dir.strip():
        return [Path(cfg.cores_dir).expanduser()]
    return [home / ".config/retroarch/cores",
            home / ".var/app/org.libretro.RetroArch/config/retroarch/cores",
            home / "snap/retroarch/current/.config/retroarch/cores",
            Path("/usr/lib/x86_64-linux-gnu/libretro"), Path("/usr/lib64/libretro"),
            Path("/usr/lib/libretro"), Path("/usr/local/lib/libretro")]


def resolve_core_path(cfg: Config, core: str, home: Path | None = None) -> str:
    if not core:
        return ""
    name = core if core.endswith(".so") else core + ".so"
    dirs = cores_dirs(cfg, home)
    for d in dirs:
        if (d / name).is_file():
            return str(d / name)
    return str(dirs[0] / name)  # best guess; RetroArch will explain if missing


def build_rom_command(cfg: Config, system: SystemConfig, rom: str, home: Path | None = None) -> list[str]:
    template = system.command.strip()
    if not template:
        raise LaunchError(f"No launch command is set for {system.name}. Edit {paths.config_file()}.")
    try:
        tokens = shlex.split(template)
    except ValueError as exc:
        raise LaunchError(f"The launch command for {system.name} is not valid: {exc}")
    repl = {
        "{rom}": rom,
        "{rom_dir}": str(Path(rom).parent),
        "{rom_name}": Path(rom).stem,
        "{core}": system.core,
        "{core_path}": resolve_core_path(cfg, system.core, home),
        "{cores_dir}": str(cores_dirs(cfg, home)[0]),
    }
    out: list[str] = []
    for tok in tokens:
        if tok == "{retroarch}":
            out += resolve_retroarch(cfg, home)
            continue
        for k, v in repl.items():
            tok = tok.replace(k, v)
        out.append(tok)
    return out


def steam_base_command(cfg: Config, home: Path | None = None) -> list[str]:
    if cfg.steam_command.strip():
        return shlex.split(cfg.steam_command)
    if shutil.which("steam"):
        return ["steam"]
    if shutil.which("flatpak") and flatpak_installed("com.valvesoftware.Steam", home):
        return ["flatpak", "run", "com.valvesoftware.Steam"]
    return ["steam"]


def build_steam_command(cfg: Config, appid: str, home: Path | None = None) -> list[str]:
    return steam_base_command(cfg, home) + [f"steam://rungameid/{appid}"]


def find_steam_pids(appid: str, proc_root: str = "/proc") -> list[int]:
    """PIDs of processes Steam started for this game (its 'reaper' wrapper carries AppId=<id>)."""
    needle = f"AppId={appid}".encode()
    env_needle = f"SteamAppId={appid}".encode()
    pids = []
    try:
        entries = os.listdir(proc_root)
    except OSError:
        return pids
    for e in entries:
        if not e.isdigit():
            continue
        try:
            with open(f"{proc_root}/{e}/cmdline", "rb") as fh:
                parts = fh.read().split(b"\0")
            if needle in parts or env_needle in parts:
                pids.append(int(e))
        except OSError:
            continue
    return pids


def _check_executable(cmd: list[str], what: str) -> None:
    if not cmd or not shutil.which(cmd[0]):
        raise LaunchError(
            f"Could not find the program '{cmd[0] if cmd else ''}' needed for {what}. "
            f"Install it, or change the command in {paths.config_file()}.")


# ---------- running -------------------------------------------------------

def _log(msg: str) -> None:
    try:
        paths.data_dir().mkdir(parents=True, exist_ok=True)
        with open(paths.log_file(), "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except OSError:
        pass


def run_game(cfg: Config, game: Game, on_started: Callable[[], None],
             poll: float = 2.0, steam_start_timeout: float = 240.0) -> tuple[float, str]:
    """Launch and block until the game ends. Returns (seconds_played, error_message).

    Meant to run in a background thread. Raises LaunchError if it can't even start.
    """
    if game.platform == "steam":
        return _run_steam(cfg, game, on_started, poll, steam_start_timeout)
    system = cfg.systems.get(game.platform)
    if system is None:
        raise LaunchError(f"Unknown system '{game.platform}'.")
    if not Path(game.rom_path).is_file():
        raise LaunchError("That game file is missing. Is the drive plugged in? Try Rescan.")
    cmd = build_rom_command(cfg, system, game.rom_path)
    _check_executable(cmd, system.name)
    _log("launch: " + shlex.join(cmd))
    try:
        paths.data_dir().mkdir(parents=True, exist_ok=True)
        logfh = open(paths.log_file(), "ab")
    except OSError:
        logfh = subprocess.DEVNULL
    started = time.time()
    try:
        proc = subprocess.Popen(cmd, env=clean_env(), stdout=logfh, stderr=logfh,
                                stdin=subprocess.DEVNULL, cwd=str(Path(game.rom_path).parent))
    except OSError as exc:
        raise LaunchError(f"Could not start the emulator: {exc}")
    on_started()
    code = proc.wait()
    elapsed = time.time() - started
    if code != 0 and elapsed < 5:
        return 0.0, (f"The emulator closed right away (code {code}). Check the emulator and core are "
                     f"installed; details are in {paths.log_file()}")
    return elapsed, ""


def _run_steam(cfg: Config, game: Game, on_started, poll: float, start_timeout: float, grace: float = 6.0):
    cmd = build_steam_command(cfg, game.steam_appid)
    _check_executable(cmd, "Steam")
    _log("launch: " + shlex.join(cmd))
    try:
        subprocess.Popen(cmd, env=clean_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        raise LaunchError(f"Could not start Steam: {exc}")
    on_started()
    deadline = time.time() + start_timeout
    first_seen = 0.0
    while time.time() < deadline:
        if find_steam_pids(game.steam_appid):
            first_seen = time.time()
            break
        time.sleep(poll)
    if not first_seen:
        return 0.0, "Steam did not seem to start the game (play time not recorded)."
    gone_since = 0.0
    while True:
        time.sleep(poll)
        if find_steam_pids(game.steam_appid):
            gone_since = 0.0
        else:
            gone_since = gone_since or time.time()
            if time.time() - gone_since >= grace:  # grace period: launchers/relaunches
                return gone_since - first_seen, ""
