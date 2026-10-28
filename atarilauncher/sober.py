"""Roblox on Linux goes through Sober (Flatpak org.vinegarhq.Sober). Its only supported install route is Flathub:
    flatpak install flathub org.vinegarhq.Sober        (verified at sober.vinegarhq.org and flathub.org, 2026)
There is NO official .flatpak bundle or .flatpakref to download - a file saved from some web page and opened by hand in
Linux Mint's installer gives "Invalid Bundle". Atari installs it from Flathub itself (per user, --noninteractive).

Sober's stated needs: x86-64 CPU with SSE4.1 (SSE4.2 recommended), Linux kernel 5.11+, OpenGL ES 3.0; Vulkan 1.1 is
recommended (Sober falls back to OpenGL without it). The Flatpak brings its own Mesa, so host Vulkan drivers are not
strictly required - but if the computer has none at all, Atari offers the mesa-vulkan-drivers package (pkexec) as a
best-effort extra, because it makes Roblox much smoother on Intel graphics (e.g. the Dell Latitude 5420's Iris Xe).
Everything here reads from injectable inputs so tests do not need the real machine."""
from __future__ import annotations

import glob
import platform
import re
import shutil
from dataclasses import dataclass
from typing import Callable

FLATPAK_ID = "org.vinegarhq.Sober"
MIN_KERNEL = (5, 11)

FIRST_RUN_NOTE = ("First start: Sober opens a window that offers to download Roblox itself (a few hundred MB, needs internet) - "
                  "leave \"Automatic\" ticked and press Install. Then sign in with your own Roblox account (a mouse or touch "
                  "screen helps on the sign-in page). Later starts open Roblox straight away.")
INVALID_BUNDLE_TEXT = ("Linux Mint says \"Invalid Bundle\" when you open a downloaded .flatpak or .flatpakref file by hand: Sober has no "
                       "official file to download - it only comes from Flathub. Do not open downloaded files; press Install on the Roblox "
                       "tile in Atari instead (Atari installs it from Flathub for you).")


@dataclass
class Check:
    id: str
    ok: bool
    fatal: bool       # True = Sober cannot work on this computer
    text: str         # plain English


def _kernel(release: str) -> tuple:
    m = re.match(r"(\d+)\.(\d+)", release or "")
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def vulkan_present(which: Callable = shutil.which, icd_files: Callable[[], list] | None = None) -> bool:
    """A Vulkan driver is installed on the host (an ICD file; vulkaninfo alone only proves the tool)."""
    files = icd_files() if icd_files else (glob.glob("/usr/share/vulkan/icd.d/*.json") + glob.glob("/etc/vulkan/icd.d/*.json"))
    return bool(files)


def preflight(machine: str | None = None, release: str | None = None, cpuinfo: str | None = None,
              which: Callable = shutil.which, icd_files: Callable[[], list] | None = None) -> list[Check]:
    machine = machine if machine is not None else platform.machine()
    release = release if release is not None else platform.release()
    if cpuinfo is None:
        try:
            cpuinfo = open("/proc/cpuinfo", encoding="utf-8", errors="replace").read()
        except OSError:
            cpuinfo = ""
    out: list[Check] = []
    if machine not in ("x86_64", "amd64", "AMD64"):
        out.append(Check("cpu", False, True, f"Sober only runs on x86-64 (Intel/AMD) computers; this one reports \"{machine}\"."))
        return out
    out.append(Check("cpu", True, False, "x86-64 processor: OK."))
    if cpuinfo:
        flags = " ".join(re.findall(r"^flags\s*:(.*)$", cpuinfo, re.M)[:1])
        if "sse4_1" not in flags.split():
            out.append(Check("sse", False, True, "This processor is too old for Roblox (it needs SSE4.1; processors from 2008-2013 onwards have it)."))
        elif "sse4_2" not in flags.split():
            out.append(Check("sse", True, False, "This processor has SSE4.1 only: Roblox will run but slower."))
        else:
            out.append(Check("sse", True, False, "Processor features (SSE4.2): OK."))
    k = _kernel(release)
    if k < MIN_KERNEL:
        out.append(Check("kernel", False, True, f"Linux kernel {release} is too old - Sober needs 5.11 or newer. Update Linux Mint (Update Manager) and restart."))
    else:
        out.append(Check("kernel", True, False, f"Linux kernel {release}: OK."))
    if vulkan_present(which, icd_files):
        out.append(Check("vulkan", True, False, "Graphics (Vulkan): OK."))
    else:
        out.append(Check("vulkan", False, False, "No Vulkan graphics driver found on this computer. Roblox can still start (Sober falls back to OpenGL) "
                                                  "but is smoother with the mesa-vulkan-drivers package, which Atari can install."))
    return out


def blocking(checks: list[Check]) -> Check | None:
    return next((c for c in checks if c.fatal and not c.ok), None)


def needs_vulkan_driver(checks: list[Check]) -> bool:
    return any(c.id == "vulkan" and not c.ok for c in checks)
