"""One shared "install this program for me" engine, used by every Install button in Atari (a tile whose program is
missing, the first-run checklist, Settings > Install everything) and by the terminal installer.

It knows ONE table of programs: the emulators (emulators.EMUS), the PC apps and helpers (apps.APP_DEFS / apps.HELPERS,
including Steam) and a few extras (browsers for the web apps, mpv). Their Flathub ids were checked against flathub.org.

How one program gets installed (first way that works wins; every step is explained in plain English):
  1. Flatpak, for your user only (no password): adds the Flathub store for your user when it is missing.
  2. apt through ``pkexec`` - Linux Mint shows its normal graphical password pop-up. Used for programs that are not on
     Flathub (mednafen, mupen64plus, Steam as a fallback: package ``steam-installer``, which takes care of the 32-bit
     libraries itself) and for installing Flatpak itself when the computer has none.
  3. Google Chrome only: Google's official .deb is downloaded and installed with ``pkexec apt-get install`` (Chrome from
     the .deb needs a password once; it is Atari's first choice for Netflix & co. because of Widevine).
Nothing is ever installed without the user pressing the Install button, nothing needs a terminal, and a failure of one
way just moves on to the next. BIOS files, firmware, keys and games are never downloaded.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import sober, apps, covers, installer, paths
from .emulators import EMUS, flatpak_installed

CHROME_DEB_URL = "https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb"
FLATHUB_REPO = installer.FLATHUB_REPO


@dataclass(frozen=True)
class Target:
    id: str
    title: str
    flatpak: str = ""
    apt: str = ""
    exes: tuple = ()
    deb_url: str = ""            # official .deb (Google Chrome)
    deb_first: bool = False      # try the .deb before Flatpak
    special: str = ""            # "umu" -> installer.install_umu
    appimage: str = ""           # "owner/repo|tag|file" official AppImage (DuckStation)
    note: str = ""


@dataclass
class Result:
    target: str
    title: str
    status: str                  # installed | already | failed | cancelled
    detail: str = ""             # plain-English reason / next step
    how: str = ""                # flatpak | apt | deb | umu


def _from_emu(e) -> Target:
    return Target(e.id, e.name, e.flatpak, e.apt, tuple(e.exes), note=e.note, appimage=e.appimage)


def _from_app(a) -> Target:
    return Target(a.id, a.title, a.flatpak, a.apt, tuple(a.exes), note=a.note,
                  deb_url=CHROME_DEB_URL if a.id == "chrome" else "", deb_first=a.id == "chrome",
                  special="umu" if a.id == "umu" else "")


EXTRAS: list[Target] = [
    Target("chromium", "Chromium (browser)", "org.chromium.Chromium", "chromium", ("chromium", "chromium-browser"),
           note="Opens the web apps. Cannot play Netflix (no Widevine) - Google Chrome can."),
    Target("firefox", "Firefox (browser)", "org.mozilla.firefox", "firefox", ("firefox",)),
    Target("brave", "Brave (browser)", "com.brave.Browser", "", ("brave-browser", "brave")),
    Target("mpv", "mpv (video player)", "io.mpv.Mpv", "mpv", ("mpv",)),
]


def _build() -> dict[str, Target]:
    t: dict[str, Target] = {}
    for e in EMUS.values():
        t[e.id] = _from_emu(e)
    for a in list(apps.APP_DEFS) + list(apps.HELPERS):
        t[a.id] = _from_app(a)
    for x in EXTRAS:
        t[x.id] = x
    return t


TARGETS: dict[str, Target] = _build()
DEFAULT_SKIP = set(installer.SKIP_BY_DEFAULT)


def target_for(tid: str, title: str = "") -> Target | None:
    """A known program, or any Flathub app as ``fp:<flatpak id>`` (used for the Free Games list)."""
    if tid in TARGETS:
        return TARGETS[tid]
    if tid.startswith("fp:") and len(tid) > 3:
        return Target(tid, title or tid[3:], tid[3:])
    return None


def all_ids() -> list[str]:
    """What "Install everything" installs: the emulators for the supported consoles, PC apps (with Steam) and helpers."""
    ids = [e.id for e in installer.used_emulators() if e.id not in DEFAULT_SKIP]
    ids += [a.id for a in apps.APP_DEFS] + [a.id for a in apps.HELPERS] + ["mpv"]
    seen: list[str] = []
    for i in ids:
        if i not in seen:
            seen.append(i)
    return seen


def is_installed(t: Target, home: Path | None = None, which: Callable = shutil.which,
                 cfg=None) -> bool:
    if cfg is not None:
        custom = (cfg.retroarch_command if t.id == "retroarch" else cfg.emulator_commands.get(t.id, "")).strip()
        if custom:
            return True
    if any(which(x) for x in t.exes):
        return True
    if t.appimage:
        from .emulators import appimage_dir
        if (appimage_dir(home) / t.appimage.split("|")[2]).is_file():
            return True
    return bool(t.flatpak) and flatpak_installed(t.flatpak, home)


def plan(t: Target, *, flatpak: bool, pkexec: bool, apt: bool) -> list[str]:
    """Ordered ways to install ``t`` with what this computer has. Pure, so it can be tested."""
    steps: list[str] = []
    if t.special == "umu":
        return ["umu"]
    if t.appimage:
        return ["appimage"]                      # no password, no Flatpak needed
    can_apt = apt and pkexec
    fp = bool(t.flatpak) and (flatpak or can_apt)       # without Flatpak, it can be installed first (needs the apt prompt)
    if t.deb_url and t.deb_first and can_apt:
        steps.append("deb")
    if fp:
        steps.append("flatpak")
    if t.apt and can_apt:
        steps.append("apt")
    if t.deb_url and not t.deb_first and can_apt:
        steps.append("deb")
    return steps


# ---------------------------------------------------------------------------------------------- running commands
def stream_run(cmd: list[str], out: Callable[[str], None], cancel: threading.Event | None = None,
               env: dict | None = None) -> int:
    """Run a command, pass each output line (and each \\r progress update) to ``out``. 127 = program missing, 130 = cancelled."""
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                env=env, bufsize=0)
    except OSError:
        return 127
    buf = b""
    last_emit = 0.0
    try:
        while True:
            if cancel is not None and cancel.is_set():
                proc.terminate()
                try:
                    proc.wait(5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                return 130
            chunk = os.read(proc.stdout.fileno(), 4096)
            if not chunk:
                break
            buf += chunk
            parts = buf.replace(b"\r", b"\n").split(b"\n")
            buf = parts.pop()
            for p in parts:
                line = p.decode(errors="replace").strip()
                if line and time.monotonic() - last_emit > 0.15:     # progress bars print a lot: keep the screen calm
                    last_emit = time.monotonic()
                    out(line[:200])
    finally:
        try:
            proc.stdout.close()
        except OSError:
            pass
    return proc.wait()


@dataclass
class Env:
    """Everything the engine touches from the outside, so tests can replace it."""
    run: Callable = stream_run                       # (cmd, out, cancel) -> exit code
    which: Callable = shutil.which
    home: Path | None = None
    http: object = None                              # covers.Http (the umu download)
    download: Callable | None = None                 # (url, dest, out, cancel) -> None  (the Chrome .deb)
    cancel: threading.Event = field(default_factory=threading.Event)
    preflight: Callable | None = None                # () -> list[sober.Check]   (Roblox / Sober)


def _download(url: str, dest: Path, out: Callable[[str], None], cancel: threading.Event) -> None:
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": covers.USER_AGENT})
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as fh:
        total = int(resp.headers.get("Content-Length") or 0)
        got, last = 0, 0.0
        while True:
            if cancel.is_set():
                raise InterruptedError("cancelled")
            chunk = resp.read(256 * 1024)
            if not chunk:
                break
            fh.write(chunk)
            got += len(chunk)
            if time.monotonic() - last > 0.5:
                last = time.monotonic()
                out(f"Downloading... {got // (1024 * 1024)} MB" + (f" of {total // (1024 * 1024)} MB" if total else ""))
    os.replace(tmp, dest)


def _pkexec(env: Env, *cmd: str) -> list[str]:
    return ["pkexec", *cmd]


def _flatpak_ready(env: Env, out: Callable[[str], None], has_apt: bool) -> bool:
    if not env.which("flatpak"):
        if not (has_apt and env.which("pkexec")):
            return False
        out("Flatpak (the program that installs most apps) is missing. Installing it - a password window will pop up...")
        rc = env.run(_pkexec(env, "apt-get", "install", "-y", "flatpak"), out, env.cancel)
        if rc != 0 or not env.which("flatpak"):
            out("Flatpak could not be installed.")
            return False
    out("Adding the Flathub store for your account (if it is not there yet)...")
    rc = env.run(["flatpak", "remote-add", "--if-not-exists", "--user", "flathub", FLATHUB_REPO], out, env.cancel)
    return rc == 0


def _try(step: str, t: Target, env: Env, out: Callable[[str], None], has_apt: bool) -> tuple[bool, str]:
    """(worked, why not)"""
    if step == "flatpak":
        if not _flatpak_ready(env, out, has_apt):
            return False, "Flatpak or the Flathub store is not available (is the internet connected?)"
        out(f"Installing {t.title} from Flathub for your user (no password needed). This can take a few minutes...")
        rc = 1
        for attempt in (1, 2):
            rc = env.run(["flatpak", "install", "--user", "-y", "--noninteractive", "flathub", t.flatpak], out, env.cancel)
            if rc in (0, 130):
                break
            if attempt == 1:
                out("That did not work; trying once more...")
                time.sleep(2.0)
        if rc == 130:
            raise InterruptedError("cancelled")
        return rc == 0 and flatpak_installed(t.flatpak, env.home), f"flatpak install flathub {t.flatpak} did not finish (code {rc})"
    if step == "apt":
        out(f"Installing {t.title} with your system's software sources. A password window will pop up - type your usual password there.")
        rc = env.run(_pkexec(env, "apt-get", "install", "-y", t.apt), out, env.cancel)
        if rc == 130:
            raise InterruptedError("cancelled")
        if rc == 126 or rc == 127:
            return False, "the password window was closed or is not available"
        ok = rc == 0 and any(env.which(x) for x in t.exes)
        return ok, f"apt could not install package {t.apt} (code {rc})"
    if step == "deb":
        dest = paths.data_dir() / "downloads" / Path(t.deb_url).name
        out(f"Downloading {t.title} from its official site...")
        try:
            (env.download or _download)(t.deb_url, dest, out, env.cancel)
        except InterruptedError:
            raise
        except Exception as exc:
            return False, f"the download failed: {exc}"
        out("Installing it - a password window will pop up...")
        rc = env.run(_pkexec(env, "apt-get", "install", "-y", str(dest)), out, env.cancel)
        try:
            dest.unlink()
        except OSError:
            pass
        if rc == 130:
            raise InterruptedError("cancelled")
        return rc == 0 and any(env.which(x) for x in t.exes), f"installing the downloaded package failed (code {rc})"
    return False, "no way to install it here"


def install_one(t: Target, out: Callable[[str], None] = print, env: Env | None = None, cores: list[str] | None = None,
                cfg=None) -> Result:
    """Install one program (and, for RetroArch, the cores asked for). Never raises; returns what happened."""
    env = env or Env()
    if is_installed(t, env.home, env.which, cfg):
        res = Result(t.id, t.title, "already", f"{t.title} is already installed.")
    else:
        has_apt = bool(env.which("apt-get"))
        extra_note = ""
        if t.id == "roblox":
            checks = (env.preflight or sober.preflight)()
            bad = sober.blocking(checks)
            if bad is not None:
                return Result(t.id, t.title, "failed", "Roblox (Sober) cannot run on this computer: " + bad.text)
            out("Checking this computer for Roblox: " + " ".join(c.text for c in checks if c.ok)[:160])
            if sober.needs_vulkan_driver(checks):
                if has_apt and env.which("pkexec"):
                    out("No Vulkan graphics driver found. Installing mesa-vulkan-drivers (a password window will pop up)...")
                    try:
                        rc = env.run(_pkexec(env, "apt-get", "install", "-y", "mesa-vulkan-drivers"), out, env.cancel)
                    except InterruptedError:
                        return Result(t.id, t.title, "cancelled", "Stopped. Press Install again to continue.")
                    if rc == 130:
                        return Result(t.id, t.title, "cancelled", "Stopped. Press Install again to continue.")
                    extra_note = (" Graphics driver added (mesa-vulkan-drivers)." if rc == 0 else
                                  " The graphics driver package could not be added; Roblox will use OpenGL (slower but works).")
                else:
                    extra_note = " No Vulkan graphics driver was found; Roblox will use OpenGL (slower but works)."
        steps = plan(t, flatpak=bool(env.which("flatpak")), pkexec=bool(env.which("pkexec")), apt=has_apt)
        if not steps:
            return Result(t.id, t.title, "failed", no_way_text(t, env))
        reasons: list[str] = []
        res = None
        for step in steps:
            try:
                if step == "umu":
                    o = installer.install_umu(out, env.home, env.http)
                    ok, why = o.status in ("installed", "already"), o.detail
                elif step == "appimage":
                    class _E:     # the installer reads .name and .appimage
                        name, appimage = t.title, t.appimage
                    o = installer.install_appimage(_E, out, env.home, env.http)
                    ok, why = o.status in ("installed", "already"), o.detail
                else:
                    ok, why = _try(step, t, env, out, has_apt)
            except InterruptedError:
                return Result(t.id, t.title, "cancelled", "Stopped. Press Install again to continue.")
            if ok:
                res = Result(t.id, t.title, "installed", f"{t.title} is installed." + extra_note
                             + ((" " + sober.FIRST_RUN_NOTE) if t.id == "roblox" else ""), step)
                break
            reasons.append(why)
            out(f"That way did not work ({why}).")
        if res is None:
            return Result(t.id, t.title, "failed", failure_text(t, reasons, steps)
                          + ((" " + sober.INVALID_BUNDLE_TEXT) if t.id == "roblox" else ""))
    if t.id == "retroarch" and cores and res.status != "failed":
        for o in installer.install_cores(out, env.home, env.http, cores):
            if o.status == "failed":
                res = Result(t.id, t.title, "failed", f"RetroArch is installed but the core {o.name} could not be downloaded ({o.detail}). "
                                                      "Press Install again when the internet works.", res.how)
    return res


def no_way_text(t: Target, env: Env) -> str:
    bits = []
    if t.flatpak:
        bits.append("install Flatpak (Software Manager > search 'flatpak') and try again")
    if t.apt:
        bits.append(f"or run in a terminal:  sudo apt install {t.apt}")
    if not env.which("pkexec") and t.apt:
        bits.insert(0, "the graphical password helper (pkexec / polkit) is missing")
    return f"Atari has no way to install {t.title} on this computer by itself: " + "; ".join(bits or ["see the program's website"]) + "."


def failure_text(t: Target, reasons: list[str], steps: list[str]) -> str:
    tail = []
    if t.flatpak:
        tail.append(f"flatpak install flathub {t.flatpak}")
    if t.apt:
        tail.append(f"sudo apt install {t.apt}")
    hint = ("  You can also try in a terminal:  " + "   or   ".join(tail)) if tail else ""
    return (f"{t.title} could not be installed. " + "; ".join(reasons[-2:]) + ". Check the internet connection and press Install again." + hint)


# ---------------------------------------------------------------------------------------------- a background job
class Job:
    """Installs a list of (target id, core) one after the other in a thread and reports progress through ``emit``."""

    def __init__(self, items: list[tuple[Target, str]], emit: Callable[[str, str], None], env: Env | None = None, cfg=None):
        self.items, self.emit, self.env, self.cfg = items, emit, env or Env(), cfg
        self.results: list[Result] = []
        self.thread: threading.Thread | None = None

    def start(self) -> "Job":
        self.thread = threading.Thread(target=self._run, name="atari-install", daemon=True)
        self.thread.start()
        return self

    def cancel(self) -> None:
        self.env.cancel.set()

    def _run(self) -> None:
        n = len(self.items)
        for i, (t, core) in enumerate(self.items, 1):
            if self.env.cancel.is_set():
                break
            prefix = f"({i}/{n}) " if n > 1 else ""
            self.emit("step", f"{prefix}{t.title}")
            res = install_one(t, lambda line, p=prefix, ti=t.title: self.emit("line", f"{p}{ti}: {line}"), self.env,
                              [c for c in core.split(",") if c] if core else None, self.cfg)
            self.results.append(res)
            if res.status == "cancelled":
                break
        self.emit("done", "")


def summary_text(results: list[Result]) -> str:
    ok = [r for r in results if r.status == "installed"]
    already = [r for r in results if r.status == "already"]
    bad = [r for r in results if r.status == "failed"]
    parts = []
    if ok:
        parts.append("Installed: " + ", ".join(r.title for r in ok) + ".")
    for r in ok:
        if r.target == "roblox":
            if "Graphics driver added" in r.detail:
                parts.append("Graphics driver added too.")
            parts.append(sober.FIRST_RUN_NOTE)
    if already:
        parts.append(f"Already installed: {len(already)}.")
    if bad:
        parts.append("Could not install: " + ", ".join(r.title for r in bad) + ". " + (bad[0].detail if len(bad) == 1 else "Press Install again later - it only tries what is missing."))
    if any(r.status == "cancelled" for r in results):
        parts.append("Stopped before the end.")
    return " ".join(parts) or "Nothing to do."
