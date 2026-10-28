"""Asking for the administrator password INSIDE Code (no pkexec / polkit window needed).

Why: in Code-only mode there is no desktop, so the polkit password agent that pkexec relies on is not running (or its window opens
behind Code's full screen window) and a Settings button that needs a password seems to do nothing. Instead:
  * every privileged action goes through ``stream_run(["pkexec", ...])`` (the old spelling kept everywhere); when Code has an in-app
    password dialog (``set_provider``), that call is turned into ``sudo -S -k -p '' -- ...`` and the password typed in Code's own dialog
    is fed to sudo on its standard input;
  * the password is checked first (``sudo -S -k -p '' true``), a wrong one asks again (up to 5 times), a cancelled dialog is exit code 126;
  * it is never put on a command line, in the environment, in a file or in the log. It is held in memory for 90 seconds only, so one
    action with several steps (install a package, then the app) asks once; ``forget()`` clears it at once;
  * without a provider (tests, the command line) or without sudo, nothing changes: pkexec is used exactly as before;
  * as root already, the command just runs.
Exit codes: 126 = no password entered / dialog closed, 125 = sudo refused this user (not an administrator). Nothing here raises."""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from typing import Callable

CACHE_SECONDS = 90.0
MAX_TRIES = 5
CANCELLED = 126
REFUSED = 125

_lock = threading.Lock()
_provider: Callable[[str, str], str | None] | None = None      # (prompt, error) -> password or None (cancelled)
_cache: tuple[str, float] | None = None
last_error = ""


def set_provider(fn: Callable[[str, str], str | None] | None) -> None:
    global _provider
    _provider = fn
    forget()


def provider() -> Callable | None:
    return _provider


def forget() -> None:
    global _cache
    _cache = None


def can_elevate(which: Callable | None = None) -> bool:
    which = which or shutil.which
    return bool(which("pkexec") or (_provider is not None and which("sudo"))) or os.geteuid() == 0


def _sudo(password: str, args: list[str], runner: Callable | None = None, timeout: float = 30.0):
    runner = runner or subprocess.run
    return runner(["sudo", "-S", "-k", "-p", "", *args], input=(password + "\n").encode(), capture_output=True, timeout=timeout)


def check_password(password: str, runner: Callable | None = None) -> tuple[bool, str]:
    """(True, '') when sudo accepts it; otherwise (False, why) with why in plain words."""
    try:
        p = _sudo(password, ["true"], runner)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"Could not run sudo ({exc})."
    if p.returncode == 0:
        return True, ""
    err = (p.stderr or b"").decode(errors="replace").lower()
    if "not in the sudoers" in err or "may not run sudo" in err or "not allowed to run sudo" in err:
        return False, "REFUSED"
    return False, "Wrong password."


def get_password(prompt: str, runner: Callable | None = None) -> tuple[str | None, int]:
    """(password, 0) | (None, 126 cancelled) | (None, 125 this user may not use sudo). Uses the 90 s memory, then asks."""
    global _cache, last_error
    now = time.monotonic()
    with _lock:
        if _cache and _cache[1] > now:
            return _cache[0], 0
    ask = _provider
    if ask is None:
        return None, CANCELLED
    error = ""
    for _ in range(MAX_TRIES):
        pw = ask(prompt, error)
        if pw is None:
            return None, CANCELLED
        ok, why = check_password(pw, runner)
        if ok:
            _cache = (pw, time.monotonic() + CACHE_SECONDS)
            return pw, 0
        if why == "REFUSED":
            last_error = "This account is not allowed to use administrator rights (sudo), so Code cannot make this change. Ask the owner of the computer."
            return None, REFUSED
        error = why
        if not pw:
            error = "Type the password for this computer's user (the one you log in with)."
    last_error = "The password was wrong five times. Nothing was changed."
    return None, CANCELLED


def prepare(cmd: list[str], which: Callable | None = None, runner: Callable | None = None) -> tuple[list[str], bytes | None, int | None]:
    """Turn a ["pkexec", ...] command into what really runs. -> (command, stdin bytes or None, early exit code or None).
    Anything that is not a pkexec command is returned untouched."""
    global last_error
    if not cmd or cmd[0] != "pkexec":
        return cmd, None, None
    which = which or shutil.which
    if os.geteuid() == 0:
        return cmd[1:], None, None
    if _provider is None or not which("sudo"):
        return cmd, None, None
    last_error = ""
    pw, rc = get_password("Type the password for this computer's user to continue.", runner)
    if pw is None:
        if rc == REFUSED and which("pkexec"):
            return cmd, None, None                 # sudo said no: the old graphical window may still work
        return cmd, None, rc
    return ["sudo", "-S", "-k", "-p", "", "--", *cmd[1:]], (pw + "\n").encode(), None
