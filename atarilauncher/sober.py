"""Roblox on Linux goes through Sober (Flatpak org.vinegarhq.Sober). Its only supported install route is Flathub:
    flatpak install flathub org.vinegarhq.Sober        (verified at sober.vinegarhq.org and flathub.org, 2026)
There is NO official .flatpak bundle or .flatpakref to download - a file saved from some web page and opened by hand in
Linux Mint's installer gives "Invalid Bundle". Code installs it from Flathub itself (per user, --noninteractive).

Sober's stated needs: x86-64 CPU with SSE4.1 (SSE4.2 recommended), Linux kernel 5.11+, OpenGL ES 3.0; Vulkan 1.1 is
recommended (Sober falls back to OpenGL without it). The Flatpak brings its own Mesa, so host Vulkan drivers are not
strictly required - but if the computer has none at all, Code offers the mesa-vulkan-drivers package (pkexec) as a
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
                       "tile in Code instead (Code installs it from Flathub for you).")


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
                                                  "but is smoother with the mesa-vulkan-drivers package, which Code can install."))
    return out


def blocking(checks: list[Check]) -> Check | None:
    return next((c for c in checks if c.fatal and not c.ok), None)


def needs_vulkan_driver(checks: list[Check]) -> bool:
    return any(c.id == "vulkan" and not c.ok for c in checks)


# ---------------------------------------------------------------------------------------------------------------
# "Install Roblox - a Roblox Android application bundle (APK) of version x.y.z with x86_64 code is required"
#
# What this screen is (researched Oct 2026: Sober's own Troubleshooting page and the vinegarhq/sober issues
# #2375, #2376, #2384 of July 2026): Sober normally downloads the Roblox Android app itself - through its update service
# (sober.vinegarhq.org) which talks to Google Play. When that download fails twice, Sober falls back to asking for the
# APK by hand. That is NOT something Code or the user did wrong, and it is not "Roblox dropped x86_64". Causes seen:
#   * Sober's update service was broken for a day or two (28-31 July 2026; Cloudflare error 1101) - it was repaired on
#     the server side, with no new Sober version needed, and Sober then downloaded the app by itself again;
#   * the network / ISP / DNS blocks Google Play's API or Sober's server (Sober's docs: use another DNS such as
#     Cloudflare 1.1.1.1 or Mullvad, or a VPN);
#   * a very old Linux (one Ubuntu 22.04 user only got it working after moving to 24.04).
# What Sober's docs recommend: check the internet, change DNS / VPN, `flatpak update`, try again later. The manual route
# needs the exact Roblox version as a base APK plus the x86_64 split from "a trusted source" - Roblox publishes no Linux
# APK and Code never downloads or bundles one. So when the cause is Sober's server or the network, Code cannot
# fix it for you; it updates Sober, checks the connection, retries once and then says exactly that.
MANIFEST_URL = "https://sober.vinegarhq.org/app"
PLAY_URL = "https://play.googleapis.com/"
BUNDLE_MARKERS = ("falling back to manual install", "couldn't install roblox using update service",
                  "provided bundle app version is invalid")
LOG_GLOBS = ("~/.var/app/org.vinegarhq.Sober/data/sober/sober_logs/*.log",
             "~/.var/app/org.vinegarhq.Sober/data/sober/*.log")

BUNDLE_HELP = ("Roblox asks for an \"application bundle (APK)\": that is Sober's screen for when it could not download Roblox "
               "by itself. Nothing is broken on your side and your account is fine. Usually it is a temporary problem with "
               "Sober's download service or with the internet connection / DNS (Sober's server was down for a day in "
               "July 2026 and came back by itself). What to do: 1) close that window, check the internet, wait a few minutes "
               "and press Roblox again - Code already updates Sober and retries once for you; 2) if it keeps happening, an "
               "adult can set the computer's DNS to 1.1.1.1 (Cloudflare) in Network settings, or use a VPN, because some "
               "internet providers block the Google service Sober uses; 3) Options > Fix my game > Roblox has an \"Update "
               "Sober and test the connection\" button. Code cannot download Roblox's app for you: Roblox does not offer a "
               "Linux file and Code never fetches one from unofficial sites. Picking a file by hand in that window only "
               "works with the exact Roblox version it names plus the x86_64 part, from a source you trust - not recommended "
               "for kids.")


def log_candidates(home: str | None = None) -> list[str]:
    import os
    out: list[str] = []
    for pat in LOG_GLOBS:
        p = os.path.expanduser(pat) if home is None else pat.replace("~", home, 1)
        out += glob.glob(p)
    return sorted(set(out), key=lambda f: _mtime(f), reverse=True)


def _mtime(path: str) -> float:
    import os
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def needs_bundle(text: str) -> bool:
    """True when a Sober log shows that its own Roblox download failed and it fell back to the manual APK screen."""
    low = (text or "").lower()
    return any(m in low for m in BUNDLE_MARKERS)


def bundle_state(since: float = 0.0, home: str | None = None) -> bool:
    """Did the newest Sober log written at or after `since` end up on the manual-bundle screen?"""
    for f in log_candidates(home)[:3]:
        if _mtime(f) >= since - 2:
            try:
                with open(f, encoding="utf-8", errors="replace") as fh:
                    text = fh.read()[-200000:]
            except OSError:
                continue
            return needs_bundle(text)
        break
    return False


def probe_url(url: str, timeout: float = 5.0) -> int:
    """HTTP status of a GET (any answer, even 404, means the host is reachable); 0 = cannot reach it."""
    import urllib.error
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Code-Launcher connection check"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return int(r.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except Exception:
        return 0


def service_checks(probe: Callable[[str], int] | None = None) -> list[Check]:
    """Can this computer reach Sober's server and Google Play (what Sober downloads Roblox through)?"""
    probe = probe or probe_url
    m = probe(MANIFEST_URL)
    g = probe(PLAY_URL)
    return [
        Check("manifest", 200 <= m < 400, False,
              "Sober's server is reachable." if 200 <= m < 400 else
              ("Sober's server answered with an error (%d) - it may be having a problem on its side; try again later." % m
               if m else "Cannot reach Sober's server (sober.vinegarhq.org) - check the internet, or the network/DNS is blocking it.")),
        Check("play", g > 0, False,
              "Google Play (where Sober gets Roblox) is reachable." if g else
              "Cannot reach Google Play - the internet or DNS may be blocking it (try DNS 1.1.1.1 or a VPN)."),
    ]


def explain(checks: list[Check]) -> str:
    """One plain-English sentence on the most likely cause, from service_checks()."""
    bad = [c for c in checks if not c.ok]
    if any(c.id == "play" and not c.ok for c in checks) or any(c.id == "manifest" and not c.ok and "Cannot" in c.text for c in checks):
        return ("This computer cannot reach what Sober downloads Roblox from (the internet, your DNS or your provider is "
                "blocking it). Check the internet; an adult can switch the DNS to 1.1.1.1 or use a VPN.")
    if bad:
        return "Sober's server is having a problem on its side. Nothing on this computer is wrong - try again in a few hours."
    return ("The connection looks fine, so Sober's download service is probably down or failing at the moment (it did that for "
            "about a day in July 2026). Try again later; nothing on this computer is wrong.")


def update_command() -> list[str]:
    return ["flatpak", "update", "-y", "--noninteractive", FLATPAK_ID]


def update_sober(run: Callable | None = None, timeout: float = 900) -> tuple[bool, str]:
    """`flatpak update org.vinegarhq.Sober` (Sober's own recommendation). Returns (ok, output tail)."""
    import subprocess
    run = run or subprocess.run
    try:
        r = run(update_command(), capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    return r.returncode == 0, ((r.stdout or "") + (r.stderr or ""))[-600:]


def recovery_note(retried: bool, checks: list[Check]) -> str:
    return ("Roblox could not download itself through Sober (it asked for an \"APK bundle\"). "
            + ("Code updated Sober and tried again, but it still failed. " if retried else "")
            + explain(checks) + " More: Help > \"Roblox asks for an application bundle\".")
