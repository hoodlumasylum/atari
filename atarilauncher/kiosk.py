"""Code-only mode ("kiosk"): the computer starts straight into Code - no Linux Mint desktop.

What turning it ON does (one password window, `pkexec`; three small files, all named "atari"):
  1. /usr/local/bin/atari-session                       the session program: starts Code full screen
  2. /usr/share/xsessions/atari.desktop                 a "session" entry, so the login screen can start it
  3. /etc/lightdm/lightdm.conf.d/90-atari-kiosk.conf    LightDM logs you in by itself and picks that session
Nothing else is touched. Turning it OFF removes exactly those three files.

Ways back to the normal Mint desktop (also written in the README and Help):
  * Code > Settings > "Back to Mint desktop"  (needs the password once; removes the three files)
  * Code > Settings > "Open the Mint desktop once"  (no password; this login only)
  * safety net: if Code crashes 5 times in a row, each within seconds of starting, the session starts the Mint desktop by itself
  * at the login screen: click the session icon (top right / next to your name) and choose Cinnamon
  * from a text console (Ctrl+Alt+F2, log in, then):  sudo rm /etc/lightdm/lightdm.conf.d/90-atari-kiosk.conf && sudo systemctl restart lightdm

The session script is the session's main process and runs Code in a loop: when Code ends for any reason except exit code 64 or the
one-off desktop flag, it starts Code again. Code itself also never quits by accident here (ATARI_KIOSK=1: "Quit Code" becomes
"Restart Code"), every game / app it starts runs in its own session (so nothing it does can take Code down), and Code re-takes the
screen whenever an app closes.

Everything outside (pkexec, files under /etc, the clock) is injectable so the tests never touch the system."""
from __future__ import annotations

import getpass
import os
import re
import shlex
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

SESSION_NAME = "atari"

from . import rootauth


@dataclass
class Layout:
    """Where the three files live. Tests point these at a temporary folder."""
    root: Path = Path("/")
    session_script: str = "usr/local/bin/atari-session"
    xsession: str = "usr/share/xsessions/atari.desktop"
    lightdm_conf: str = "etc/lightdm/lightdm.conf.d/90-atari-kiosk.conf"

    def p(self, rel: str) -> Path:
        return self.root / rel

    @property
    def files(self) -> list[Path]:
        return [self.p(self.session_script), self.p(self.xsession), self.p(self.lightdm_conf)]


DEFAULT = Layout()
RECOVERY = ("If you ever get stuck: at the login screen choose the Cinnamon session (the small icon next to your name), "
            "or press Ctrl+Alt+F2, log in, and type:  sudo rm /etc/lightdm/lightdm.conf.d/90-atari-kiosk.conf "
            "&& sudo systemctl restart lightdm")
# One line to paste in a Terminal if Code-only mode ever stops working (rewrites the three files and clears a leftover "desktop once" note;
# needs the installed Code 0.3.x or newer; asks for the sudo password):
RESTORE_COMMAND = ("cd ~/.local/share/atari-launcher && rm -f ~/.config/atari/desktop-once && "
                   "python3 -c \"from atarilauncher import kiosk; print(kiosk.enable_script('$USER'))\" | sudo sh")
FAST_BOOT_TIPS = [
    "Optional - make the computer start faster. Code changes none of this by itself.",
    "See what is slow:  systemd-analyze blame   (in a Terminal).",
    "Printer-less PC:  sudo systemctl disable --now cups cups-browsed",
    "No mobile modem:  sudo systemctl disable --now ModemManager",
    "No Bluetooth devices:  sudo systemctl disable --now bluetooth",
    "Waiting for the network at boot:  sudo systemctl disable NetworkManager-wait-online.service",
    "To undo any of them:  sudo systemctl enable --now <name>.",
]


@dataclass
class Check:
    id: str
    ok: bool
    fatal: bool
    text: str


def in_session(env: dict | None = None) -> bool:
    """True when Code runs as the whole Code-only session (the session script sets ATARI_KIOSK=1)."""
    return (env if env is not None else os.environ).get("ATARI_KIOSK") == "1"


def shell_mode(layout: "Layout | None" = None, env: dict | None = None) -> bool:
    """Code must behave as the whole screen (always full screen again when an app closes): it runs as the Code-only session, OR
    Code-only mode is installed on this computer but this copy was started some other way (desktop menu, autostart, a fallback to the
    desktop) - that is exactly when closing an app used to show the Mint desktop."""
    return in_session(env) or enabled(layout or DEFAULT)


def running_description(env: dict | None = None) -> tuple[str, str]:
    """('code-only'|'desktop', plain text): which kind of session THIS running Code is in."""
    env = env if env is not None else os.environ
    if in_session(env):
        return "code-only", "Code is running as the Code-only session (started by the session program)."
    desk = env.get("XDG_CURRENT_DESKTOP") or env.get("DESKTOP_SESSION") or "unknown"
    return "desktop", (f"Code is running INSIDE the {desk} desktop (started from the menu, an autostart entry or after a fall-back to the "
                       "desktop), not by the Code-only session.")


def log_event(text: str, home: Path | None = None) -> None:
    """One line in the same session.log the session program writes. Never raises."""
    import time
    if home is None and os.environ.get("ATARI_NO_SESSIONLOG"):
        return
    try:
        f = session_log_path(home)
        f.parent.mkdir(parents=True, exist_ok=True)
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(time.strftime("%F %T") + " code: " + text + "\n")
    except OSError:
        pass


def run_script_path() -> Path:
    """Code's own start script (run.sh in the install folder)."""
    return Path(__file__).resolve().parent.parent / "run.sh"


def default_display_manager(path: str = "/etc/X11/default-display-manager") -> str:
    try:
        return Path(path).read_text(errors="replace").strip()
    except OSError:
        return ""


def desktop_session_exec(layout: Layout = DEFAULT) -> str:
    """The command that starts the normal desktop (Cinnamon on Mint), read from its session entry."""
    for name in ("cinnamon.desktop", "cinnamon2d.desktop", "mate.desktop", "xfce.desktop", "ubuntu.desktop"):
        f = layout.p("usr/share/xsessions/" + name)
        try:
            m = re.search(r"^Exec=(.+)$", f.read_text(errors="replace"), re.M)
        except OSError:
            continue
        if m and m.group(1).strip():
            return m.group(1).strip()
    return "cinnamon-session"


def autologin_conflict(conf: str = "/etc/lightdm/lightdm.conf") -> bool:
    """True when /etc/lightdm/lightdm.conf already sets its own autologin (that file wins over our drop-in)."""
    try:
        text = Path(conf).read_text(errors="replace")
    except OSError:
        return False
    return bool(re.search(r"^\s*autologin-(user|session)\s*=\s*\S", text, re.M))


def preflight(layout: Layout = DEFAULT, which: Callable = shutil.which, dm_file: str = "/etc/X11/default-display-manager",
              run_sh: Path | None = None, user: str | None = None, session_type: str | None = None,
              lightdm_conf: str = "/etc/lightdm/lightdm.conf") -> list[Check]:
    out: list[Check] = []
    user = user or getpass.getuser()
    run_sh = run_sh or run_script_path()
    dm = default_display_manager(dm_file)
    out.append(Check("lightdm", "lightdm" in dm, True,
                     "The login screen is LightDM (Linux Mint's normal one)." if "lightdm" in dm else
                     "This computer does not use LightDM (found: " + (os.path.basename(dm) or "unknown") + "), so Code-only mode "
                     "cannot be set up from here."))
    out.append(Check("user", user != "root", True, "You are a normal user." if user != "root" else
                     "Run Code as your normal user, not as root."))
    out.append(Check("pkexec", bool(rootauth.can_elevate(which)), True, "The password window (pkexec) is available." if rootauth.can_elevate(which) else
                     "The password window (pkexec) is missing: install the 'policykit-1' package."))
    out.append(Check("xsessions", layout.p("usr/share/xsessions").is_dir(), True,
                     "The session list exists." if layout.p("usr/share/xsessions").is_dir() else
                     "No /usr/share/xsessions folder - this does not look like a normal desktop install."))
    out.append(Check("run", run_sh.is_file(), True, "Code's start script was found." if run_sh.is_file() else
                     "Code's start script (run.sh) was not found - install Code with ./install.sh first."))
    st = (session_type if session_type is not None else os.environ.get("XDG_SESSION_TYPE", "")).lower()
    out.append(Check("x11", st != "wayland", False, "You are on the normal X11 desktop." if st != "wayland" else
                     "This login uses Wayland. Code-only mode starts an X11 session, which is fine on Mint."))
    conflict = autologin_conflict(lightdm_conf)
    out.append(Check("conflict", not conflict, False, "No other auto-login setting found." if not conflict else
                     f"{lightdm_conf} already has its own auto-login lines, and they win over Code's. "
                     "Remove those two lines, or Code-only mode will not start by itself."))
    return out


def blocked(checks: list[Check]) -> str:
    """'' when everything needed is there, else the first fatal problem in plain English."""
    for c in checks:
        if c.fatal and not c.ok:
            return c.text
    return ""


def enabled(layout: Layout = DEFAULT) -> bool:
    return layout.p(layout.lightdm_conf).is_file() and layout.p(layout.xsession).is_file() \
        and layout.p(layout.session_script).is_file()


# ------------------------------------------------------------------ the three files
SESSION_VERSION = 3     # 2 = 0.4.1 (restarts Code instead of ending the session); 3 = 0.4.2 (also writes ~/.local/share/atari/session.log)
EXIT_LOGOUT = 64        # the one exit code that means "log out on purpose" (anything else: the session starts Code again)
MAX_QUICK_CRASHES = 5   # only this many crashes in a row, each within seconds of starting, send the session to the desktop


def session_outdated(layout: Layout = DEFAULT) -> bool:
    """Code-only mode is on, but its session script was written by an older Code (it ends the session - and so logs out to the
    desktop - when Code stops). /usr/local/bin is root's, so updating Code cannot rewrite it: the person presses Update once."""
    try:
        text = layout.p(layout.session_script).read_text(errors="replace")
    except OSError:
        return False
    m = re.search(r"atari-session-version:\s*(\d+)", text)
    return enabled(layout) and (int(m.group(1)) if m else 1) < SESSION_VERSION


def render_session_script(run_sh: Path, desktop_exec: str, home_hint: str = "") -> str:
    return f"""#!/bin/sh
# Code-only session. Written by Code > Settings > Code-only mode. Remove it with Settings > Back to Mint desktop.
# atari-session-version: {SESSION_VERSION}
# This script IS the session: it never ends while Code is wanted. Whenever Code stops - a crash, a game that took it down,
# "Restart Code" - it starts Code again after a second. Launching and closing games, browsers and emulators never reaches here.
# Exceptions: the "Open the Mint desktop once" flag, Code exiting with code {EXIT_LOGOUT} (log out on purpose), and a real crash
# loop ({MAX_QUICK_CRASHES} crashes in a row, each within seconds): then the Mint desktop starts so you are never locked out.
# Everything it decides is written to ~/.local/share/atari/session.log (Settings > Code-only mode shows the last lines).
RUN={shlex.quote(str(run_sh))}
FLAG="$HOME/.config/atari/desktop-once"
LOG="$HOME/.local/share/atari/session.log"
DELAY="${{ATARI_RESTART_DELAY:-1}}"
mkdir -p "$(dirname "$LOG")" 2>/dev/null
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG" 2>/dev/null || echo 0)" -gt 200000 ]; then tail -n 200 "$LOG" > "$LOG.new" 2>/dev/null && mv "$LOG.new" "$LOG"; fi
log() {{ printf '%s %s\n' "$(date '+%F %T')" "$*" >> "$LOG" 2>/dev/null; }}
desktop() {{
    log "STARTING THE MINT DESKTOP: $*"
    exec {desktop_exec}
}}
log "session start (script version {SESSION_VERSION}, user $USER, display $DISPLAY)"
# "Open the Mint desktop once" in Code's settings leaves this flag file.
if [ -e "$FLAG" ]; then rm -f "$FLAG"; desktop "the 'Open the Mint desktop once' note was found ($FLAG)"; fi
[ -e "$RUN" ] || desktop "Code's start script is missing: $RUN"
# a black screen instead of the grey X pattern while Code starts
command -v xsetroot >/dev/null 2>&1 && xsetroot -solid black 2>/dev/null
# tells Code it is the whole session: Quit means Restart, and it re-takes the screen when any app closes
export ATARI_KIOSK=1
# a small window manager keeps the full-screen window focused (optional; Code also runs without one)
for wm in openbox metacity marco xfwm4; do
    if command -v "$wm" >/dev/null 2>&1; then "$wm" >/dev/null 2>&1 & log "window manager: $wm"; break; fi
done
crashes=0
while :; do
    t=$(date +%s)
    log "starting Code"
    if [ -x "$RUN" ]; then "$RUN" --fullscreen; else sh "$RUN" --fullscreen; fi
    rc=$?
    ran=$(( $(date +%s) - t ))
    log "Code ended: exit code $rc after $ran s"
    [ "$rc" -eq {EXIT_LOGOUT} ] && {{ log "log out on purpose"; exit 0; }}
    if [ -e "$FLAG" ]; then rm -f "$FLAG"; desktop "the 'Open the Mint desktop once' note was found ($FLAG)"; fi
    if [ "$ran" -lt 3 ] || {{ [ "$rc" -ne 0 ] && [ "$ran" -lt 10 ]; }}; then crashes=$((crashes + 1)); else crashes=0; fi
    if [ "$crashes" -ge {MAX_QUICK_CRASHES} ]; then desktop "Code stopped {MAX_QUICK_CRASHES} times in a row within seconds of starting (last exit code $rc)"; fi
    sleep "$DELAY"
done
"""


def render_xsession(session_script: str = "/usr/local/bin/atari-session") -> str:
    return f"""[Desktop Entry]
Name=Code
Comment=Code game launcher as the whole session (no desktop)
Exec={session_script}
TryExec={session_script}
Type=XSession
"""


def render_lightdm(user: str) -> str:
    return f"""# Written by Code > Settings > Code-only mode. Remove with Settings > Back to Mint desktop.
[Seat:*]
autologin-user={user}
autologin-user-timeout=0
autologin-session={SESSION_NAME}
"""


def _write(path: str, content: str, mode: str) -> str:
    return (f"mkdir -p {shlex.quote(os.path.dirname(path))} && printf %s {shlex.quote(content)} > {shlex.quote(path)} "
            f"&& chmod {mode} {shlex.quote(path)}")


def enable_script(user: str, layout: Layout = DEFAULT, run_sh: Path | None = None, desktop_exec: str | None = None) -> str:
    """The shell script that pkexec runs as root. The file contents are inside the command itself (no temp files)."""
    run_sh = run_sh or run_script_path()
    desktop_exec = desktop_exec or desktop_session_exec(layout)
    s, x, c = (str(layout.p(r)) for r in (layout.session_script, layout.xsession, layout.lightdm_conf))
    steps = [
        "set -e",
        "(command -v openbox >/dev/null 2>&1 || apt-get install -y openbox >/dev/null 2>&1 || true)",   # optional, never fatal
        _write(s, render_session_script(run_sh, desktop_exec), "755"),
        _write(x, render_xsession("/" + layout.session_script), "644"),
        _write(c, render_lightdm(user), "644"),
    ]
    return "\n".join(steps)


def disable_script(layout: Layout = DEFAULT) -> str:
    return "set -e\nrm -f " + " ".join(shlex.quote(str(f)) for f in layout.files)


def _pkexec(script: str, out: Callable[[str], None], run: Callable | None) -> int:
    from .appinstall import stream_run
    run = run or stream_run
    return run(["pkexec", "sh", "-c", script], out, None)


def _result_text(rc: int, ok_text: str, fail_text: str) -> tuple[bool, str]:
    if rc == 0:
        return True, ok_text
    if rc == rootauth.REFUSED:
        return False, rootauth.last_error or "This account may not make this change (not an administrator)."
    if rc in (126, 127):
        return False, "The password window was closed, so nothing was changed. Press the button again when you are ready."
    return False, f"{fail_text} (code {rc}). Nothing else was changed."


ON_TEXT = ("Code-only mode is ON. Next time the computer starts (or after you log out) it goes straight into Code. "
           "To get the normal desktop back: Settings > Back to Mint desktop.")
OFF_TEXT = ("Code-only mode is OFF. The normal Mint login comes back after the next restart (or log out and in).")


WM_NAMES = ("openbox", "metacity", "marco", "xfwm4")
WM_PACKAGE = "openbox"
WM_OK_TEXT = ("A window manager (openbox) is installed. Restart the computer (or log out and in) once: from then on Steam's own "
              "windows (Properties, Settings, pop-ups) open on top and can be clicked.")


def window_manager(which: Callable[[str], str | None] | None = None) -> str:
    """Name of the first minimal window manager the session can start ('' = none: windows then have no stacking or focus)."""
    which = which or shutil.which
    return next((w for w in WM_NAMES if which(w)), "")


def install_wm_script() -> str:
    return ("set -e\n"
            "export DEBIAN_FRONTEND=noninteractive\n"
            "command -v apt-get >/dev/null 2>&1 || exit 82\n"
            f"apt-get install -y {WM_PACKAGE} || exit 83\n"
            f"command -v {WM_PACKAGE} >/dev/null 2>&1 || exit 84\n")


def install_wm(run: Callable | None = None, out: Callable[[str], None] = lambda s: None,
               which: Callable[[str], str | None] | None = None) -> tuple[bool, str]:
    """One password: install openbox, so the Code-only session has a real window manager (Steam dialogs, focus). Never raises."""
    try:
        if window_manager(which):
            return True, "A window manager is already installed. " + WM_OK_TEXT.split(". ", 1)[1]
        rc = _pkexec(install_wm_script(), out, run)
        if rc == 0:
            log_event("window manager installed (openbox)")
            return True, WM_OK_TEXT
        ok, text = _result_text(rc, "", "Could not install the window manager")
        if rc in (82, 83, 84):
            text = ("Could not install openbox automatically (code %d). In a Terminal run:  sudo apt install openbox" % rc)
        log_event("window manager install failed: " + text)
        return False, text
    except Exception as exc:
        return False, f"Could not install the window manager: {exc}"


def enable(layout: Layout = DEFAULT, run: Callable | None = None, out: Callable[[str], None] = lambda s: None,
           user: str | None = None, checks: list[Check] | None = None, run_sh: Path | None = None,
           desktop_exec: str | None = None) -> tuple[bool, str]:
    """Turn it on. Never raises. Refuses (with the reason) when a check says it cannot work."""
    try:
        checks = checks if checks is not None else preflight(layout, user=user, run_sh=run_sh)
        why = blocked(checks)
        if why:
            return False, why
        user = user or getpass.getuser()
        rc = _pkexec(enable_script(user, layout, run_sh, desktop_exec), out, run)
        ok, text = _result_text(rc, ON_TEXT, "Could not turn Code-only mode on")
        if ok and not enabled(layout):
            return False, "The files were not written - nothing changed. Try again, or ask for help (Settings > Help > Copy log)."
        return ok, text
    except Exception as exc:  # never take Code down
        return False, f"Could not turn Code-only mode on: {exc}"


def disable(layout: Layout = DEFAULT, run: Callable | None = None, out: Callable[[str], None] = lambda s: None) -> tuple[bool, str]:
    try:
        rc = _pkexec(disable_script(layout), out, run)
        ok, text = _result_text(rc, OFF_TEXT, "Could not turn Code-only mode off")
        if ok and enabled(layout):
            return False, "The files are still there. In a Terminal run:  sudo rm /etc/lightdm/lightdm.conf.d/90-atari-kiosk.conf"
        return ok, text
    except Exception as exc:
        return False, f"Could not turn Code-only mode off: {exc}"


def desktop_once_flag(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".config" / "atari" / "desktop-once"


def open_desktop_once(home: Path | None = None, run: Callable = None, which: Callable = shutil.which,
                      env: dict | None = None) -> tuple[bool, str]:
    """No password needed: leave a flag file, then log out. The session program sees the flag and starts the Mint desktop
    for that one login (the flag is deleted at once, so the next boot is Code-only again)."""
    import subprocess
    run = run or subprocess.run
    env = env if env is not None else os.environ
    flag = desktop_once_flag(home)
    try:
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text("1")
    except OSError as exc:
        return False, f"Could not leave the note for the next login: {exc}"
    if which("cinnamon-session-quit"):
        cmd = ["cinnamon-session-quit", "--logout", "--no-prompt"]
    elif which("loginctl") and env.get("XDG_SESSION_ID"):
        cmd = ["loginctl", "terminate-session", env["XDG_SESSION_ID"]]
    else:
        return True, "Done. Log out (or restart) and the Mint desktop opens once."
    try:
        run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return True, "Done. Log out (or restart) and the Mint desktop opens once."
    return True, "Logging out - the Mint desktop opens next."


def session_log_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".local" / "share" / "atari" / "session.log"


def log_tail(n: int = 4, home: Path | None = None) -> list[str]:
    try:
        return session_log_path(home).read_text(errors="replace").splitlines()[-n:]
    except OSError:
        return []


def diagnose(layout: Layout = DEFAULT, home: Path | None = None) -> list[str]:
    """Plain-English facts about whether the three files agree with each other, and what the session last did. Never raises."""
    home = home or Path.home()
    out: list[str] = []
    s, x, c = (layout.p(r) for r in (layout.session_script, layout.xsession, layout.lightdm_conf))
    for label, f in (("session program", s), ("session entry", x), ("auto-login file", c)):
        out.append(f"{'OK     ' if f.is_file() else 'MISSING'} {label}: {f}")
    try:
        conf = c.read_text(errors="replace")
        m = re.search(r"^\s*autologin-session\s*=\s*(\S+)", conf, re.M)
        u = re.search(r"^\s*autologin-user\s*=\s*(\S+)", conf, re.M)
        out.append(f"{'OK     ' if m and m.group(1) == SESSION_NAME else 'WRONG  '} auto-login session = {m.group(1) if m else 'not set'} "
                   f"(must be {SESSION_NAME}, the name of {x.name})")
        out.append(f"{'OK     ' if u and u.group(1) not in ('root', '') else 'WRONG  '} auto-login user = {u.group(1) if u else 'not set'}")
    except OSError:
        pass
    try:
        text = x.read_text(errors="replace")
        ex = re.search(r"^Exec=(\S+)", text, re.M)
        out.append(f"{'OK     ' if ex and layout.p(ex.group(1).lstrip('/')).is_file() else 'WRONG  '} the session entry starts {ex.group(1) if ex else 'nothing'}")
    except OSError:
        pass
    try:
        text = s.read_text(errors="replace")
        m = re.search(r"^RUN=(.+)$", text, re.M)
        if m:
            run = Path(shlex.split(m.group(1))[0])
            out.append(f"{'OK     ' if run.is_file() else 'MISSING'} Code's start script: {run}")
        v = re.search(r"atari-session-version:\s*(\d+)", text)
        out.append(f"{'OK     ' if v and int(v.group(1)) >= SESSION_VERSION else 'OLD    '} session program version {v.group(1) if v else '1 (from Code 0.3.x or older)'} "
                   f"(this Code writes {SESSION_VERSION})")
    except OSError:
        pass
    if not any(shutil.which(w) for w in ("openbox", "metacity", "marco", "xfwm4")):
        out.append("WRONG  no window manager (openbox) is installed, so after an app closes nothing hands the screen back to Code. "
                   "Fix:  Settings > Code-only mode > Install the window manager (or  sudo apt install openbox). "
                   "Without it Steam's own windows (Properties, Settings) can open out of sight.")
    if (home / ".config" / "autostart" / "atari.desktop").exists():
        out.append("NOTE   Code is also started by the desktop's autostart (~/.config/autostart/atari.desktop). In the Code-only session "
                   "that is not needed; if the computer starts the Mint desktop first, Code appears on top of it.")
    kind, text = running_description()
    out.append(("OK     " if kind == "code-only" else "NOTE   ") + text)
    flag = desktop_once_flag(home)
    out.append(("WILL OPEN THE DESKTOP ONCE  " if flag.exists() else "OK     no 'Open the Mint desktop once' note: ") + str(flag))
    conflict = autologin_conflict(str(layout.p("etc/lightdm/lightdm.conf")))
    out.append(("WRONG  /etc/lightdm/lightdm.conf has its own auto-login lines, and they win over Code's" if conflict
                else "OK     /etc/lightdm/lightdm.conf has no competing auto-login lines"))
    tail = log_tail(6, home)
    out.append("session log (" + str(session_log_path(home)) + "): " + ("" if tail else "nothing written yet - the session program has not run since the update"))
    out += ["    " + t for t in tail]
    return out


def main(argv: list[str] | None = None) -> int:
    """Terminal helper (no Qt needed):  python3 -m atarilauncher.kiosk --print-session   writes the current session script to stdout.
    One-line update by hand:  python3 -m atarilauncher.kiosk --print-session | sudo tee /usr/local/bin/atari-session >/dev/null && sudo chmod 755 /usr/local/bin/atari-session"""
    import sys
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--print-session"]:
        sys.stdout.write(render_session_script(run_script_path(), desktop_session_exec()))
        return 0
    if args == ["--check"]:
        print("\n".join(diagnose()))
        return 0
    if args == ["--status"]:
        print("not installed" if not enabled() else ("OUTDATED (press Update Code-only mode)" if session_outdated() else "up to date"))
        return 0
    print("usage: python3 -m atarilauncher.kiosk --print-session | --status | --check", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
