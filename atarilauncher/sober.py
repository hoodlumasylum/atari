"""Roblox on Linux goes through Sober (Flatpak org.vinegarhq.Sober). Its only supported install route is Flathub:
    flatpak install flathub org.vinegarhq.Sober        (verified at sober.vinegarhq.org and flathub.org, 2026)
There is NO official .flatpak bundle or .flatpakref to download - a file saved from some web page and opened by hand in
Linux Mint's installer gives "Invalid Bundle". CodeAque installs it from Flathub itself (per user, --noninteractive).

Sober's stated needs: x86-64 CPU with SSE4.1 (SSE4.2 recommended), Linux kernel 5.11+, OpenGL ES 3.0; Vulkan 1.1 is
recommended (Sober falls back to OpenGL without it). The Flatpak brings its own Mesa, so host Vulkan drivers are not
strictly required - but if the computer has none at all, CodeAque offers the mesa-vulkan-drivers package (pkexec) as a
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
                       "tile in CodeAque instead (CodeAque installs it from Flathub for you).")


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
                                                  "but is smoother with the mesa-vulkan-drivers package, which CodeAque can install."))
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
# APK by hand. That is NOT something CodeAque or the user did wrong, and it is not "Roblox dropped x86_64". Causes seen:
#   * Sober's update service was broken for a day or two (28-31 July 2026; Cloudflare error 1101) - it was repaired on
#     the server side, with no new Sober version needed, and Sober then downloaded the app by itself again;
#   * the network / ISP / DNS blocks Google Play's API or Sober's server (Sober's docs: use another DNS such as
#     Cloudflare 1.1.1.1 or Mullvad, or a VPN);
#   * a very old Linux (one Ubuntu 22.04 user only got it working after moving to 24.04).
# What Sober's docs recommend: check the internet, change DNS / VPN, `flatpak update`, try again later. The manual route
# needs the exact Roblox version as a base APK plus the x86_64 split from "a trusted source" - Roblox publishes no Linux
# APK and CodeAque never downloads or bundles one. So when the cause is Sober's server or the network, CodeAque cannot
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
               "and press Roblox again - CodeAque already updates Sober and retries once for you; 2) if it keeps happening, an "
               "adult can set the computer's DNS to 1.1.1.1 (Cloudflare) in Network settings, or use a VPN, because some "
               "internet providers block the Google service Sober uses; 3) Options > Fix my game > Roblox has an \"Update "
               "Sober and test the connection\" button. CodeAque cannot download Roblox's app for you: Roblox does not offer a "
               "Linux file and CodeAque never fetches one from unofficial sites. Picking a file by hand in that window only "
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
            + ("CodeAque updated Sober and tried again, but it still failed. " if retried else "")
            + explain(checks) + " The next screen has a Run fix button and the log paths.")


# ------------------------------------------------------------------ "Permission Update Required"
# Newer Sober builds show a "Permission Update Required" window with this exact command (user level, only for Sober):
OVERRIDE_ARGS = ["flatpak", "override", "--user", "--filesystem=xdg-run/app/com.discordapp.Discord:create",
                 "--filesystem=xdg-run/discord-ipc-0", "--device=all", FLATPAK_ID]
OVERRIDE_COMMAND = " ".join(OVERRIDE_ARGS)
OVERRIDE_PLAIN = ("Sober asks for two extra permissions: to use all the computer's devices (controllers, graphics) and to reach Discord's "
                  "chat link if Discord is running. CodeAque gives them with this one command, for your user only and for Sober only "
                  "(nothing else changes, no password): " + OVERRIDE_COMMAND)
PERMISSION_MARKERS = ("permission update required", "flatpak override", "--device=all", "xdg-run/discord-ipc")


def needs_permission(text: str) -> bool:
    low = (text or "").lower()
    return any(m in low for m in PERMISSION_MARKERS)


def permission_state(since: float = 0.0, home: str | None = None) -> bool:
    """Did the newest Sober log written at or after `since` ask for the permission update?"""
    for f in log_candidates(home)[:3]:
        if _mtime(f) >= since - 2:
            try:
                with open(f, encoding="utf-8", errors="replace") as fh:
                    return needs_permission(fh.read()[-200000:])
            except OSError:
                continue
        break
    return False


def override_applied(run: Callable | None = None) -> bool:
    """Has the override already been given to Sober? (flatpak override --user --show)"""
    import subprocess
    run = run or subprocess.run
    try:
        r = run(["flatpak", "override", "--user", "--show", FLATPAK_ID], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    if r.returncode != 0:
        return False
    out = r.stdout or ""
    return all(tok in out for tok in ("xdg-run/app/com.discordapp.Discord", "xdg-run/discord-ipc-0", "all"))


def apply_override(run: Callable | None = None) -> tuple[bool, str]:
    """Run exactly OVERRIDE_ARGS (user level, Sober only). Returns (ok, output tail)."""
    import subprocess
    run = run or subprocess.run
    try:
        r = run(OVERRIDE_ARGS, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    return r.returncode == 0, ((r.stdout or "") + (r.stderr or ""))[-400:]


# ------------------------------------------------------------------ the "Roblox fix" screen
# What Sober's own docs (vinegarhq.org/Sober/Troubleshooting) and its issue tracker say, checked 2026-10-28:
#  * "Automatic download isn't working ... falls back to manual install": the ISP / DNS blocks Google Play's API (what Sober downloads
#    Roblox through), or the internet is down, or the API is down -> VPN or DNS like Cloudflare 1.1.1.1 / Mullvad.
#  * July 2026 (issue #2376): Sober's own update service (sober.vinegarhq.org/update) answered HTTP 500 "error code: 1101" for about two
#    days; it recovered with NO new Sober version. Reinstalling Sober did nothing in that case. Only waiting helped.
#  * "Select Application Bundle" does nothing without a working D-Bus session and the desktop portals (issue #1818) - which a
#    CodeAque-only session may lack. A manual bundle must be the exact version named, base APK + x86_64 split, from a source you trust.
#  * The wanted version is in ~/.var/app/org.vinegarhq.Sober/data/sober/state ; logs in .../sober/sober_logs/.
STATE_FILE = "~/.var/app/org.vinegarhq.Sober/data/sober/state"
LATEST_LOG = "~/.var/app/org.vinegarhq.Sober/data/sober/sober_logs/latest.log"
FLATHUB_URL = "https://dl.flathub.org/repo/flathub.flatpakrepo"
MAX_SKEW = 300.0           # seconds the clock may be off before secure connections start to fail


@dataclass
class Step:
    id: str
    title: str
    ok: bool
    detail: str
    changed: bool = False      # this step changed something (e.g. gave Sober the permission it asked for)


def requested_version(home: str | None = None) -> str:
    """The Roblox version Sober says it needs, from its state file ('' when unknown)."""
    import os
    try:
        text = open(os.path.expanduser(STATE_FILE.replace("~", home) if home else STATE_FILE), errors="replace").read()
    except OSError:
        return ""
    m = re.search(r"(\d+\.\d{3}\.\d+)", text)
    return m.group(1) if m else ""


def http_date(url: str = MANIFEST_URL, timeout: float = 6.0) -> float | None:
    """The server's own clock (HTTP Date header) as a Unix time, or None."""
    import urllib.request
    from email.utils import parsedate_to_datetime
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Code-Launcher connection check"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = r.headers.get("Date")
    except Exception as exc:
        d = getattr(getattr(exc, "headers", None), "get", lambda *_: None)("Date")
    try:
        return parsedate_to_datetime(d).timestamp() if d else None
    except (TypeError, ValueError):
        return None


def resolves(host: str) -> bool:
    import socket
    try:
        return bool(socket.getaddrinfo(host, 443))
    except OSError:
        return False


def portal_running(run: Callable | None = None) -> bool:
    import subprocess
    run = run or subprocess.run
    try:
        return run(["pgrep", "-x", "xdg-desktop-portal"], capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def run_fix(run: Callable | None = None, probe: Callable[[str], int] | None = None, now: Callable[[], float] | None = None,
            date_fn: Callable[[], float | None] | None = None, resolve: Callable[[str], bool] | None = None,
            portal: Callable[[], bool] | None = None, home: str | None = None,
            update: Callable[[], tuple[bool, str]] | None = None) -> tuple[list[Step], str]:
    """Do everything that can be done from here, in Sober's documented order. Returns (steps, plain verdict).
    Only touches Flatpak (add the Flathub store for this user if it is missing, then `flatpak update` Sober)."""
    import subprocess
    import time
    run = run or subprocess.run
    now = now or time.time
    steps: list[Step] = []

    def sh(args):
        try:
            r = run(args, capture_output=True, text=True, timeout=60)
            return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()
        except (OSError, subprocess.SubprocessError) as exc:
            return 1, str(exc)

    # 1 Flathub store + where Sober came from
    rc, out = sh(["flatpak", "remotes", "--columns=name"])
    has_flathub = rc == 0 and any(ln.strip().lower() == "flathub" for ln in out.splitlines())
    if rc != 0 and not shutil.which("flatpak"):
        steps.append(Step("flatpak", "Flatpak (the program that installs Sober)", False,
                          "Flatpak is not installed. Use Settings > Emulators > Install emulators and apps."))
        return steps, "Sober needs Flatpak, which is missing. Install it first (Settings > Emulators > Install emulators and apps)."
    if not has_flathub:
        rc2, out2 = sh(["flatpak", "remote-add", "--user", "--if-not-exists", "flathub", FLATHUB_URL])
        steps.append(Step("flathub", "The Flathub store is set up", rc2 == 0,
                          "It was missing, so CodeAque added it for you (only for your user)." if rc2 == 0 else
                          "It was missing and could not be added: " + out2[-160:]))
    else:
        steps.append(Step("flathub", "The Flathub store is set up", True, "Yes."))
    rc, out = sh(["flatpak", "info", "--show-origin", FLATPAK_ID])
    origin = out.strip().splitlines()[-1].strip() if rc == 0 and out.strip() else ""
    if rc != 0:
        steps.append(Step("installed", "Sober is installed", False, "It is not installed. Press Install on the Roblox tile."))
    elif origin and origin.lower() != "flathub":
        steps.append(Step("installed", "Sober came from Flathub", False,
                          f"It came from \"{origin}\". Only the Flathub copy is supported: remove it and press Install on the Roblox tile."))
    else:
        steps.append(Step("installed", "Sober is installed (from Flathub)", True, "Yes."))

    # 2 update (Sober's own advice)
    if rc == 0:
        ok, tail = (update or update_sober)()
        steps.append(Step("update", "Sober is up to date (flatpak update)", ok, "Done." if ok else "It could not update: " + tail[-160:]))

    # 2b the permission Sober asks for ("Permission Update Required"): user level, Sober only
    if rc == 0:
        if override_applied(run):
            steps.append(Step("permissions", "Sober has the permissions it asks for", True, "Yes (already given)."))
        else:
            ok_o, tail_o = apply_override(run)
            steps.append(Step("permissions", "Sober has the permissions it asks for", ok_o,
                              "CodeAque gave them with:  " + OVERRIDE_COMMAND if ok_o else "That command failed: " + tail_o[-160:], changed=ok_o))

    # 3 DNS + internet
    resolve = resolve or resolves
    dns_bad = [h for h in ("sober.vinegarhq.org", "play.googleapis.com") if not resolve(h)]
    steps.append(Step("dns", "The computer can look up Sober's and Google Play's addresses (DNS)", not dns_bad,
                      "Yes." if not dns_bad else "It cannot look up " + " and ".join(dns_bad) +
                      ". Your DNS or provider is blocking them - an adult can set DNS to 1.1.1.1 in Network settings, or use a VPN."))
    checks = service_checks(probe)
    for c in checks:
        steps.append(Step(c.id, "Sober's server is reachable" if c.id == "manifest" else "Google Play (where Sober gets Roblox) is reachable",
                          c.ok, "Yes." if c.ok else c.text))

    # 4 clock
    server = (date_fn or http_date)()
    if server is None:
        steps.append(Step("clock", "The clock is right", True, "Could not compare it (no answer from the server)."))
    else:
        skew = abs(now() - server)
        steps.append(Step("clock", "The clock is right", skew <= MAX_SKEW,
                          "Yes." if skew <= MAX_SKEW else f"The clock is {int(skew // 60)} minutes off. Secure connections fail with a wrong clock: "
                          "switch on automatic date & time in the system settings."))

    # 5 file picker (only matters for the manual route)
    p_ok = (portal or portal_running)()
    steps.append(Step("portal", "The file picker works (needed only to choose a file by hand)", p_ok,
                      "Yes." if p_ok else "No desktop portal is running (common in CodeAque-only mode), so \"Select Application Bundle\" "
                      "may do nothing. You should not need it: let Sober download Roblox itself."))

    # verdict: the first real problem, else the honest "it is Sober's side"
    bad = next((s for s in steps if not s.ok and s.id != "portal"), None)
    if bad is not None:
        verdict = {"dns": "DNS is blocking the download. " + bad.detail, "play": explain(checks), "manifest": explain(checks),
                   "clock": bad.detail}.get(bad.id, bad.detail)
    else:
        v = requested_version(home)
        verdict = ("Everything on this computer looks right" + (f" (Sober wants Roblox {v})" if v else "") + ". Press Roblox again. If it still "
                   "asks for a bundle, the cause is Sober's own download service (in July 2026 it failed for two days and then fixed "
                   "itself) - nothing CodeAque can repair. Try again in a few hours, and ask for help on Sober's support page (vinegarhq.org) "
                   "with the log named below.")
    if any(st.changed for st in steps):
        verdict = ("CodeAque gave Sober the permission it asked for (" + OVERRIDE_COMMAND + ") and will start Roblox again now. " + verdict)
    return steps, verdict
