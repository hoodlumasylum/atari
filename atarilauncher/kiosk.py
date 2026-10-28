"""Code-only mode ("kiosk"): the computer starts straight into Code - no Linux Mint desktop.

What turning it ON does (one password window, `pkexec`; three small files, all named "atari"):
  1. /usr/local/bin/atari-session                       the session program: starts Code full screen
  2. /usr/share/xsessions/atari.desktop                 a "session" entry, so the login screen can start it
  3. /etc/lightdm/lightdm.conf.d/90-atari-kiosk.conf    LightDM logs you in by itself and picks that session
Nothing else is touched. Turning it OFF removes exactly those three files.

Ways back to the normal Mint desktop (also written in the README and Help):
  * Code > Settings > "Back to Mint desktop"  (needs the password once; removes the three files)
  * Code > Settings > "Open the Mint desktop once"  (no password; this login only)
  * safety net: if Code fails to start 3 times in a row, the session starts the Mint desktop by itself
  * at the login screen: click the session icon (top right / next to your name) and choose Cinnamon
  * from a text console (Ctrl+Alt+F2, log in, then):  sudo rm /etc/lightdm/lightdm.conf.d/90-atari-kiosk.conf && sudo systemctl restart lightdm

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
    out.append(Check("pkexec", bool(which("pkexec")), True, "The password window (pkexec) is available." if which("pkexec") else
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
def render_session_script(run_sh: Path, desktop_exec: str, home_hint: str = "") -> str:
    return f"""#!/bin/sh
# Code-only session. Written by Code > Settings > Code-only mode. Remove it with Settings > Back to Mint desktop.
RUN={shlex.quote(str(run_sh))}
FLAG="$HOME/.config/atari/desktop-once"
desktop() {{
    exec {desktop_exec}
}}
# "Open the Mint desktop once" in Code's settings leaves this flag file.
if [ -e "$FLAG" ]; then rm -f "$FLAG"; desktop; fi
[ -x "$RUN" ] || desktop
# a small window manager keeps the full-screen window focused (optional; Code also runs without one)
for wm in openbox metacity marco xfwm4; do
    if command -v "$wm" >/dev/null 2>&1; then "$wm" >/dev/null 2>&1 & break; fi
done
n=0
while [ "$n" -lt 3 ]; do
    t=$(date +%s)
    "$RUN" --fullscreen
    if [ $(( $(date +%s) - t )) -ge 30 ]; then exit 0; fi   # it ran for a while and was closed on purpose: log out
    n=$((n + 1))
done
# Code would not start three times in a row: never leave the computer without a desktop
desktop
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
    if rc in (126, 127):
        return False, "The password window was closed, so nothing was changed. Press the button again when you are ready."
    return False, f"{fail_text} (code {rc}). Nothing else was changed."


ON_TEXT = ("Code-only mode is ON. Next time the computer starts (or after you log out) it goes straight into Code. "
           "To get the normal desktop back: Settings > Back to Mint desktop.")
OFF_TEXT = ("Code-only mode is OFF. The normal Mint login comes back after the next restart (or log out and in).")


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
