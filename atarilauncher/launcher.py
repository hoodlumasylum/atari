"""Build and run launch commands, and measure play time."""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable

from . import apps, controls, emulators, exitwatch, freegames, paths, webapps, windows
from .config import Config, SystemConfig
from .library import Game


class LaunchError(Exception):
    """Raised with a friendly, human-readable message."""


# ---------- helpers -------------------------------------------------------

_STRIP_ENV = ("QT_QPA_PLATFORM", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QML_IMPORT_PATH",
              "QML2_IMPORT_PATH", "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "QT_QUICK_BACKEND")


def _has_fuse2() -> bool:
    import ctypes.util
    return bool(ctypes.util.find_library("fuse"))


def clean_env() -> dict[str, str]:
    """Environment for child programs, without our Python/Qt settings leaking in."""
    env = {k: v for k, v in os.environ.items() if k not in _STRIP_ENV}
    if not _has_fuse2():            # AppImages (DuckStation) need FUSE 2; without it they unpack themselves and run from there
        env.setdefault("APPIMAGE_EXTRACT_AND_RUN", "1")
    venv = os.environ.get("VIRTUAL_ENV")
    if venv:
        env["PATH"] = os.pathsep.join(p for p in env.get("PATH", "").split(os.pathsep)
                                      if not p.startswith(venv))
    return env


def resolve_retroarch(cfg: Config, home: Path | None = None) -> list[str]:
    return emulators.find_emu(cfg, "retroarch", home)[0]


def build_rom_command(cfg: Config, system: SystemConfig, rom: str, home: Path | None = None) -> list[str]:
    """The command that starts one game: your own command if you wrote one, else the chosen/detected emulator."""
    template = system.command.strip()
    if template:  # custom command (also used for consoles that are not in the built-in table)
        try:
            return emulators.expand(template, cfg, system, rom, [], system.core, home)
        except ValueError as exc:
            raise LaunchError(f"The launch command for {system.name} is not valid: {exc}")
    choice = emulators.choose(cfg, system, home)
    if choice is None:
        raise LaunchError(f"No launch command is set for {system.name}. Edit {paths.config_file()}.")
    cmd = emulators.expand(choice.emu.template, cfg, system, rom, choice.cmd, choice.core, home)
    if choice.how == "flatpak":  # sandboxed emulators only see folders they were given
        cmd = emulators.grant_rom_access(cmd, rom)
    return cmd


flatpak_installed = emulators.flatpak_installed
cores_dirs = emulators.cores_dirs
resolve_core_path = emulators.resolve_core_path


def controls_hint(cfg: Config, game: Game) -> str:
    """One line of keyboard keys for the emulator that would run this game ('' for Steam / unknown)."""
    if game.platform == "steam":
        return ""
    if game.platform == webapps.STREAMING:            # Netflix, YouTube, ... and Kodi: how to get back to Atari
        return exit_hint(cfg)
    system = cfg.systems.get(game.platform)
    if system is None or system.command.strip():
        return ""
    choice = emulators.choose(cfg, system)
    return controls.hint_for(choice.emu.id, system.id) if choice else ""


def exit_hint(cfg: Config | None = None) -> str:
    """The line shown when a web app / Kodi starts ('' when Esc-to-return is switched off)."""
    if not exitwatch.enabled(cfg):
        return ""
    return exitwatch.HINT + ".  " + exitwatch.HINT_PAD


def _hint_delay() -> float:
    """Seconds the 'NOW PLAYING ... press Esc twice' screen is shown before the browser covers it."""
    try:
        return max(0.0, float(os.environ.get("ATARI_HINT_DELAY", "1.5")))
    except ValueError:
        return 1.5


def _flatpak_id(cmd: list[str]) -> str:
    if len(cmd) >= 3 and cmd[0] == "flatpak" and cmd[1] == "run":
        return next((a for a in cmd[2:] if not a.startswith("-")), "")
    return ""


def _start_watch(cfg: Config, proc, cmd: list[str]):
    """Start the Esc-twice watcher for a running web app; None when switched off."""
    if not exitwatch.enabled(cfg):
        return None
    w = exitwatch.Watch(proc, _flatpak_id(cmd))
    _log("esc-to-return: " + ("keyboard watcher on (X11)" if w.keyboard_ok else
                              f"keyboard watcher unavailable ({w.keys.why}); gamepad Guide+B only"))
    w.start()
    exitwatch.notify(exitwatch.HINT_SHORT)
    return w


def _finish_watched(w, name: str, code: int, started: float) -> tuple[float, str] | None:
    """If the user closed the app with Esc-twice / Guide+B, that is a normal end, not an error."""
    if w is not None and w.triggered:
        _log(f"esc-to-return: closed {name} ({w.reason})")
        return time.time() - started, ""
    return None


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
    if game.platform == windows.PLATFORM:
        return _run_windows(cfg, game, on_started)
    if game.gid.startswith("free:"):
        return _run_free(cfg, game, on_started)
    if game.gid.startswith("web:"):
        return _run_web(cfg, game, on_started)
    if game.platform in apps.NON_GAME or game.launch:
        return _run_app(cfg, game, on_started)
    system = cfg.systems.get(game.platform)
    if system is None:
        raise LaunchError(f"Unknown system '{game.platform}'.")
    if not Path(game.rom_path).is_file():
        raise LaunchError("That game file is missing. Is the drive plugged in? Try Rescan.")
    is_pkg = system.id == "ps3" and game.rom_path.lower().endswith(".pkg")
    if is_pkg:  # a .pkg is an installer: RPCS3 only installs packages with its window open
        cmd = emulators.find_emu(cfg, "rpcs3")[0] + ["--installpkg", game.rom_path]
    else:
        cmd = build_rom_command(cfg, system, game.rom_path)
    if not system.command.strip() and cmd and not shutil.which(cmd[0]):
        ready, _label, hint = emulators.status_line(cfg, system)
        if not ready:
            raise LaunchError(f"{system.name} needs an emulator that is not installed yet. {hint}")
    _check_executable(cmd, system.name)
    if not is_pkg and not system.command.strip():
        choice = emulators.choose(cfg, system)
        if choice is not None:  # make sure the keyboard works the first time (only when the emulator has no keys yet)
            for made in controls.ensure_keyboard_defaults(choice.emu.id, choice.how):
                _log("keyboard defaults written: " + made)
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
    if is_pkg:
        return 0.0, ("Package installer closed. Installed PS3 games live inside RPCS3 - to list a game here, "
                     "put its game folder (with PS3_GAME) or .iso in your PS3 folder.")
    if code != 0 and elapsed < 5:
        return 0.0, (f"The emulator closed right away (code {code}). Check the emulator and core are "
                     f"installed; details are in {paths.log_file()}")
    return elapsed, ""


def _run_app(cfg: Config, game: Game, on_started):
    """A PC app (Roblox, Heroic, Lutris, ...) or a game imported from Heroic / Lutris. Blocks until it closes."""
    if game.launch:                       # imported game: ask its launcher to start it
        store = game.platform if game.platform in apps.BY_ID else ""
        app = apps.BY_ID.get(store)
        cmd, how = apps.store_command(cfg, game.launch, store) if app else ([], "")
    else:
        app = next((a for a in apps.APP_DEFS if a.gid == game.gid), None)
        if app is None:
            raise LaunchError(f"Unknown app '{game.title}'.")
        cmd, how = apps.app_command(cfg, app)
    if app is None or not how:
        raise LaunchError(apps.install_hint(app) if app else "That app is not available.")
    _check_executable(cmd, app.title)
    _log("launch: " + shlex.join(cmd))
    if app.id == "steam" and not game.launch:      # Steam stays open on its own: start it and come straight back
        try:
            subprocess.Popen(cmd, env=clean_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             stdin=subprocess.DEVNULL, start_new_session=True)
        except OSError as exc:
            raise LaunchError(f"Could not start Steam: {exc}")
        on_started()
        return 0.0, INFO + ("Steam is starting - sign in there. After Steam has installed a game, choose "
                            "Settings > Steam > Rescan Steam so it shows up here.")
    try:
        paths.data_dir().mkdir(parents=True, exist_ok=True)
        logfh = open(paths.log_file(), "ab")
    except OSError:
        logfh = subprocess.DEVNULL
    watched = game.platform == webapps.STREAMING and exitwatch.enabled(cfg)    # Kodi: Esc twice / hold Esc returns to Atari
    if watched:
        time.sleep(_hint_delay())
    started = time.time()
    try:
        proc = subprocess.Popen(cmd, env=clean_env(), stdout=logfh, stderr=logfh, stdin=subprocess.DEVNULL,
                                start_new_session=watched)
    except OSError as exc:
        raise LaunchError(f"Could not start {app.title}: {exc}")
    watch = _start_watch(cfg, proc, cmd) if watched else None
    on_started()
    try:
        code = proc.wait()
    finally:
        if watch is not None:
            watch.stop()
    done = _finish_watched(watch, app.title, code, started)
    if done:
        return done
    elapsed = time.time() - started
    if code != 0 and elapsed < 5:
        extra = (" Sober is unofficial and can break after a Roblox update: reinstall it with Settings > Emulators "
                 "> Install emulators and apps." if app.id == "roblox" else "")
        return 0.0, (f"{app.title} closed right away (code {code}).{extra} Details: {paths.log_file()}")
    return elapsed, ""


INFO = "\u2139 "     # a message that is advice, not an error (no error sound, no "Fix my game" hint)


def _run_free(cfg: Config, game: Game, on_started):
    """A game from the Free Games list: through Steam, through a Flatpak, or just an honest explanation."""
    fg = freegames.BY_ID.get(game.gid.split(":", 1)[-1])
    if fg is None:
        raise LaunchError(f"Unknown game '{game.title}'.")
    if fg.kind == "info":
        raise LaunchError(INFO + fg.why)
    if fg.kind == "steam":
        installed = False
        try:
            from . import steam as steam_mod
            scan = steam_mod.scan_steam(None, cfg.steam_root, cfg.steam_extra_libraries)
            installed = any(g.appid == fg.ref for g in scan.games)
        except Exception:
            pass
        cmd = steam_base_command(cfg) + [freegames.steam_command_for(fg, installed)]
        _check_executable(cmd, "Steam")
        _log("launch (free, steam): " + shlex.join(cmd))
        try:
            subprocess.Popen(cmd, env=clean_env(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError as exc:
            raise LaunchError(f"Could not start Steam: {exc}")
        on_started()
        if installed:
            return _wait_for_steam_game(fg.ref, game.title)
        raise LaunchError(INFO + f"Steam is opening the free install page for {fg.title}. Press Install there; "
                          "when it is done, come back and press Play again.")
    # Flatpak
    if emulators.flatpak_installed(fg.ref):
        cmd = ["flatpak", "run", fg.ref]
        _check_executable(cmd, "Flatpak")
        _log("launch (free, flatpak): " + shlex.join(cmd))
        started = time.time()
        try:
            proc = subprocess.Popen(cmd, env=clean_env(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
        except OSError as exc:
            raise LaunchError(f"Could not start {fg.title}: {exc}")
        on_started()
        code = proc.wait()
        elapsed = time.time() - started
        if code != 0 and elapsed < 5:
            return 0.0, f"{fg.title} closed right away (code {code})."
        return elapsed, ""
    from . import installer
    script = f"flatpak install --user -y flathub {fg.ref}; echo; read -r -p 'Done. Press Enter to close this window.' _"
    ok, msg = installer.open_in_terminal(["bash", "-c", script])
    raise LaunchError(INFO + (f"Installing {fg.title} (free) in a new window. When it finishes, press Play again." if ok else msg))


def _wait_for_steam_game(appid: str, title: str):
    """Steam starts the game itself: wait until its process shows up, then until it ends (as for any Steam game)."""
    t0 = time.time()
    while time.time() - t0 < 90 and not find_steam_pids(appid):
        time.sleep(2.0)
    started = time.time()
    while find_steam_pids(appid):
        time.sleep(2.0)
    return (time.time() - started if time.time() - started > 5 else 0.0), ""


def _run_web(cfg: Config, game: Game, on_started):
    """A web app (YouTube, Netflix, ...) in a full-screen browser window with its own profile. Blocks until it closes."""
    wa = webapps.BY_ID.get(game.gid.split(":", 1)[-1])
    if wa is None:
        raise LaunchError(f"Unknown web app '{game.title}'.")
    cmd, name = webapps.build_command(cfg, wa)
    if not cmd:
        raise LaunchError(webapps.HELP_TEXT)
    try:
        (webapps.profile_root() / wa.id).mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    _check_executable(cmd, name)
    _log(f"launch (web, {name}): " + shlex.join(cmd))
    try:
        paths.data_dir().mkdir(parents=True, exist_ok=True)
        logfh = open(paths.log_file(), "ab")
    except OSError:
        logfh = subprocess.DEVNULL
    if exitwatch.enabled(cfg):
        time.sleep(_hint_delay())       # let the "Press Esc twice to return to Atari" screen be read before the browser covers it
    started = time.time()
    try:
        proc = subprocess.Popen(cmd, env=clean_env(), stdout=logfh, stderr=logfh, stdin=subprocess.DEVNULL,
                                start_new_session=True)
    except OSError as exc:
        raise LaunchError(f"Could not start {name}: {exc}")
    watch = _start_watch(cfg, proc, cmd)
    on_started()
    try:
        code = proc.wait()
    finally:
        if watch is not None:
            watch.stop()
    done = _finish_watched(watch, name, code, started)
    if done:
        return done
    elapsed = time.time() - started
    if code != 0 and elapsed < 5:
        return 0.0, f"{name} closed right away (code {code}). Details: {paths.log_file()}"
    return elapsed, ""


def _run_windows(cfg: Config, game: Game, on_started):
    """A Windows game through umu / Proton / Wine, in its own prefix. Blocks until it closes."""
    wg = windows.WinGame(game.gid.split(":", 1)[-1], game.title, game.rom_path, game.cover)
    try:
        cmd, extra, cwd, label = windows.build_launch(cfg, wg)
    except windows.WinError as exc:
        raise LaunchError(str(exc))
    env = clean_env()
    env.update(extra)
    _log(f"launch (windows, {label}): " + shlex.join(cmd))
    try:
        paths.data_dir().mkdir(parents=True, exist_ok=True)
        logfh = open(paths.log_file(), "ab")
    except OSError:
        logfh = subprocess.DEVNULL
    started = time.time()
    try:
        proc = subprocess.Popen(cmd, env=env, stdout=logfh, stderr=logfh, stdin=subprocess.DEVNULL, cwd=str(cwd))
    except OSError as exc:
        raise LaunchError(f"Could not start the Windows helper ({label}): {exc}")
    on_started()
    code = proc.wait()
    elapsed = time.time() - started
    if code != 0 and elapsed < 8:
        return 0.0, (f"The game closed right away (code {code}). The first start with {label} can take a few minutes "
                     f"(it sets up the game's own Windows folder) - try again. Options > Fix my game can check the "
                     f"rest. Details: {paths.log_file()}")
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
