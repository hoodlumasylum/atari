"""Power menu actions: restart the device, shut it down, sleep.

`systemctl reboot|poweroff|suspend` normally works without a password for the person sitting at the computer (a local logind session
is allowed by polkit). When it is refused (a remote or odd session, no polkit rule), the same command is retried with `pkexec`
(the normal password window). If systemctl does not exist, `loginctl` is tried before pkexec. Nothing here ever raises.
Code-only mode needs nothing special: the session is the user's own local session, so the first try is the one that works."""
from __future__ import annotations

import shutil
import subprocess
from typing import Callable

from . import rootauth

ACTIONS = {
    "reboot": ("restart the computer", "Restarting the computer ..."),
    "poweroff": ("shut the computer down", "Shutting down ..."),
    "suspend": ("put the computer to sleep", "Going to sleep ..."),
}
NEEDS_CONFIRM = ("reboot", "poweroff")


def command_chain(action: str, which: Callable | None = None) -> list[list[str]]:
    """The commands to try, in order."""
    which = which or shutil.which
    if action not in ACTIONS:
        return []
    chain: list[list[str]] = []
    if which("systemctl"):
        chain.append(["systemctl", action])
    elif which("loginctl"):
        chain.append(["loginctl", action])
    if which("pkexec"):
        chain.append(["pkexec", "systemctl", action] if which("systemctl") else ["pkexec", "loginctl", action])
    return chain


def run(action: str, runner: Callable | None = None, which: Callable | None = None, timeout: float = 60.0) -> tuple[bool, str]:
    """Do it. (True, text to show) when the system accepted the command; (False, plain-English reason) otherwise."""
    runner = runner or subprocess.run
    which = which or shutil.which
    what, doing = ACTIONS.get(action, ("", ""))
    chain = command_chain(action, which)
    if not chain:
        return False, f"This computer has no systemctl / loginctl, so Code cannot {what or action}. Use the power button."
    last = ""
    for cmd in chain:
        kw = {"stdin": subprocess.DEVNULL}
        if cmd[0] == "pkexec":                    # the second try needs the administrator password: asked inside Code (no polkit window)
            cmd, secret, early = rootauth.prepare(cmd, which)
            if early is not None:
                return False, f"The password window was closed, so Code did not {what}." if early == rootauth.CANCELLED else (rootauth.last_error or f"Code may not {what}.")
            if secret is not None:
                kw = {"input": secret.decode()}
        try:
            p = runner(cmd, capture_output=True, text=True, timeout=timeout, **kw)
        except subprocess.TimeoutExpired:
            return True, doing                       # a slow shutdown is still a shutdown in progress
        except (OSError, subprocess.SubprocessError) as exc:
            last = str(exc)
            continue
        if p.returncode == 0:
            return True, doing
        last = ((p.stderr or p.stdout or "").strip().splitlines() or [f"exit code {p.returncode}"])[0]
        if p.returncode in (126, 127) and cmd[0] in ("pkexec", "sudo"):      # the password window was closed: do not try anything else
            return False, f"The password window was closed, so Code did not {what}."
    return False, f"Could not {what} ({last}). Use the power button, or in a Terminal:  systemctl {action}"
