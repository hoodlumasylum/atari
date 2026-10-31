"""Battery level of connected gamepads, for the small indicator in the top bar.

Read from the kernel (/sys/class/power_supply - the drivers for PlayStation, Switch, Xbox-over-Bluetooth and many others put a battery
there and link it to the pad's input device), with UPower (`upower --dump`, kind "gaming-input") as a second source. A pad that reports
nothing: wired pads are not shown, a Bluetooth pad shows "Battery unknown". Never raises."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import pads

LOW = 15


@dataclass
class Battery:
    path: str              # the device folder it belongs to (real path)
    percent: int | None
    status: str            # Charging / Discharging / Full / Not charging / Unknown
    level: str = ""        # capacity_level when there is no number: Low / Normal / High / Full / Critical
    model: str = ""


def _read(p: Path) -> str:
    try:
        return p.read_text(errors="replace").strip()
    except OSError:
        return ""


def sysfs_batteries(sys_root: str = "/sys") -> list[Battery]:
    out = []
    base = Path(sys_root) / "class/power_supply"
    try:
        entries = sorted(base.iterdir())
    except OSError:
        return out
    for e in entries:
        if _read(e / "scope") != "Device" and not re.search(r"controller|gamepad|joy|xpad|ds4|dualsense|sony|nintendo|gip", e.name, re.I):
            continue                                       # the computer's own battery / charger
        cap = _read(e / "capacity")
        try:
            real = os.path.realpath(e / "device")
        except OSError:
            real = ""
        out.append(Battery(real, int(cap) if cap.isdigit() else None, _read(e / "status") or "Unknown",
                           _read(e / "capacity_level"), _read(e / "model_name")))
    return out


def pad_device_path(pad: pads.Pad, sys_root: str = "/sys") -> str:
    try:
        return os.path.realpath(Path(sys_root) / "class/input" / pad.js / "device")
    except OSError:
        return ""


def upower_batteries(which: Callable = shutil.which, runner: Callable | None = None) -> dict[str, tuple[int | None, str]]:
    """{model name: (percent, state)} for gaming-input devices UPower knows."""
    if not which("upower"):
        return {}
    runner = runner or subprocess.run
    try:
        text = runner(["upower", "--dump"], capture_output=True, text=True, timeout=4).stdout or ""
    except (OSError, subprocess.SubprocessError):
        return {}
    found = {}
    for block in re.split(r"\n\s*\n", text):
        if not re.search(r"^\s*gaming-input", block, re.M):
            continue
        model = re.search(r"^\s*model:\s*(.+)$", block, re.M)
        pct = re.search(r"^\s*percentage:\s*(\d+)", block, re.M)
        state = re.search(r"^\s*state:\s*(\S+)", block, re.M)
        if model:
            found[model.group(1).strip()] = (int(pct.group(1)) if pct else None, state.group(1) if state else "")
    return found


def describe(percent: int | None, status: str, level: str = "") -> tuple[str, bool, bool]:
    """-> (text, low, charging)"""
    charging = status.lower() == "charging"
    if percent is None:
        if level and level.lower() != "unknown":
            low = level.lower() in ("low", "critical")
            return (("Charging" if charging else "Battery " + level.lower()), low and not charging, charging)
        return ("Charging" if charging else "Battery unknown"), False, charging
    if status.lower() == "full":
        return "Full", False, False
    return (f"Charging {percent}%" if charging else f"{percent}%"), percent <= LOW and not charging, charging


def for_pads(found: list[pads.Pad], sys_root: str = "/sys", upower: dict | None = None) -> list[dict]:
    """One entry per connected pad that has something to show: {'name', 'text', 'low', 'charging', 'percent', 'known'}."""
    bats = sysfs_batteries(sys_root)
    rows = []
    for p in found:
        dev = pad_device_path(p, sys_root)
        hit = None
        for b in bats:
            if b.path and dev and (dev == b.path or dev.startswith(b.path.rstrip("/") + "/")):
                hit = b
                break
        if hit is not None:
            text, low, charging = describe(hit.percent, hit.status, hit.level)
            pct = hit.percent
        elif upower and p.name in upower:
            pct, state = upower[p.name]
            text, low, charging = describe(pct, {"charging": "Charging", "fully-charged": "Full"}.get(state, state))
        elif p.how == "Bluetooth":
            pct, (text, low, charging) = None, describe(None, "")
        else:
            continue                                      # a wired pad without a battery report: nothing to show
        rows.append({"name": p.name, "text": text, "low": low, "charging": charging, "percent": -1 if pct is None else pct,
                     "known": pct is not None or text not in ("Battery unknown",)})
    return rows
