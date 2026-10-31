"""Screen brightness for laptops whose brightness keys do nothing (seen on Dells running Mint).

Ways, in order: brightnessctl (installed on request), /sys/class/backlight through a pkexec helper, then xrandr --brightness
(software dimming only - it cannot make the panel brighter than its backlight). When no backlight is controllable, fix_script()
adds acpi_backlight=native (a second press: vendor) to the kernel options, backing up /etc/default/grub first; a reboot is needed.
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Callable

BACKLIGHT = "/sys/class/backlight"
GRUB = "/etc/default/grub"
BACKUP = "/etc/default/grub.codeaque-brightness.bak"
FIX_ORDER = ("native", "vendor")


def _run(cmd, runner=None, timeout=10) -> tuple[int, str]:
    try:
        p = (runner or subprocess.run)(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)


def backlights(root: str = BACKLIGHT) -> list[Path]:
    """Backlight devices, the best first (firmware/platform before raw, as the kernel's own docs advise)."""
    rank = {"firmware": 0, "platform": 1, "raw": 2}
    out = []
    try:
        for d in Path(root).iterdir():
            if (d / "max_brightness").exists():
                kind = (d / "type").read_text().strip() if (d / "type").exists() else "raw"
                out.append((rank.get(kind, 3), d.name, d))
    except OSError:
        return []
    return [d for _r, _n, d in sorted(out)]


def read_sysfs(root: str = BACKLIGHT) -> int | None:
    for d in backlights(root):
        try:
            mx = int((d / "max_brightness").read_text())
            cur = int((d / "brightness").read_text())
            if mx > 0:
                return round(cur * 100 / mx)
        except (OSError, ValueError):
            continue
    return None


def read_brightnessctl(runner=None, which: Callable = shutil.which) -> int | None:
    if not which("brightnessctl"):
        return None
    rc, out = _run(["brightnessctl", "-m", "-c", "backlight"], runner)
    m = re.search(r",(\d+)%", out)
    return int(m.group(1)) if rc == 0 and m else None


def current(runner=None, which: Callable = shutil.which, root: str = BACKLIGHT) -> int | None:
    v = read_brightnessctl(runner, which)
    return v if v is not None else read_sysfs(root)


def clamp(pct) -> int:
    return max(5, min(100, int(round(float(pct)))))     # never fully black: 5 % lowest


def set_brightnessctl(pct: int, runner=None, which: Callable = shutil.which) -> bool:
    if not which("brightnessctl"):
        return False
    rc, _ = _run(["brightnessctl", "-q", "-c", "backlight", "set", f"{clamp(pct)}%"], runner)
    return rc == 0


def sysfs_helper(device: Path, pct: int) -> str:
    """Shell run as root by pkexec: writes the raw value for pct into one backlight device."""
    d = shlex.quote(str(device))
    return (f"set -e; mx=$(cat {d}/max_brightness); v=$(( mx * {clamp(pct)} / 100 )); [ \"$v\" -lt 1 ] && v=1; "
            f"echo \"$v\" > {d}/brightness")


def set_sysfs(pct: int, runner=None, root: str = BACKLIGHT, which: Callable = shutil.which, root_run: Callable | None = None,
              allow_root: bool = True) -> bool:
    devs = backlights(root)
    if not devs:
        return False
    d = devs[0]
    try:                                        # writable without root (udev rule / group): no password
        mx = int((d / "max_brightness").read_text())
        (d / "brightness").write_text(str(max(1, mx * clamp(pct) // 100)))
        return True
    except (OSError, ValueError):
        pass
    if not allow_root:
        return False
    cmd = ["pkexec", "sh", "-c", sysfs_helper(d, pct)]
    if root_run is not None:
        return root_run(cmd) == 0
    if not which("pkexec"):
        return False
    return _run(cmd, runner, 120)[0] == 0


def outputs(runner=None, which: Callable = shutil.which) -> list[str]:
    if not which("xrandr") or not os.environ.get("DISPLAY"):
        return []
    rc, out = _run(["xrandr", "--query"], runner)
    return [l.split()[0] for l in out.splitlines() if " connected" in l] if rc == 0 else []


def set_xrandr(pct: int, runner=None, which: Callable = shutil.which) -> bool:
    outs = outputs(runner, which)
    ok = False
    for o in outs[:1]:               # the built-in panel is listed first on laptops
        ok = _run(["xrandr", "--output", o, "--brightness", f"{clamp(pct) / 100:.2f}"], runner)[0] == 0
    return ok


def set_level(pct, runner=None, which: Callable = shutil.which, root: str = BACKLIGHT, root_run: Callable | None = None,
              allow_root: bool = True) -> tuple[bool, str]:
    """(ok, which way worked). Tries brightnessctl, /sys (pkexec if needed), then xrandr."""
    pct = clamp(pct)
    if set_brightnessctl(pct, runner, which):
        return True, "brightnessctl"
    if set_sysfs(pct, runner, root, which, root_run, allow_root):
        return True, "backlight"
    if set_xrandr(pct, runner, which):
        return True, "xrandr"
    return False, ""


def grub_cmdline(text: str) -> str:
    m = re.search(r'^GRUB_CMDLINE_LINUX_DEFAULT="([^"]*)"', text, re.M)
    return m.group(1) if m else ""


def applied_fix(text: str) -> str:
    m = re.search(r"acpi_backlight=(\w+)", grub_cmdline(text))
    return m.group(1) if m else ""


def next_fix(text: str) -> str:
    cur = applied_fix(text)
    if not cur:
        return FIX_ORDER[0]
    i = FIX_ORDER.index(cur) if cur in FIX_ORDER else len(FIX_ORDER) - 1
    return FIX_ORDER[i + 1] if i + 1 < len(FIX_ORDER) else ""


def fix_script(mode: str, grub: str = GRUB, backup: str = BACKUP, update: str = "update-grub") -> str:
    """Root shell: back up grub (first time only), put acpi_backlight=<mode> in GRUB_CMDLINE_LINUX_DEFAULT, update-grub."""
    assert mode in FIX_ORDER
    g, b = shlex.quote(grub), shlex.quote(backup)
    return (f"set -e; [ -f {b} ] || cp -a {g} {b}; "
            f"sed -i -E '/^GRUB_CMDLINE_LINUX_DEFAULT=/ {{ s/ ?acpi_backlight=[a-z_]+//g; s/=\"/=\"acpi_backlight={mode} /; s/ \"/\"/ }}' {g}; "
            f"grep -q 'acpi_backlight={mode}' {g}; {update}")


def restore_script(grub: str = GRUB, backup: str = BACKUP, update: str = "update-grub") -> str:
    g, b = shlex.quote(grub), shlex.quote(backup)
    return f"set -e; [ -f {b} ]; cp -a {b} {g}; rm -f {b}; {update}"
