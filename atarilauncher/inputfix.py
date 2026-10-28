"""One-click "Fix Steam controller / gamepad permissions".

Steam says "Missing permissions for input devices" when Linux has no udev rules that let a normal user talk to
controllers and /dev/uinput. The fix is Valve's own `steam-devices` rules. Order of attempts (one password window):
  1. the `steam-devices` package from the distribution (Linux Mint / Ubuntu),
  2. else Valve's rules file (60-steam-input.rules) downloaded and installed into /etc/udev/rules.d.
Everything outside (pkexec, apt, network) is injectable, so tests never touch the system."""
from __future__ import annotations

import glob
import os
import shlex
import shutil
import tempfile
import urllib.request

from . import rootauth
from pathlib import Path
from typing import Callable

RULES_URL = os.environ.get("ATARI_STEAM_RULES_URL",
                           "https://raw.githubusercontent.com/ValveSoftware/steam-devices/master/60-steam-input.rules")
RULES_DIRS = ("/etc/udev/rules.d", "/usr/lib/udev/rules.d", "/lib/udev/rules.d", "/run/udev/rules.d")
TARGET = "/etc/udev/rules.d/60-steam-input.rules"
RELOAD = "udevadm control --reload-rules && udevadm trigger"
AFTER = ("Done. Unplug your controller and plug it back in (or turn it off and on), then restart Steam. "
         "If Steam still complains, log out and back in once.")


def rules_installed(dirs=RULES_DIRS) -> bool:
    for d in dirs:
        if glob.glob(os.path.join(d, "*steam*.rules")) or glob.glob(os.path.join(d, "*steam-input*")):
            return True
    return False


def uinput_ok(path: str = "/dev/uinput") -> bool:
    return os.path.exists(path) and os.access(path, os.W_OK)


def status(dirs=RULES_DIRS, uinput: str = "/dev/uinput") -> tuple[bool, str]:
    """(everything looks fine, plain-English text)."""
    rules, ui = rules_installed(dirs), uinput_ok(uinput)
    if rules and ui:
        return True, "The controller permissions for Steam look fine already."
    bits = []
    if not rules:
        bits.append("Valve's controller rules (steam-devices) are not installed")
    if not ui:
        bits.append("Steam cannot write to /dev/uinput")
    return False, "; ".join(bits).capitalize() + ". The fix needs your password once."


def download_rules(dest: str, url: str = RULES_URL) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "atari-launcher"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        if b"28de" not in data.lower():  # a real rules file mentions Valve's USB id
            return False
        Path(dest).write_bytes(data)
        return True
    except (OSError, ValueError):
        return False


def fix(out: Callable[[str], None], run: Callable | None = None, which: Callable = shutil.which,
        download: Callable = download_rules) -> tuple[bool, str]:
    """Install the rules. Returns (worked, plain-English result). Never raises."""
    from .appinstall import stream_run
    run = run or stream_run
    if not rootauth.can_elevate(which):
        return False, ("Code needs the 'pkexec' password window for this and it is missing. In a Terminal run:  "
                       "sudo apt install steam-devices")
    try:
        if which("apt-get"):
            out("Installing Valve's controller rules (steam-devices) - a password window will pop up...")
            rc = run(["pkexec", "sh", "-c", "apt-get install -y steam-devices && modprobe uinput; " + RELOAD], out, None)
            if rc == 0 and rules_installed():
                return True, AFTER
            out("The package was not available - downloading Valve's rules file instead...")
        tmp = os.path.join(tempfile.mkdtemp(prefix="atari-rules-"), "60-steam-input.rules")
        if not download(tmp):
            return False, ("Could not download Valve's rules (are you online?). Try again, or in a Terminal run:  "
                           "sudo apt install steam-devices")
        rc = run(["pkexec", "sh", "-c",
                  f"install -m 0644 {shlex.quote(tmp)} {TARGET} && (modprobe uinput || true) && {RELOAD}"], out, None)
        if rc == 0:
            return True, AFTER
        if rc == 126 or rc == 127:
            return False, "The password window was closed, so nothing was changed. Press the button again when you are ready."
        return False, f"The fix did not work (code {rc}). In a Terminal run:  sudo apt install steam-devices"
    except Exception as exc:  # never take Code down
        return False, f"The fix hit a problem: {exc}"
