"""Pairing Bluetooth controllers from CodeAque, with BlueZ's own tool `bluetoothctl` (the same thing the desktop's Bluetooth settings use).

Steps: make sure the Bluetooth adapter is on (only if it is blocked or the service is stopped does this need the administrator password -
asked in CodeAque's own dialog through rootauth), search for 15 seconds, list what was found (controllers first), then pair, trust (so it
reconnects by itself next time) and connect the one you pick. Every function returns plain-English text and never raises."""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable

from . import rootauth

SCAN_SECONDS = 15
MAC = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$", re.I)

PAIRING_STEPS = [
    "Put the controller into pairing mode first (the light flashes quickly when it is ready):",
    "Xbox-style pads: switch the pad on, then hold the small pairing button on the top edge (next to the charging port) until the logo flashes fast.",
    "PlayStation-style pads: hold the Share / Create button and the round Home button together for about 3 seconds until the light flashes.",
    "Switch-style Pro pads: hold the small sync button on the top edge until the lights move from side to side.",
    "Other pads: look for a button marked with the Bluetooth sign, \"pair\" or \"sync\" (often held together with Start or Home). The pad's leaflet says which.",
    "Keep the pad close to the computer, then press Search below.",
]


@dataclass
class Device:
    mac: str
    name: str
    icon: str = ""
    paired: bool = False
    trusted: bool = False
    connected: bool = False
    battery: int | None = None

    @property
    def is_pad(self) -> bool:
        n = self.name.lower()
        return self.icon == "input-gaming" or any(w in n for w in ("controller", "gamepad", "joy-con", "pro controller", "xbox", "dualshock",
                                                                     "dualsense", "8bitdo", "pad"))


def available(which: Callable = shutil.which) -> bool:
    return bool(which("bluetoothctl"))


def _run(args: list[str], runner: Callable | None = None, timeout: float = 20.0) -> tuple[int, str]:
    runner = runner or subprocess.run
    try:
        p = runner(["bluetoothctl", *args], capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        return 124, out.decode(errors="replace") if isinstance(out, bytes) else out
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, str(exc)


def parse_devices(text: str) -> list[tuple[str, str]]:
    out = []
    for line in text.splitlines():
        m = re.search(r"Device\s+(([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2})\s*(.*)$", line)
        if m and (m.group(1).upper(), m.group(3).strip()) not in out and "[DEL]" not in line:
            out.append((m.group(1).upper(), m.group(3).strip()))
    return out


def parse_info(mac: str, name: str, text: str) -> Device:
    def field(k):
        m = re.search(r"^\s*" + re.escape(k) + r":\s*(.*)$", text, re.M)
        return m.group(1).strip() if m else ""
    d = Device(mac, field("Name") or field("Alias") or name or mac)
    d.icon = field("Icon")
    d.paired, d.trusted, d.connected = (field(k) == "yes" for k in ("Paired", "Trusted", "Connected"))
    m = re.search(r"Battery Percentage:\s*0x[0-9a-fA-F]+\s*\((\d+)\)", text)
    d.battery = int(m.group(1)) if m else None
    return d


def adapter(runner: Callable | None = None) -> dict:
    """{'present': bool, 'powered': bool, 'blocked': bool}"""
    rc, out = _run(["show"], runner, 10)
    present = rc == 0 and "Controller" in out and "No default controller" not in out
    blocked = "off-blocked" in out or "org.bluez.Error.Blocked" in out
    return {"present": present, "powered": bool(re.search(r"^\s*Powered:\s*yes", out, re.M)), "blocked": blocked}


def _admin(cmd: list[str], runner: Callable | None, which: Callable) -> tuple[bool, str]:
    runner = runner or subprocess.run
    full, secret, early = rootauth.prepare(["pkexec", *cmd], which)
    if early is not None:
        return False, "The password window was closed, so nothing was changed."
    try:
        p = runner(full, capture_output=True, text=True, timeout=30, **({"input": secret.decode()} if secret else {"stdin": subprocess.DEVNULL}))
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    return p.returncode == 0, ((p.stderr or p.stdout or "").strip().splitlines() or [""])[0]


def ensure_on(runner: Callable | None = None, which: Callable = shutil.which) -> tuple[bool, str]:
    """Bluetooth on. Asks for the administrator password only when the service is stopped or the radio is blocked."""
    if not available(which):
        return False, "The Bluetooth tools are not installed. In a Terminal:  sudo apt install bluez   (then restart the computer)."
    st = adapter(runner)
    if not st["present"]:
        _admin(["systemctl", "start", "bluetooth"], runner, which)
        st = adapter(runner)
        if not st["present"]:
            return False, "No Bluetooth adapter found. This computer may not have Bluetooth (a small USB Bluetooth adapter adds it)."
    if st["blocked"] and which("rfkill"):
        _admin(["rfkill", "unblock", "bluetooth"], runner, which)
    if not st["powered"] or st["blocked"]:
        rc, out = _run(["power", "on"], runner, 10)
        if "succeeded" not in out and not adapter(runner)["powered"]:
            return False, "Bluetooth is switched off and could not be switched on (" + (out.strip().splitlines() or ["no answer"])[-1] + ")."
    return True, "Bluetooth is on."


def devices(runner: Callable | None = None, extra: str = "") -> list[Device]:
    _rc, out = _run(["devices"], runner, 10)
    found = []
    for mac, name in parse_devices(out + "\n" + extra):
        _rc, info = _run(["info", mac], runner, 10)
        found.append(parse_info(mac, name, info))
    found.sort(key=lambda d: (not d.is_pad, not d.connected, d.name.lower()))
    return found


def scan(runner: Callable | None = None, seconds: int = SCAN_SECONDS) -> list[Device]:
    """Search for `seconds` (the pads must be in pairing mode), then list everything Bluetooth knows of."""
    _rc, out = _run(["--timeout", str(seconds), "scan", "on"], runner, seconds + 10)
    return devices(runner, extra=out)


def connect_pad(mac: str, runner: Callable | None = None, say: Callable[[str], None] | None = None) -> tuple[bool, str]:
    """Pair, trust and connect. Returns (worked, plain text)."""
    say = say or (lambda t: None)
    if not MAC.match(mac or ""):
        return False, "That is not a Bluetooth address."
    say("Pairing... (keep the pad in pairing mode)")
    rc, out = _run(["pair", mac], runner, 40)
    if "Pairing successful" not in out and "AlreadyExists" not in out and rc != 0:
        why = "the pad stopped searching - put it in pairing mode again and retry" if ("not available" in out or "AuthenticationTimeout" in out
                                                                                       or "ConnectionAttemptFailed" in out or rc == 124) else \
              "it asked for a code this screen cannot type - pair it once in the desktop's Bluetooth settings" if "AuthenticationRejected" in out else \
              (out.strip().splitlines() or ["no answer"])[-1]
        return False, "Pairing did not work: " + why + "."
    say("Paired. Trusting it so it reconnects by itself next time...")
    _run(["trust", mac], runner, 15)
    say("Connecting...")
    rc, out = _run(["connect", mac], runner, 30)
    if "Connection successful" in out or "AlreadyConnected" in out or rc == 0:
        return True, "Connected. Press a button on the pad - it should now show on the Controllers page."
    return False, "Paired, but it did not connect yet. Press the Home button on the pad (it reconnects by itself), or press it again here."


def forget(mac: str, runner: Callable | None = None) -> tuple[bool, str]:
    if not MAC.match(mac or ""):
        return False, "That is not a Bluetooth address."
    rc, out = _run(["remove", mac], runner, 15)
    return ("removed" in out or rc == 0), ("Removed. Pair it again any time." if ("removed" in out or rc == 0) else "Could not remove it.")
