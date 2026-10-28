"""Install the emulators Code can use - in plain English, one step at a time, never stopping at the first problem.

    scripts/install-everything.sh              install everything that is missing (safe to run again and again)
    scripts/install-everything.sh --list       show what is installed
    scripts/install-everything.sh duckstation pcsx2     install only these (ids from --list)

What it does:
  1. makes sure Flatpak exists (only this step may use apt + your password) and adds the Flathub store for you
  2. installs each emulator from Flathub (per-user, no sudo) - skipping what is already installed
  3. downloads the RetroArch cores from libretro's official build server (the same place RetroArch's own
     "Core Downloader" uses) into RetroArch's own cores folder
  4. offers to install the few emulators that exist only as apt packages (mednafen, mupen64plus) - asks first
BIOS / firmware / keys / games are never downloaded or included: use "Add BIOS files" in Code with your own files.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import apps, covers, windows
from .emulators import EMUS, NOTES, SYSTEMS, find_emu, flatpak_installed

FLATHUB_REPO = "https://dl.flathub.org/repo/flathub.flatpakrepo"
CORES_URL = "https://buildbot.libretro.com/nightly/linux/x86_64/latest/{core}.so.zip"
RETROARCH_ID = "org.libretro.RetroArch"
# Not installed by default (other emulators already cover those consoles); still installable by name.
SKIP_BY_DEFAULT = {"desmume"}
# "Install essentials only": RetroArch (with every core, which also covers PlayStation 1, Genesis, SNES, ...) and the
# stand-alone emulators most people want. Everything else is one press away later.
ESSENTIAL_IDS = ("retroarch", "pcsx2", "dolphin", "ppsspp", "melonds", "mgba", "flycast")
GITHUB_API = "https://api.github.com"

# lines flatpak prints about end-of-life apps / runtimes: true, but just noise to someone who wants to play
_EOL_NOISE = ("end-of-life", "end of life", "no longer maintained", "no longer supported", "applications using this runtime",
              "masked", "is eol")


@dataclass
class Outcome:
    name: str
    status: str            # installed | already | failed | skipped
    detail: str = ""


def used_emulators() -> list:
    used = {eid for s in SYSTEMS for eid in s.emus}
    return [e for e in EMUS.values() if e.id in used]


def essential_selection() -> list:
    by_id = {e.id: e for e in used_emulators()}
    return [by_id[i] for i in ESSENTIAL_IDS if i in by_id]


def default_selection() -> list:
    """Everything: the emulators for the supported consoles plus the PC apps / stores (Roblox, Heroic, Lutris, ...)."""
    return ([e for e in used_emulators() if e.id not in SKIP_BY_DEFAULT] + list(apps.APP_DEFS) + list(apps.HELPERS))


def wanted_cores() -> list[str]:
    seen: list[str] = []
    for s in SYSTEMS:
        if s.core and s.core not in seen:
            seen.append(s.core)
    return seen


def cores_dir(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".var/app" / RETROARCH_ID / "config/retroarch/cores"


# ------------------------------------------------------------------ small helpers
def _run(cmd: list[str], quiet: bool = False) -> int:
    try:
        return subprocess.run(cmd, stdout=subprocess.DEVNULL if quiet else None,
                              stderr=subprocess.DEVNULL if quiet else None).returncode
    except OSError:
        return 127


def is_noise(line: str) -> bool:
    low = line.lower()
    return any(w in low for w in _EOL_NOISE)


def _run_friendly(cmd: list[str], out: Callable[[str], None]) -> int:
    """Run a command and show its output without the end-of-life chatter and without a screenful of progress-bar redraws."""
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, bufsize=0)
    except OSError:
        return 127
    buf = b""
    last = ""
    while True:
        chunk = os.read(proc.stdout.fileno(), 4096)
        if not chunk:
            break
        buf += chunk
        *lines, buf = buf.split(b"\n")
        for raw in lines:
            line = raw.decode(errors="replace").split("\r")[-1].strip()
            if not line or is_noise(line) or line == last:
                continue
            last = line
            out("      " + line[:160])
    proc.stdout.close()
    return proc.wait()


def flatpak_has(app_id: str) -> bool:
    """Installed (per-user or system-wide)? Asks flatpak itself."""
    return _run(["flatpak", "info", app_id], quiet=True) == 0


def _yes(question: str, assume_yes: bool, ask: Callable[[str], str]) -> bool:
    if assume_yes:
        return True
    try:
        return ask(question + " [Y/n] ").strip().lower() in ("", "y", "yes", "j", "ja", "s", "si", "o", "oui")
    except EOFError:
        return False


# ------------------------------------------------------------------ steps
def ensure_flatpak(out: Callable[[str], None], ask, assume_yes: bool) -> bool:
    if shutil.which("flatpak"):
        return True
    out("Flatpak (the program that installs most emulators) is not on this computer yet.")
    if shutil.which("apt-get") and shutil.which("sudo"):
        if _yes("Install Flatpak now? It needs your password (it is asked by sudo, not by Code).", assume_yes, ask):
            out("Installing Flatpak with apt ...")
            _run(["sudo", "apt-get", "install", "-y", "flatpak"])
            if shutil.which("flatpak"):
                out("Flatpak is installed.")
                return True
            out("Flatpak could not be installed.")
        else:
            out("OK, skipping Flatpak.")
    else:
        out("Install it with your software manager (package name: flatpak), then run this again.")
    return False


def ensure_flathub(out: Callable[[str], None]) -> bool:
    out("Adding the Flathub store (the place emulators come from) for your account if it is missing ...")
    rc = _run(["flatpak", "remote-add", "--if-not-exists", "--user", "flathub", FLATHUB_REPO])
    if rc != 0:
        out("Could not add Flathub. Are you connected to the internet?")
        return False
    return True


def install_flatpak(emu, out: Callable[[str], None], retries: int = 2, wait: float = 3.0) -> Outcome:
    if flatpak_has(emu.flatpak):
        out("   already installed - nothing to do")
        return Outcome(emu.name, "already")
    for attempt in range(1, retries + 1):
        rc = _run_friendly(["flatpak", "install", "--user", "-y", "--noninteractive", "flathub", emu.flatpak], out)
        if rc == 0 and flatpak_has(emu.flatpak):
            out("   installed")
            from . import sober
            if emu.flatpak == sober.FLATPAK_ID:       # Sober's "Permission Update Required": give it now, user level, Sober only
                out("   giving Sober the permission it asks for:  " + sober.OVERRIDE_COMMAND)
                _run_friendly(list(sober.OVERRIDE_ARGS), out)
            return Outcome(emu.name, "installed")
        if attempt < retries:
            out(f"   that did not work (code {rc}); trying once more ...")
            time.sleep(wait)
    out("   FAILED - continuing with the next one")
    return Outcome(emu.name, "failed", f"flatpak install flathub {emu.flatpak} did not finish")


def install_cores(out: Callable[[str], None], home: Path | None = None, http: covers.Http | None = None,
                  names: list[str] | None = None) -> list[Outcome]:
    """Download RetroArch cores (official libretro build server) for the Flatpak RetroArch."""
    dest = cores_dir(home)
    http = http or covers.Http(timeout=60, retries=3, pause=0.2, backoff=2.0)
    base = os.environ.get("ATARI_CORES_URL") or CORES_URL
    results: list[Outcome] = []
    todo = names if names is not None else wanted_cores()
    for i, core in enumerate(todo, 1):
        label = core.replace("_libretro", "")
        target = dest / f"{core}.so"
        if target.is_file() and target.stat().st_size > 0:
            results.append(Outcome(f"core {label}", "already"))
            out(f"   [{i}/{len(todo)}] {label}: already there")
            continue
        out(f"   [{i}/{len(todo)}] {label}: downloading ...")
        try:
            data = http.get(base.format(core=core), max_bytes=300 * 1024 * 1024, timeout=90)
            if not data:
                raise ValueError("not found on the server")
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                member = next((n for n in zf.namelist() if n.endswith(".so")), None)
                if not member:
                    raise ValueError("the download had no core inside")
                dest.mkdir(parents=True, exist_ok=True)
                tmp = target.with_name(target.name + ".part")
                tmp.write_bytes(zf.read(member))
                os.replace(tmp, target)
            results.append(Outcome(f"core {label}", "installed"))
        except (covers.Offline, ValueError, zipfile.BadZipFile, OSError) as exc:
            results.append(Outcome(f"core {label}", "failed", str(exc)))
            out(f"      failed: {exc}")
            if isinstance(exc, covers.Offline):
                # one retry-worth of patience is already built into Http; give up quickly when offline
                if sum(1 for r in results[-2:] if r.status == "failed") >= 2:
                    out("   The connection seems to be down - skipping the remaining cores.")
                    for rest in todo[i:]:
                        results.append(Outcome(f"core {rest.replace('_libretro', '')}", "failed", "no connection"))
                    break
    return results


UMU_API = "https://api.github.com/repos/Open-Wine-Components/umu-launcher/releases/latest"


def install_umu(out: Callable[[str], None], home: Path | None = None, http: covers.Http | None = None) -> Outcome:
    """umu-launcher (runs Windows games with Proton): the official 'zipapp' from its GitHub release, checked against the
    SHA256 GitHub publishes for it, put in ~/.local/share/umu-launcher with an `umu-run` link in ~/.local/bin."""
    home = home or Path.home()
    name = "umu-launcher"
    if windows.umu_path(home):
        out("   already installed - nothing to do")
        return Outcome(name, "already")
    api = os.environ.get("ATARI_UMU_API") or UMU_API
    http = http or covers.Http(timeout=60, retries=3, pause=0.2, backoff=2.0)
    try:
        meta = http.get(api, max_bytes=3_000_000)
        rel = json.loads(meta.decode("utf-8", "replace")) if meta else {}
        asset = next((a for a in rel.get("assets", []) if str(a.get("name", "")).endswith("-zipapp.tar")), None)
        if not asset:
            raise ValueError("no download found in the latest release")
        digest = str(asset.get("digest") or "")
        if not digest.startswith("sha256:"):
            raise ValueError("the release has no checksum, so it was not installed")
        data = http.get(asset["browser_download_url"], max_bytes=100 * 1024 * 1024, timeout=120)
        if not data:
            raise ValueError("the download was not found")
        import hashlib
        if hashlib.sha256(data).hexdigest() != digest.split(":", 1)[1].lower():
            raise ValueError("the download did not match its checksum, so it was not installed")
        with tarfile.open(fileobj=io.BytesIO(data)) as tf:
            member = next((m for m in tf.getmembers() if m.isreg() and m.name.endswith("umu-run")), None)
            if member is None:
                raise ValueError("the download had no umu-run inside")
            dest = home / ".local/share/umu-launcher"
            dest.mkdir(parents=True, exist_ok=True)
            target = dest / "umu-run"
            target.write_bytes(tf.extractfile(member).read())
            target.chmod(0o755)
        link = home / ".local/bin/umu-run"
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(target)
        out("   installed (the first Windows game you start will download Proton once - that takes a few minutes)")
        return Outcome(name, "installed")
    except (covers.Offline, ValueError, OSError, tarfile.TarError, KeyError) as exc:
        out(f"   FAILED: {exc} - continuing")
        return Outcome(name, "failed", str(exc))


def install_appimage(emu, out: Callable[[str], None], home: Path | None = None, http: covers.Http | None = None) -> Outcome:
    """An emulator that is only maintained as a GitHub AppImage (DuckStation: its Flathub package is end-of-life).
    Downloads the official file for your user into ~/.local/share/atari/emulators, checks it against the SHA256 that GitHub
    publishes for the release asset, and makes it executable. Nothing else is touched."""
    from .emulators import appimage_dir, appimage_path
    repo, tag, fname = emu.appimage.split("|")
    if appimage_path(emu, home):
        out("   already installed - nothing to do")
        return Outcome(emu.name, "already")
    api = os.environ.get("ATARI_GITHUB_API") or GITHUB_API
    http = http or covers.Http(timeout=60, retries=3, pause=0.2, backoff=2.0)
    try:
        meta = http.get(f"{api}/repos/{repo}/releases/tags/{tag}", max_bytes=5_000_000)
        rel = json.loads(meta.decode("utf-8", "replace")) if meta else {}
        asset = next((a for a in rel.get("assets", []) if a.get("name") == fname), None)
        if not asset:
            raise ValueError("the official download was not found on GitHub")
        digest = str(asset.get("digest") or "")
        if not digest.startswith("sha256:"):
            raise ValueError("GitHub lists no checksum for it, so it was not installed")
        out(f"   downloading {fname} ({int(asset.get('size') or 0) // (1024 * 1024)} MB) ...")
        data = http.get(asset["browser_download_url"], max_bytes=400 * 1024 * 1024, timeout=300)
        if not data:
            raise ValueError("the download was not found")
        import hashlib
        if hashlib.sha256(data).hexdigest() != digest.split(":", 1)[1].lower():
            raise ValueError("the download did not match its checksum, so it was not installed")
        dest = appimage_dir(home)
        dest.mkdir(parents=True, exist_ok=True)
        target = dest / fname
        tmp = target.with_name(fname + ".part")
        tmp.write_bytes(data)
        tmp.chmod(0o755)
        os.replace(tmp, target)
        out("   installed (checksum verified)")
        return Outcome(emu.name, "installed")
    except (covers.Offline, ValueError, OSError, KeyError) as exc:
        out(f"   FAILED: {exc} - continuing")
        return Outcome(emu.name, "failed", str(exc))


def apt_only_emulators() -> list:
    return [e for e in used_emulators() if not e.flatpak and e.apt]


def install_apt(emus: list, out: Callable[[str], None], ask, assume_yes: bool) -> list[Outcome]:
    todo = [e for e in emus if not any(shutil.which(x) for x in e.exes)]
    results = [Outcome(e.name, "already") for e in emus if e not in todo]
    if not todo:
        return results
    pk = [e.apt for e in todo]
    out("These emulators are not on Flathub; they come from your system's own software list (apt): "
        + ", ".join(e.name for e in todo))
    if not (shutil.which("apt-get") and shutil.which("sudo")):
        out("   apt is not available here - skipping.")
        return results + [Outcome(e.name, "skipped", "apt not available") for e in todo]
    if not _yes("Install them now? It needs your password (asked by sudo, not by Code).", assume_yes, ask):
        return results + [Outcome(e.name, "skipped", "you chose to skip") for e in todo]
    rc = _run(["sudo", "apt-get", "install", "-y", *pk])
    for e in todo:
        ok = rc == 0 and any(shutil.which(x) for x in e.exes)
        results.append(Outcome(e.name, "installed" if ok else "failed", "" if ok else f"sudo apt install {e.apt}"))
    return results


# ------------------------------------------------------------------ the whole run
def summarize(results: list[Outcome], out: Callable[[str], None]) -> int:
    def names(status):
        return [r for r in results if r.status == status]
    out("")
    out("=" * 60)
    out("SUMMARY")
    out("=" * 60)
    inst, already, failed, skipped = names("installed"), names("already"), names("failed"), names("skipped")
    if inst:
        out(f"Installed now ({len(inst)}): " + ", ".join(r.name for r in inst))
    if already:
        out(f"Already installed ({len(already)}): " + ", ".join(r.name for r in already))
    if skipped:
        out(f"Skipped ({len(skipped)}): " + ", ".join(f"{r.name} ({r.detail})" for r in skipped))
    if failed:
        out(f"DID NOT INSTALL ({len(failed)}):")
        for r in failed:
            out(f"   - {r.name}: {r.detail or 'unknown problem'}")
        out("Run this again later - it only tries what is still missing.")
    if not (inst or already or failed or skipped):
        out("Nothing to do.")
    out("")
    if any(r.name == "Roblox" for r in results):
        out("Roblox: runs through Sober, an UNOFFICIAL community app (not made by Roblox). It may break after a Roblox")
        out("update (run this again or 'flatpak update'). Open Roblox from Code's PC Apps and sign in to your own account.")
    out("Next: open Code > Settings > Emulators to see what is ready. Some consoles also need a BIOS file")
    out("from your own console - use \"Add BIOS files\" in Code (Code never downloads BIOS files or games).")
    return 1 if failed else 0


def run_install(selection: list, *, out: Callable[[str], None] = print, ask: Callable[[str], str] = input,
                assume_yes: bool = False, use_apt: bool = True, with_cores: bool = True,
                home: Path | None = None, title: str = "install everything (emulators and PC apps)") -> int:
    results: list[Outcome] = []
    flatpak_ok_needed = any(e.flatpak for e in selection)
    fl = [e for e in selection if e.flatpak]
    img = [e for e in selection if not e.flatpak and getattr(e, "appimage", "")]
    apt = [e for e in selection if not e.flatpak and not getattr(e, "appimage", "") and e.apt]
    other = [e for e in selection if not e.flatpak and not getattr(e, "appimage", "") and not e.apt and e.id != "umu"]
    want_umu = any(e.id == "umu" for e in selection)
    ra_selected = any(e.id == "retroarch" for e in selection)
    steps = len(fl) + len(img) + len(apt) + int(want_umu) + int(with_cores and ra_selected)
    out(f"Code - {title}")
    out(f"{steps} step{'s' if steps != 1 else ''} to do. " + ("This can take 20 minutes or more - several GB are downloaded. "
        if steps > 8 else "") + "You can run it again at any time; it only does what is still missing.")
    out("(Warnings about old 'end-of-life' packages are hidden - they do not stop anything from working.)")
    out("")
    n = 0

    def step(text: str) -> None:
        nonlocal n
        n += 1
        out("")
        out(f"Step {n} of {steps} - {text}")

    flatpak_ok = (ensure_flatpak(out, ask, assume_yes) and ensure_flathub(out)) if flatpak_ok_needed else False
    if flatpak_ok:
        for e in fl:
            step(f"{e.name}")
            results.append(install_flatpak(e, out))
    else:
        for e in fl:
            n += 1
            results.append(Outcome(e.name, "failed", "Flatpak is not available"))
    for e in img:
        step(f"{e.name} (official download from GitHub)")
        results.append(install_appimage(e, out, home))
    if with_cores and ra_selected:
        step("RetroArch cores (one per console, from libretro's official server)")
        if flatpak_ok and flatpak_has(RETROARCH_ID):
            results.extend(install_cores(out, home))
        else:
            out("Skipping RetroArch cores because RetroArch is not installed.")
    if want_umu:
        step("umu-launcher (starts Windows games with Proton)")
        results.append(install_umu(out, home))
    if use_apt and apt:
        step("Programs from your system's software list (apt): " + ", ".join(e.name for e in apt))
        results.extend(install_apt(apt, out, ask, assume_yes))
    for e in other:
        results.append(Outcome(e.name, "skipped", "no package known - see its website"))
    return summarize(results, out)


def list_status(out: Callable[[str], None] = print) -> None:
    from .config import default_config
    cfg = default_config()
    out(f"{'id':12} {'emulator':40} {'status':22} installed from")
    for a in apps.APP_DEFS:
        ok, _t = apps.app_status(cfg, a)
        out(f"{a.id:12} {a.title[:40]:40} {'installed' if ok else '-':22} Flathub: {a.flatpak}")
    for h in apps.HELPERS:
        if h.id == "umu":
            have = windows.umu_path() != ""
        else:
            have = any(shutil.which(x) for x in h.exes) or bool(h.flatpak and flatpak_installed(h.flatpak))
        src = f"Flathub: {h.flatpak}" if h.flatpak else (f"apt: {h.apt}" if h.apt else "GitHub release (checked)")
        out(f"{h.id:12} {h.title[:40]:40} {'installed' if have else '-':22} {src}")
    for e in used_emulators():
        cmd, how = find_emu(cfg, e.id)
        status = {"native": "installed", "flatpak": "installed (Flatpak)", "custom": "custom command"}.get(how, "-")
        src = (("Flathub: " + e.flatpak) if e.flatpak else (("GitHub AppImage: " + e.appimage.split("|")[0]) if e.appimage else
               (("apt: " + e.apt) if e.apt else "see its website")))
        out(f"{e.id:12} {e.name[:40]:40} {status:22} {src}")
    for name, text in NOTES:
        out(f"\n{name}: {text}")


# ------------------------------------------------------------------ open it in a terminal (Settings > Emulators)
TERMINALS = [  # (program, arguments that put the command after them)
    ("x-terminal-emulator", ["-e"]), ("gnome-terminal", ["--"]), ("xfce4-terminal", ["-x"]),
    ("mate-terminal", ["-x"]), ("konsole", ["-e"]), ("kitty", []), ("alacritty", ["-e"]),
    ("tilix", ["-e"]), ("xterm", ["-e"]),
]


def installer_script() -> list[str]:
    script = Path(__file__).resolve().parent.parent / "scripts" / "install-everything.sh"
    if script.is_file():
        return ["bash", str(script), "--pause"]
    return [sys.executable, "-m", "atarilauncher.installer", "--pause"]


def terminal_command(cmd: list[str], which: Callable[[str], str | None] = shutil.which) -> list[str] | None:
    for prog, args in TERMINALS:
        path = which(prog)
        if path:
            return [prog, *args, *cmd]
    return None


def open_in_terminal(cmd: list[str] | None = None, which: Callable[[str], str | None] = shutil.which,
                     popen=subprocess.Popen) -> tuple[bool, str]:
    """Start the installer in a terminal window. Returns (started, message for the user)."""
    cmd = cmd or installer_script()
    full = terminal_command(cmd, which)
    if full is None:
        return False, ("Code could not find a terminal program. Open one yourself and run:  atari-install-everything")
    env = {k: v for k, v in os.environ.items()
           if k not in ("QT_QPA_PLATFORM", "QT_PLUGIN_PATH", "QML_IMPORT_PATH", "QML2_IMPORT_PATH", "PYTHONHOME")}
    try:
        popen(full, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
              start_new_session=True)
    except OSError as exc:
        return False, f"Could not open a terminal: {exc}"
    return True, "A terminal window opened to install the emulators. Come back here when it says it is finished."


# ------------------------------------------------------------------ command line
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="install-emulators", description=(
        "Install the emulators Code can use (Flatpak, per-user; plus RetroArch cores). Safe to run again. "
        "Code never includes BIOS/firmware/keys/games - bring your own and use 'Add BIOS files' in Code."))
    ap.add_argument("names", nargs="*", help="emulator ids to install (default: all; see --list)")
    ap.add_argument("--list", action="store_true", help="show emulators and whether each is installed")
    ap.add_argument("--essentials", action="store_true",
                    help="install only the essentials: RetroArch + cores, PCSX2, Dolphin, PPSSPP, melonDS, mGBA, Flycast")
    ap.add_argument("--all", action="store_true", help="install everything (this is the default without names)")
    ap.add_argument("--yes", "-y", action="store_true", help="do not ask questions (sudo may still ask your password)")
    ap.add_argument("--no-apt", action="store_true", help="do not use apt / sudo at all")
    ap.add_argument("--no-cores", action="store_true", help="do not download RetroArch cores")
    ap.add_argument("--pause", action="store_true", help="wait for Enter at the end (used when opened in a window)")
    ap.add_argument("--apt", action="store_true", help="only print the apt command for apt-only emulators")
    args = ap.parse_args(argv)
    if args.list:
        list_status()
        return 0
    if args.apt:
        print("sudo apt install " + " ".join(sorted({e.apt for e in apt_only_emulators()})))
        return 0
    if args.names and not args.all:
        sel = []
        for n in args.names:
            if n in apps.BY_ID:
                sel.append(apps.BY_ID[n])
            elif n in {h.id: h for h in apps.HELPERS}:
                sel.append({h.id: h for h in apps.HELPERS}[n])
            elif n in EMUS:
                sel.append(EMUS[n])
            else:
                print(f"Unknown emulator or app '{n}'. Run with --list.", file=sys.stderr)
                return 2
    elif args.essentials:
        sel = essential_selection()
    else:
        sel = default_selection()
    rc = 1
    try:
        rc = run_install(sel, assume_yes=args.yes, use_apt=not args.no_apt, with_cores=not args.no_cores,
                         title="install the essentials" if args.essentials and not args.names else
                         "install everything (emulators and PC apps)")
    except KeyboardInterrupt:
        print("\nStopped. Run it again any time - it continues where it left off.")
    finally:
        if args.pause:
            try:
                input("\nPress Enter to close this window ...")
            except (EOFError, KeyboardInterrupt):
                pass
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
