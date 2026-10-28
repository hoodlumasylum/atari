"""Build and run launch commands, and measure play time."""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable

from . import apps, controls, emulators, exitwatch, freegames, paths, sober, webapps, windows, xbox
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
    if game.gid == "app:steam" and big_picture_wanted(cfg):
        return exit_hint(cfg)
    if game.platform == webapps.STREAMING or game.gid.startswith("web:"):            # Netflix, YouTube, ... and Kodi: how to get back to CodeAque
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
             poll: float = 2.0, steam_start_timeout: float = 240.0, status=None, cancel=None) -> tuple[float, str]:
    """Launch and block until the game ends. Returns (seconds_played, error_message).

    Meant to run in a background thread. Raises LaunchError if it can't even start.
    """
    if game.platform == "steam":
        return _run_steam(cfg, game, on_started, poll, steam_start_timeout, status=status, cancel=cancel)
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
        rom = game.rom_path
        if system.id == "xbox":  # xemu starts disc images only: an unpacked game folder becomes one first
            try:
                rom = xbox.disc_image_for(rom)
            except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
                raise LaunchError(str(exc))
        cmd = build_rom_command(cfg, system, rom)
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
                                stdin=subprocess.DEVNULL, cwd=str(Path(game.rom_path).parent),
                                start_new_session=True)       # its own session: nothing it does to its process group can reach CodeAque
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
    if app.id == "steam" and not game.launch and big_picture_wanted(cfg):
        return _run_steam_bigpicture(cfg, game, cmd, on_started)
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
    if app.background and not game.launch:
        return _run_background(cfg, cmd, app.title, on_started, logfh)
    watched = game.platform == webapps.STREAMING and exitwatch.enabled(cfg)    # Kodi: Esc twice / hold Esc returns to CodeAque
    if watched:
        time.sleep(_hint_delay())
    started = time.time()
    try:
        proc = subprocess.Popen(cmd, env=clean_env(), stdout=logfh, stderr=logfh, stdin=subprocess.DEVNULL,
                                start_new_session=True)
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
    if app.id == "roblox" and not game.launch:
        fixed = _roblox_recover(cmd, started, logfh)
        if fixed is not None:
            return fixed
    elapsed = time.time() - started
    if code != 0 and elapsed < 5:
        extra = (" Sober is unofficial and can break after a Roblox update: reinstall it with Settings > Emulators "
                 "> Install emulators and apps." if app.id == "roblox" else "")
        return 0.0, (f"{app.title} closed right away (code {code}).{extra} Details: {paths.log_file()}")
    return elapsed, ""


def _roblox_recover(cmd, started: float, logfh):
    """Sober showed its "Install Roblox - application bundle (APK) required" screen (its own download failed). Follow Sober's
    advice: if the connection to its servers works, update Sober and start it once more (it retries the download itself);
    if not - or if it fails again - say plainly what is wrong. Never downloads a Roblox APK. Returns None when this
    start was normal, else (seconds, message)."""
    if sober.permission_state(started):
        _log("roblox: Sober asked for the permission update")
        return 0.0, INFO + ("Sober shows \"Permission Update Required\". That is normal after a Sober update: it needs the permission update below. "
                            "The next screen shows the exact command in plain English; press Run fix and CodeAque applies it (your user only, "
                            "Sober only) and starts Roblox again. " + sober.OVERRIDE_COMMAND)
    if not sober.bundle_state(started):
        return None
    _log("roblox: Sober fell back to the manual APK screen")
    checks = sober.service_checks()
    retried = False
    if all(c.ok for c in checks):
        ok, out = sober.update_sober()
        _log("roblox: flatpak update org.vinegarhq.Sober -> " + ("ok" if ok else "failed: " + out[-200:]))
        retried = True
        t0 = time.time()
        try:
            p2 = subprocess.Popen(cmd, env=clean_env(), stdout=logfh, stderr=logfh, stdin=subprocess.DEVNULL, start_new_session=True)
            p2.wait()
        except OSError as exc:
            _log("roblox: retry could not start: " + str(exc))
            return 0.0, INFO + sober.recovery_note(retried, checks)
        if not sober.bundle_state(t0):
            return time.time() - t0, ""
        checks = sober.service_checks()
    _log("roblox: still needs the bundle; " + sober.explain(checks))
    return 0.0, INFO + sober.recovery_note(retried, checks)


def big_picture_wanted(cfg: Config) -> bool:
    """The Steam tile opens Big Picture when the setting is on - and ALWAYS in CodeAque-only mode (nobody there has a desktop to use)."""
    from . import kiosk
    return bool(getattr(cfg, "steam_bigpicture", True)) or kiosk.shell_mode()


def bigpicture_command(cfg: Config, base: list[str], running: bool) -> list[str]:
    """How to put Steam into full-screen Big Picture mode: a fresh start uses `-gamepadui`; a Steam that is
    already open is told with the steam:// link (a second `steam` call would only hand the request over)."""
    return base + (["steam://open/bigpicture"] if running else ["-gamepadui"])


def _close_bigpicture(base: list[str]):
    """The quit gesture for Steam: leave Big Picture (Steam itself keeps running, and so do your downloads / games)."""
    def term(_proc, _flatpak_id="", _grace=0.0):
        try:
            subprocess.run(base + ["steam://close/bigpicture"], env=clean_env(), stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=15)
        except (OSError, subprocess.SubprocessError):
            pass
    return term


class _SteamProc:
    """Stands in for "the Steam process" in the Esc watcher: alive while the Steam client runs (it may have been
    started long before CodeAque, so it is not our child)."""
    pid = 0

    def __init__(self, running=None):
        from . import steam as steam_mod
        self._running = running or steam_mod.steam_running
        self.seen = False

    def poll(self):
        alive = self._running()
        if alive:
            self.seen = True
            return None
        return 0 if self.seen else None

    def send_signal(self, _sig):
        pass


def _run_steam_bigpicture(cfg: Config, game: Game, cmd: list[str], on_started):
    """Steam tile: open Steam full screen in Big Picture, and come back to CodeAque with the Esc / Guide+B gesture."""
    from . import steam as steam_mod
    base = list(cmd)
    cmd = bigpicture_command(cfg, base, steam_mod.steam_running())
    watched = exitwatch.enabled(cfg)
    if watched:
        time.sleep(_hint_delay())
    _log("launch (steam big picture): " + shlex.join(cmd))
    started = time.time()
    try:
        subprocess.Popen(cmd, env=clean_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        raise LaunchError(f"Could not start Steam: {exc}")
    on_started()
    proc = _SteamProc()
    deadline = time.time() + _steam_appear_timeout()
    while proc.poll() is None and not proc.seen and time.time() < deadline:   # wait for the Steam window to exist
        time.sleep(0.5)
    if not proc.seen:
        return 0.0, INFO + ("Steam is starting - sign in there. After Steam has installed a game, choose "
                            "Settings > Steam > Rescan Steam so it shows up here.")
    watch = None
    if watched:
        watch = exitwatch.Watch(proc, "", term=_close_bigpicture(base), grace=0.0, guard=steam_mod.steam_game_running)
        _log("esc-to-return (steam): " + ("keyboard watcher on (X11)" if watch.keyboard_ok else
                                          f"keyboard watcher unavailable ({watch.keys.why}); gamepad Guide+B only"))
        watch.start()
        exitwatch.notify(exitwatch.HINT_SHORT)
    try:
        while proc.poll() is None and not (watch is not None and watch.triggered):
            time.sleep(0.5)
    finally:
        if watch is not None:
            watch.stop()
    if watch is not None and watch.triggered:
        _log(f"esc-to-return: left Steam Big Picture ({watch.reason})")
    return time.time() - started, ""


def _steam_appear_timeout() -> float:
    try:
        return max(0.0, float(os.environ.get("ATARI_STEAM_WAIT", "90")))
    except ValueError:
        return 90.0


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
                                    stderr=subprocess.DEVNULL, start_new_session=True)
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


class _Alive:
    """Stands in for a background app's process. A browser that hands the window to an already-open copy of itself exits with
    code 0 within seconds: that is NOT "closed" - the app is still there, so it stays alive until the person leaves with
    Esc twice / Guide + B. A process that ends with 0 after a longer run (the window was closed) or with an error is over."""
    HANDOVER = 8.0

    def __init__(self, proc=None, started: float | None = None):
        self.proc = proc
        self.pid = proc.pid if proc is not None else 0
        self.started = started if started is not None else time.time()

    def poll(self):
        if self.proc is None:
            return None
        rc = self.proc.poll()
        if rc is None:
            return None
        if rc != 0 or time.time() - self.started > self.HANDOVER:
            return rc
        return None


def _leave_running(proc, flatpak_id, grace):
    """The Esc watcher's way of "closing" a background app: do nothing - the app stays, CodeAque simply comes back."""
    return None


def _run_background(cfg: Config, cmd: list[str], name: str, on_started, logfh, wait_cap: float = 86400.0):
    """Music apps: start the app, hide CodeAque, and come back on Esc twice / Guide + B WITHOUT closing the app, so it keeps playing."""
    if exitwatch.enabled(cfg):
        time.sleep(_hint_delay())
    started = time.time()
    try:
        proc = subprocess.Popen(cmd, env=clean_env(), stdout=logfh, stderr=logfh, stdin=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        raise LaunchError(f"Could not start {name}: {exc}")
    alive = _Alive(proc, started)
    watch = None
    if exitwatch.enabled(cfg):
        watch = exitwatch.Watch(alive, "", term=_leave_running, grace=0.0)
        _log("esc-to-return (background): " + ("keyboard watcher on (X11)" if watch.keyboard_ok else
                                              f"keyboard watcher unavailable ({watch.keys.why}); gamepad Guide+B only"))
        watch.start()
        exitwatch.notify(exitwatch.HINT_SHORT)
    on_started()
    try:
        while alive.poll() is None and not (watch is not None and watch.triggered) and time.time() - started < wait_cap:
            if watch is None and proc.poll() == 0:
                break                                  # no way to leave with a key: do not hide CodeAque for ever
            time.sleep(0.3)
    finally:
        if watch is not None:
            watch.stop()
    code = proc.poll()
    if code not in (None, 0) and time.time() - started < 8:
        return 0.0, f"{name} closed right away (code {code}). Details: {paths.log_file()}"
    _log(f"background: back in CodeAque, {name} keeps running")
    return time.time() - started, INFO + f"{name} keeps playing in the background. Use the music buttons in the top bar."


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
    webapps.prepare_profile(wa, webapps.profile_root() / wa.id)
    _check_executable(cmd, name)
    _log(f"launch (web, {name}): " + shlex.join(cmd))
    try:
        paths.data_dir().mkdir(parents=True, exist_ok=True)
        logfh = open(paths.log_file(), "ab")
    except OSError:
        logfh = subprocess.DEVNULL
    if wa.background:
        return _run_background(cfg, cmd, name, on_started, logfh)
    if exitwatch.enabled(cfg):
        time.sleep(_hint_delay())       # let the "Press Esc twice to return to CodeAque" screen be read before the browser covers it
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
        proc = subprocess.Popen(cmd, env=env, stdout=logfh, stderr=logfh, stdin=subprocess.DEVNULL, cwd=str(cwd),
                                start_new_session=True)
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


def _slog(msg: str) -> None:
    """The launcher log and (so the user can read it) the session log."""
    _log("steam launch: " + msg)
    try:
        from . import kiosk
        kiosk.log_event("steam launch: " + msg)
    except Exception:
        pass


def _run_steam(cfg: Config, game: Game, on_started, poll: float, start_timeout: float, grace: float = 6.0, status=None, cancel=None,
               steam_running=None, ui_ready=None, settle: float = 3.0, reveal_after: float = 20.0, resend_after: float = 45.0,
               hint_after: float = 60.0):
    """A Steam game from CodeAque. Never fire-and-forget: (1) start Steam first when it is not running (Big Picture) and WAIT until its
    window process exists, (2) only then hand it steam://rungameid/<id>, (3) show live status, resend the request once, offer a hint
    after hint_after seconds, (4) detect the game's process, (5) let the user cancel (Esc / B on the screen, or Esc twice once CodeAque
    has stepped aside to show Steam's own windows). status(phase, text): starting | launching | waiting | reveal | playing."""
    from . import steam as steam_mod
    steam_running = steam_running or steam_mod.steam_running
    ui_ready = ui_ready or steam_mod.steam_ui_ready
    say = status or (lambda phase, text: None)
    cancelled = lambda: cancel is not None and cancel.is_set()      # noqa: E731
    step = max(0.05, min(poll, 1.0))
    base = steam_base_command(cfg)
    _check_executable(base, "Steam")
    appid, title = game.steam_appid, game.title
    on_started()

    def spawn(cmd: list[str], what: str) -> None:
        _slog(f"{what}: " + shlex.join(cmd))
        try:
            subprocess.Popen(cmd, env=clean_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             stdin=subprocess.DEVNULL, start_new_session=True)
        except OSError as exc:
            raise LaunchError(f"Could not start Steam: {exc}")

    def stopped(note: str):
        _slog("cancelled - back in CodeAque (" + note + ")")
        return 0.0, INFO + "Cancelled - back in CodeAque. Steam keeps running; open the Steam tile to see it."

    # 1. Steam first
    t0 = time.time()
    if steam_running():
        _slog(f"Steam is already running (window process {'up' if ui_ready() else 'not up yet'})")
    else:
        spawn(base + (["-gamepadui"] if big_picture_wanted(cfg) else []), "Steam is not running - starting it")
        seen = False
        while True:
            if cancelled():
                return stopped("while Steam was starting")
            running = steam_running()
            seen = seen or running
            waited = time.time() - t0
            if running and ui_ready():
                _slog(f"Steam is up after {int(waited)} s")
                break
            if not running and not seen and waited > 45:
                return 0.0, "Steam did not start. Open the Steam tile once to see what it says (sign in / update), then try again."
            if waited > start_timeout:
                _slog(f"Steam window never appeared after {int(waited)} s - asking anyway")
                break
            say("starting", f"Starting Steam... {int(waited)} s" + ("  (a first start or an update can take a few minutes)" if waited > 30 else ""))
            time.sleep(step)
        if settle > 0:
            time.sleep(settle)                    # the window exists a moment before Steam listens for steam:// requests
    # 2. ask for the game
    say("launching", f"Asking Steam to start {title}...")
    watch = None
    if exitwatch.enabled(cfg):
        watch = exitwatch.Watch(_SteamProc(steam_running), "", term=_close_bigpicture(base), grace=0.0, guard=steam_mod.steam_game_running)
        watch.start()
    spawn(base + [f"steam://rungameid/{appid}"], "asking Steam for the game")
    t1 = time.time()
    resent = revealed = False
    first_seen = 0.0
    try:
        # 3. wait for the game's process
        while time.time() - t1 < start_timeout:
            if find_steam_pids(appid):
                first_seen = time.time()
                break
            if cancelled() or (watch is not None and watch.triggered):
                return stopped("while waiting for the game")
            w = time.time() - t1
            if not steam_running() and w > 10:
                _slog("Steam closed before the game started")
                return 0.0, "Steam closed before the game started. Open the Steam tile, check it signs in, then try again."
            if w >= resend_after and not resent:
                resent = True
                spawn(base + [f"steam://rungameid/{appid}"], "no game yet - asking Steam again")
            if w >= reveal_after and not revealed:
                revealed = True
                _slog("no game process yet - stepping aside so Steam's own windows (sign in, update, Proton download) can be seen")
                say("reveal", f"Waiting for {title}... Steam may be showing a window.")
            text = f"Waiting for {title} to start... {int(w)} s"
            if w >= hint_after:
                text += ("\nStill nothing after a minute. Steam may be asking something (sign in, an update, a Proton download, the game "
                         "installing). Press Esc (or B) to go back to CodeAque, or Esc twice if CodeAque has stepped aside.")
            say("waiting", text)
            time.sleep(step)
        if not first_seen:
            _slog(f"the game never started after {int(time.time() - t1)} s")
            return 0.0, ("Steam did not seem to start the game (play time not recorded). Open the Steam tile to see Steam's own message "
                         "(sign in, update, or the game still installing).")
        _slog(f"game process found after {int(first_seen - t1)} s")
    finally:
        if watch is not None:
            watch.stop()
    say("playing", f"Playing {title}")
    gone_since = 0.0
    while True:
        time.sleep(step)
        if find_steam_pids(appid):
            gone_since = 0.0
        else:
            gone_since = gone_since or time.time()
            if time.time() - gone_since >= grace:  # grace period: launchers/relaunches
                _slog(f"the game ended after {int(gone_since - first_seen)} s")
                return gone_since - first_seen, ""
