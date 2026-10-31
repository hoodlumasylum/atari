"""Screen to TV: show CodeAque on a TV.

1. With a cable (HDMI, or USB-C / DisplayPort to HDMI) - the easy, reliable way. CodeAque sees which screens are plugged in
   (/sys/class/drm) and, on an X11 session, can switch the picture with `xrandr`: the same picture on both, or the TV only.
   A change undoes itself after 15 seconds unless you press "Keep this" (so a TV that shows nothing can never leave you with a black screen).
2. Without a cable - only when the TV can receive it: Miracast ("Screen mirroring" / "Wireless display" on many TVs) through the
   GNOME Network Displays app, or a Chromecast / Google TV from the Chrome or Chromium browser (menu > Cast > Cast screen).
Never raises; every result is plain-English text."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

REVERT_SECONDS = 15
ND_FLATPAK = "org.gnome.NetworkDisplays"


@dataclass
class Output:
    name: str              # xrandr name (HDMI-1) or kernel name (HDMI-A-1)
    connected: bool
    internal: bool
    active: bool = False   # showing a picture now (xrandr)

    @property
    def kind(self) -> str:
        n = self.name.upper()
        return "built-in screen" if self.internal else "HDMI" if "HDMI" in n else "DisplayPort / USB-C" if n.startswith("DP") else "screen"


def _internal(name: str) -> bool:
    return bool(re.match(r"^(eDP|LVDS|DSI)", name, re.I))


def kernel_outputs(sys_root: str = "/sys") -> list[Output]:
    out = []
    try:
        entries = sorted(Path(sys_root, "class/drm").iterdir())
    except OSError:
        return out
    for e in entries:
        m = re.match(r"^card\d+-(.+)$", e.name)
        if not m or not (e / "status").exists():
            continue
        try:
            st = (e / "status").read_text().strip()
        except OSError:
            continue
        out.append(Output(m.group(1), st == "connected", _internal(m.group(1))))
    return out


def parse_xrandr(text: str) -> list[Output]:
    out = []
    for line in text.splitlines():
        m = re.match(r"^(\S+) (connected|disconnected)( primary)?\s*(\d+x\d+\+\d+\+\d+)?", line)
        if m:
            out.append(Output(m.group(1), m.group(2) == "connected", _internal(m.group(1)), bool(m.group(4))))
    return out


def x11(env=os.environ) -> bool:
    return bool(env.get("DISPLAY")) and env.get("XDG_SESSION_TYPE", "x11") != "wayland"


def xrandr_outputs(runner: Callable | None = None, which: Callable = shutil.which) -> list[Output] | None:
    """None when xrandr cannot be used here (not installed, or a Wayland session)."""
    if not which("xrandr") or not x11():
        return None
    runner = runner or subprocess.run
    try:
        p = runner(["xrandr", "--query"], capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_xrandr(p.stdout or "") if p.returncode == 0 else None


def pick(outputs: list[Output]) -> tuple[Output | None, Output | None]:
    """(built-in screen, TV) - the TV is the first connected outside screen."""
    inner = next((o for o in outputs if o.internal and o.connected), None)
    tv = next((o for o in outputs if not o.internal and o.connected), None)
    if inner is None:                        # a desktop computer: the first connected screen counts as "this screen"
        conn = [o for o in outputs if o.connected]
        if len(conn) >= 2:
            inner, tv = conn[0], conn[1]
    return inner, tv


def commands(mode: str, inner: Output | None, tv: Output | None) -> list[str] | None:
    """xrandr arguments for: mirror (same picture on both), tv (TV only), here (this screen only)."""
    if tv is None:
        return None
    if mode == "mirror" and inner is not None:
        return ["xrandr", "--output", tv.name, "--auto", "--same-as", inner.name, "--output", inner.name, "--auto", "--primary"]
    if mode == "tv":
        cmd = ["xrandr", "--output", tv.name, "--auto", "--primary"]
        return cmd + (["--output", inner.name, "--off"] if inner is not None else [])
    if mode == "here" and inner is not None:
        return ["xrandr", "--output", inner.name, "--auto", "--primary", "--output", tv.name, "--off"]
    return None


def undo_command(before: list[Output]) -> list[str]:
    """Put back the screens that were on before (each one --auto) and switch the others off."""
    cmd = ["xrandr"]
    for o in before:
        if not o.connected:
            continue
        cmd += ["--output", o.name] + (["--auto"] if o.active else ["--off"])
    return cmd if len(cmd) > 1 else []


def run(cmd: list[str], runner: Callable | None = None) -> tuple[bool, str]:
    runner = runner or subprocess.run
    try:
        p = runner(cmd, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    return p.returncode == 0, ((p.stderr or p.stdout or "").strip().splitlines() or [""])[-1]


def wireless_app(which: Callable = shutil.which, home: Path | None = None) -> list[str] | None:
    """The command that opens GNOME Network Displays (Miracast), or None."""
    if which("gnome-network-displays"):
        return ["gnome-network-displays"]
    home = home or Path.home()
    for base in (Path("/var/lib/flatpak/app"), home / ".local/share/flatpak/app"):
        if (base / ND_FLATPAK).exists() and which("flatpak"):
            return ["flatpak", "run", ND_FLATPAK]
    return None


CABLE_STEPS = [
    "With a cable (easiest, works with every TV that has HDMI): plug an HDMI cable from the computer into the TV. Laptops with only USB-C need a USB-C to HDMI adapter or cable.",
    "On the TV remote press Input / Source and pick the HDMI number you plugged into (HDMI 1, HDMI 2 ...).",
    "Then choose below: the same picture on both screens, or the TV only. If the TV stays black, wait 15 seconds - the change undoes itself.",
    "No sound from the TV? Settings > Sound in Linux: pick the HDMI output.",
]
WIRELESS_STEPS = [
    "Without a cable (only if the TV supports it - look for \"Screen mirroring\", \"Miracast\" or \"Wireless display\" in the TV's Input / Source menu): switch that on on the TV, then press \"Open wireless display\" below and pick the TV. The computer and TV must be on the same WiFi.",
    "A Chromecast or Google TV: open the Chrome or Chromium browser, menu (three dots) > Cast... > Sources > Cast screen, and pick the TV.",
    "Wireless is slower than a cable: fine for films and menus, often too laggy for fast games.",
]
