"""Quiet boot ("hide the Mint branding") - an optional extra for Code-only mode. Everything it does can be undone from the same screen.

What turning it ON does (one password window, `pkexec`; nothing else is touched):
  1. /etc/default/grub.d/zz-code-quiet.cfg      GRUB: "quiet splash" and less kernel / systemd text; the boot menu is hidden for a
                                                 2 second window in which Shift (old BIOS) or Esc (UEFI) shows it again - and it is
                                                 NOT hidden when another operating system (Windows, macOS ...) is on the disk
  2. /usr/share/plymouth/themes/code/           a boot-splash theme: black background, the Code logo (code-logo.png) in the middle,
                                                 made the default with update-alternatives (the Mint logo theme stays installed)
  3. /etc/code-boot/quiet-boot                  a note that this is on (and what was changed)
  then `update-grub` and `update-initramfs -u` (the splash is part of the initramfs). If either fails, everything is put back.
Turning it OFF removes exactly those files, takes the Code theme out of update-alternatives (Mint's own splash comes back), and runs
update-grub / update-initramfs again.

Recovery is never removed: the boot menu is one key away (Shift / Esc within 2 s), GRUB still shows by itself after a failed boot
(recordfail), "Advanced options" / recovery mode are untouched, and from a text console (Ctrl+Alt+F2) RECOVERY below undoes it all.
Not done on purpose: LightDM's own (Mint) login screen is not restyled - with Code-only mode's auto-login it is skipped anyway.
Paths are relative to a root so tests can run the scripts in a temporary folder."""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import kiosk
from . import rootauth

RECOVERY = ("To undo quiet boot by hand (Ctrl+Alt+F2, log in): sudo rm -f /etc/default/grub.d/zz-code-quiet.cfg /etc/default/grub.d/90-code-quiet.cfg; "
            "sudo plymouth-set-default-theme \"$(sed -n 's/^previous_theme=//p' /etc/code-boot/quiet-boot)\"; "
            "sudo update-alternatives --remove default.plymouth /usr/share/plymouth/themes/code/code.plymouth; "
            "sudo update-grub && sudo update-initramfs -u && sudo rm -rf /etc/code-boot /usr/share/plymouth/themes/code")
HOW_TO_SHOW_MENU = "To see the boot menu: hold Shift (older BIOS) or tap Esc (UEFI) right when the computer starts."
CMDLINE = "quiet splash loglevel=3 rd.systemd.show_status=false systemd.show_status=false rd.udev.log_level=3 vt.global_cursor_default=0"
OTHER_OS = re.compile(r"menuentry\s+['\"]([^'\"]*(Windows|Microsoft|macOS|Mac OS|Darwin|FreeBSD|OpenBSD)[^'\"]*)['\"]", re.I)


@dataclass
class Layout:
    root: Path = Path("/")
    grub_cfg: str = "etc/default/grub.d/zz-code-quiet.cfg"          # "zz": read after every other grub.d file, so nothing overrides it
    legacy_grub_cfg: str = "etc/default/grub.d/90-code-quiet.cfg"   # written by Code 0.4.2; cleaned up
    plymouth_conf: str = "etc/plymouth/plymouthd.conf"
    theme_dir: str = "usr/share/plymouth/themes/code"
    marker_dir: str = "etc/code-boot"
    marker: str = "etc/code-boot/quiet-boot"
    grub_menu: str = "boot/grub/grub.cfg"

    def p(self, rel: str) -> Path:
        return self.root / rel

    @property
    def files(self) -> list[Path]:
        return [self.p(self.grub_cfg), self.p(self.theme_dir), self.p(self.marker)]


DEFAULT = Layout()


def enabled(layout: Layout = DEFAULT) -> bool:
    return layout.p(layout.marker).is_file()


def disk_filesystems() -> list[str] | None:
    """Filesystem types of every partition (lsblk), or None when that cannot be read."""
    import subprocess
    try:
        p = subprocess.run(["lsblk", "-rno", "FSTYPE"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    return [x.strip().lower() for x in p.stdout.splitlines()] if p.returncode == 0 else None


def boot_menu_systems(layout: Layout = DEFAULT, fstypes: Callable | None = None) -> tuple[list[str], list[str]]:
    """(other systems that are really there, leftover entries). GRUB keeps listing 'Windows Boot Manager' after Windows is deleted
    (os-prober finds the old boot files on the EFI partition), so a Windows entry only counts when a Windows-type partition
    (NTFS / BitLocker) still exists. An unreadable menu counts as 'there' to stay safe."""
    fstypes = fstypes or disk_filesystems
    try:
        text = layout.p(layout.grub_menu).read_text(errors="replace")
    except OSError:
        return (["(the boot menu could not be read)"], []) if layout.p(layout.grub_menu).exists() else ([], [])
    names = sorted({m.group(1) for m in OTHER_OS.finditer(text)})
    windows = [n for n in names if re.search(r"windows|microsoft", n, re.I)]
    others = [n for n in names if n not in windows]
    if not windows:
        return others, []
    types = fstypes()
    if types is None or any(t in ("ntfs", "bitlocker", "ntfs3") for t in types):
        return others + windows, []
    return others, windows


def other_systems(layout: Layout = DEFAULT, fstypes: Callable | None = None) -> list[str]:
    return boot_menu_systems(layout, fstypes)[0]


@dataclass
class Check:
    ok: bool
    fatal: bool
    text: str


def preflight(layout: Layout = DEFAULT, which: Callable = None, logo: Path | None = None, fstypes: Callable | None = None) -> list[Check]:
    import shutil
    which = which or shutil.which
    out: list[Check] = []

    def add(ok: bool, fatal: bool, good: str, bad: str):
        out.append(Check(ok, fatal, good if ok else bad))
    add(bool(rootauth.can_elevate(which)), True, "The password window (pkexec) is available.", "The password window (pkexec) is missing: install the 'policykit-1' package.")
    add(bool(which("update-initramfs")) and layout.p("usr/share/plymouth/themes").is_dir(), True, "Plymouth (the boot splash) is installed.",
        "This computer has no Plymouth boot splash (or no update-initramfs), so the logo cannot be changed here.")
    mods = list(layout.p("usr/lib").glob("**/plymouth/script.so")) if layout.p("usr/lib").is_dir() else []
    add(bool(mods), True, "Plymouth's script module is there.", "Plymouth's script module (script.so) was not found.")
    add(layout.p("etc/alternatives/default.plymouth").exists() or layout.p("usr/share/plymouth/themes/default.plymouth").exists(), True,
        "The boot splash can be switched with update-alternatives (Mint / Ubuntu / Debian).",
        "This computer does not manage its boot splash with update-alternatives, so Code will not touch it.")
    add(bool(logo and logo.is_file()), True, "Code's logo file was found.", "Code's logo file (code-logo.png) was not found - reinstall Code.")
    has_grub = bool(which("update-grub")) and layout.p(layout.grub_menu).exists()
    add(has_grub, False, "GRUB is the boot menu, so its text and menu can be quietened.",
        "GRUB was not found (another boot loader?): only the splash logo is changed, the boot menu is left alone.")
    others, stale = boot_menu_systems(layout, fstypes) if has_grub else ([], [])
    if stale:
        out.append(Check(True, False, "GRUB still lists " + ", ".join(stale) + ", but no Windows disk (NTFS) is left: it is a leftover and does "
                                      "not stop the boot menu from being hidden."))
    add(not others, False, "Only this operating system is on the disk: the boot menu is hidden (Shift / Esc shows it).",
        "Another system is on this disk (" + ", ".join(others) + "): the boot menu stays visible so you can still choose it.")
    return out


def blocked(checks: list[Check]) -> str:
    for c in checks:
        if c.fatal and not c.ok:
            return c.text
    return ""


# ------------------------------------------------------------------ file contents
def render_grub(hide_menu: bool, disable_os_prober: bool = False) -> str:
    lines = ["# Written by Code > Settings > Quiet boot. Remove with Settings > Quiet boot > Turn off."]
    if hide_menu:
        lines += ["GRUB_TIMEOUT_STYLE=hidden", "GRUB_TIMEOUT=2", "GRUB_HIDDEN_TIMEOUT_QUIET=true"]    # Shift / Esc inside these 2 seconds shows the menu
    if disable_os_prober:       # only a leftover "Windows Boot Manager" (no Windows disk) is on the machine: stop GRUB listing it again
        lines += ["GRUB_DISABLE_OS_PROBER=true"]
    lines += [f'GRUB_CMDLINE_LINUX_DEFAULT="$GRUB_CMDLINE_LINUX_DEFAULT {CMDLINE}"', ""]
    return "\n".join(lines)


def render_plymouth(theme_dir: str) -> str:
    return f"""[Plymouth Theme]
Name=Code
Description=Code logo on black
ModuleName=script

[script]
ImageDir={theme_dir}
ScriptFile={theme_dir}/code.script
"""


PLYMOUTH_SCRIPT = """Window.SetBackgroundTopColor(0, 0, 0);
Window.SetBackgroundBottomColor(0, 0, 0);
logo.image = Image("code-logo.png");
size = Math.Min(Window.GetHeight() / 3, logo.image.GetHeight());
scale = size / logo.image.GetHeight();
logo.image = logo.image.Scale(logo.image.GetWidth() * scale, size);
logo.sprite = Sprite(logo.image);
logo.sprite.SetX(Window.GetX() + Window.GetWidth() / 2 - logo.image.GetWidth() / 2);
logo.sprite.SetY(Window.GetY() + Window.GetHeight() / 2 - logo.image.GetHeight() / 2);
logo.sprite.SetOpacity(1);
"""


def _q(p) -> str:
    return shlex.quote(str(p))


def _write(path: str, content: str, mode: str = "644") -> str:
    # separate lines (not &&): under `set -e` a failure in the middle of an && chain would be ignored
    return f"mkdir -p {_q(Path(path).parent)}\nprintf %s {_q(content)} > {_q(path)}\nchmod {mode} {_q(path)}"


STEPS = {          # exit code of the pkexec script -> what was being done (the script puts everything back and ends with this code)
    81: "writing the GRUB setting file", 82: "writing the Code boot-splash theme", 83: "rebuilding the boot menu (update-grub)",
    84: "checking that GRUB took the setting (another file overrides it)", 85: "choosing the Code boot-splash theme",
    86: "rebuilding the boot image (update-initramfs)", 87: "checking that the boot image contains the Code theme", 88: "writing the note that quiet boot is on",
    89: "restoring Mint's boot-splash theme",
}


def enable_script(layout: Layout = DEFAULT, logo: Path | None = None, hide_menu: bool = True, theme_visible_path: str | None = None,
                  grub: bool = True, disable_os_prober: bool = False) -> str:
    """What pkexec runs as root. Any failure puts every file back and ends the script with the exit code of the step that failed (STEPS)."""
    g, lg, t, md, m, gm, pc = (str(layout.p(x)) for x in (layout.grub_cfg, layout.legacy_grub_cfg, layout.theme_dir, layout.marker_dir,
                                                         layout.marker, layout.grub_menu, layout.plymouth_conf))
    shown = theme_visible_path or "/" + layout.theme_dir          # the path Plymouth reads at boot (never the test folder)
    pfile = f"{t}/code.plymouth"
    initrd = str(layout.p("boot/initrd.img-")) + "$(uname -r)"
    undo = (f"rm -f {_q(g)}; if [ -n \"$PREV\" ] && [ \"$PREV\" != code ] && command -v plymouth-set-default-theme >/dev/null 2>&1; "
            f"then plymouth-set-default-theme \"$PREV\" >/dev/null 2>&1 || true; fi; "
            f"update-alternatives --remove default.plymouth {_q(pfile)} >/dev/null 2>&1 || true; "
            f"rm -rf {_q(t)} {_q(md)}; update-grub >/dev/null 2>&1 || true")
    lines = [
        "set -e",
        "STEP=81",
        "PREV=",
        f"undo() {{ {undo}; }}",
        "trap 'rc=$?; if [ $rc -ne 0 ]; then undo; exit $STEP; fi' EXIT",
        "if command -v plymouth-set-default-theme >/dev/null 2>&1; then PREV=\"$(plymouth-set-default-theme 2>/dev/null || true)\"; fi",
        f"if [ \"$PREV\" = code ] && [ -f {_q(m)} ]; then PREV=\"$(sed -n 's/^previous_theme=//p' {_q(m)} | head -n 1)\"; fi",   # enabling twice keeps Mint's theme as the one to restore
        f"rm -f {_q(lg)}",                                           # the file Code 0.4.2 wrote
    ]
    if grub:
        lines.append(_write(g, render_grub(hide_menu, disable_os_prober)))
    lines += [
        "STEP=82",
        f"mkdir -p {_q(t)}\ncp {_q(logo)} {_q(t + '/code-logo.png')}\nchmod 644 {_q(t + '/code-logo.png')}",
        _write(t + "/code.script", PLYMOUTH_SCRIPT),
        _write(pfile, render_plymouth(shown)),
    ]
    if grub:
        lines += ["STEP=83", "update-grub >/dev/null 2>&1", "STEP=84", f"grep -q splash {_q(gm)}"]
        if hide_menu:
            lines.append(f"grep -q 'timeout_style=hidden' {_q(gm)}")
    lines += [
        "STEP=85",
        f"update-alternatives --install /usr/share/plymouth/themes/default.plymouth default.plymouth {_q(pfile)} 300 >/dev/null",
        f"update-alternatives --set default.plymouth {_q(pfile)} >/dev/null",
        # modern Plymouth reads the theme from /etc/plymouth/plymouthd.conf, which only this tool writes
        "if command -v plymouth-set-default-theme >/dev/null 2>&1; then",
        "plymouth-set-default-theme code >/dev/null 2>&1",
        "[ \"$(plymouth-set-default-theme)\" = code ]",
        "fi",
        "STEP=86",
        "update-initramfs -u >/dev/null 2>&1",
        "STEP=87",
        f"INITRD={initrd}",
        "if [ -f \"$INITRD\" ] && command -v lsinitramfs >/dev/null 2>&1; then lsinitramfs \"$INITRD\" | grep -q 'plymouth/themes/code/code.plymouth'; fi",
        "STEP=88",
        f"mkdir -p {_q(md)}",
        "printf 'hide_menu=%s\\nprevious_theme=%s\\n' " + ("yes" if hide_menu else "no") + " \"$PREV\" > " + _q(m),
    ]
    script = "\n".join(lines)
    return script


def disable_script(layout: Layout = DEFAULT) -> str:
    g, lg, t, md, m = (str(layout.p(x)) for x in (layout.grub_cfg, layout.legacy_grub_cfg, layout.theme_dir, layout.marker_dir, layout.marker))
    pfile = f"{t}/code.plymouth"
    return "\n".join([
        "set -e",
        "STEP=89",
        "trap 'rc=$?; if [ $rc -ne 0 ]; then exit $STEP; fi' EXIT",
        f"PREV=\"$(sed -n 's/^previous_theme=//p' {_q(m)} 2>/dev/null | head -n 1)\"",
        f"rm -f {_q(g)} {_q(lg)}",
        "if [ -n \"$PREV\" ] && [ \"$PREV\" != code ] && command -v plymouth-set-default-theme >/dev/null 2>&1; then "
        "plymouth-set-default-theme \"$PREV\" >/dev/null 2>&1 || true; fi",
        f"update-alternatives --remove default.plymouth {_q(pfile)} >/dev/null 2>&1 || true",
        f"rm -rf {_q(t)}",
        "update-grub >/dev/null 2>&1 || true",
        "STEP=86",
        "update-initramfs -u >/dev/null 2>&1",
        f"rm -rf {_q(md)}",
    ])


def logo_path() -> Path:
    return Path(__file__).resolve().parent / "assets" / "code-logo.png"


OFF_TEXT = "Quiet boot is OFF. Mint's own boot screens come back at the next start."


def on_text(menu_hidden: bool) -> str:
    if menu_hidden:
        return ("Quiet boot is ON. From the next start: no boot menu, no Mint logo, the Code logo on black, hardly any text. "
                + HOW_TO_SHOW_MENU)
    return ("Quiet boot is ON (logo and text only). From the next start: the Code logo on black and hardly any text. "
            "The boot menu was left visible because another system is on the disk or GRUB was not found.")


def _run(layout: Layout, script: str, run: Callable | None, out: Callable[[str], None]) -> int:
    return kiosk._pkexec(script, out, run)


def explain(rc: int, doing: str, lines: list[str]) -> str:
    """A plain sentence for a pkexec exit code (the script ends with the number of the step that failed)."""
    if rc == 0:
        return ""
    if rc in STEPS:
        why = (lines[-1] if lines else "").strip()
        return f"Failed while {STEPS[rc]}.{(' ' + why) if why else ''} Everything was put back, nothing changed."
    if rc == rootauth.REFUSED:
        return rootauth.last_error or "This account may not make this change (not an administrator)."
    if rc in (126, 127):
        return "No password was entered (the password window was closed or did not open), so nothing was changed. Press the button again when you are ready."
    return f"Could not {doing} (code {rc}). Nothing else was changed."


def _log(what: str, ok: bool, text: str, lines: list[str]) -> None:
    kiosk.log_event(f"quiet boot {what}: {'OK' if ok else 'FAILED'} - {text}")
    for l in lines[-6:]:
        kiosk.log_event("    output: " + l)


def enable(layout: Layout = DEFAULT, run: Callable | None = None, out: Callable[[str], None] = lambda s: None,
           checks: list[Check] | None = None, logo: Path | None = None, which: Callable = None, force_hide: bool = False,
           fstypes: Callable | None = None) -> tuple[bool, str]:
    """Turn it on. Never raises, and always returns a sentence to show (and writes it to session.log)."""
    import shutil
    which = which or shutil.which
    lines: list[str] = []

    def collect(line: str) -> None:
        lines.append(line)
        out(line)
    try:
        logo = logo or logo_path()
        checks = checks if checks is not None else preflight(layout, which=which, logo=logo, fstypes=fstypes)
        why = blocked(checks)
        if why:
            _log("on", False, why, [])
            return False, why
        grub = bool(which("update-grub")) and layout.p(layout.grub_menu).exists()
        hide = grub and (force_hide or all(c.ok for c in checks))       # a real other system on the disk: the menu is left alone
        others, stale = boot_menu_systems(layout, fstypes) if grub else ([], [])
        prober_off = bool(hide and stale and not others)           # the Windows entry is a leftover: stop os-prober listing it again
        kiosk.log_event(f"quiet boot on: asking for the password (hide_menu={hide}, grub={grub}, os_prober_off={prober_off}, stale={stale})")
        rc = _run(layout, enable_script(layout, logo, hide_menu=hide, grub=grub, disable_os_prober=prober_off), run, collect)
        if rc != 0:
            text = explain(rc, "turn quiet boot on", lines)
            if rc == 84:
                over = [o for o in grub_overrides(layout) if o.wins]
                if over:
                    text += " Competing settings: " + "; ".join(f"{o.file} sets {o.key}={o.value}" for o in over) + "."
            _log("on", False, text, lines)
            return False, text
        if not enabled(layout):
            text = "The password step finished but the files are not there - nothing changed. Run the diagnostic command on the Quiet boot page."
            _log("on", False, text, lines)
            return False, text
        text = on_text(hide)
        _log("on", True, text, [])
        return True, text
    except Exception as exc:  # never take Code down
        text = f"Could not turn quiet boot on: {exc}"
        _log("on", False, text, lines)
        return False, text


def disable(layout: Layout = DEFAULT, run: Callable | None = None, out: Callable[[str], None] = lambda s: None) -> tuple[bool, str]:
    lines: list[str] = []

    def collect(line: str) -> None:
        lines.append(line)
        out(line)
    try:
        kiosk.log_event("quiet boot off: asking for the password")
        rc = _run(layout, disable_script(layout), run, collect)
        if rc != 0:
            text = explain(rc, "turn quiet boot off", lines)
            _log("off", False, text, lines)
            return False, text
        if enabled(layout):
            text = "The files are still there. In a Terminal:  " + RECOVERY
            _log("off", False, text, lines)
            return False, text
        _log("off", True, OFF_TEXT, [])
        return True, OFF_TEXT
    except Exception as exc:
        text = f"Could not turn quiet boot off: {exc}"
        _log("off", False, text, lines)
        return False, text


# ------------------------------------------------------------------ what GRUB / Plymouth really have now (read back from disk)
@dataclass
class Override:
    file: str
    key: str
    value: str
    wins: bool          # sourced after Code's file, so it would beat it


GRUB_KEYS = ("GRUB_TIMEOUT_STYLE", "GRUB_TIMEOUT", "GRUB_HIDDEN_TIMEOUT", "GRUB_HIDDEN_TIMEOUT_QUIET", "GRUB_DISABLE_OS_PROBER")


def grub_overrides(layout: Layout = DEFAULT) -> list[Override]:
    """Other places that set the boot-menu keys. /etc/default/grub is read BEFORE the grub.d files (Code's file is 'zz-...', the last
    one), so only a grub.d file that sorts after it - or after it in the same name - could win. Mint's own 50_linuxmint.cfg sorts before."""
    ours = Path(layout.grub_cfg).name
    found: list[Override] = []
    files = [(layout.p("etc/default/grub"), False)]
    d = layout.p("etc/default/grub.d")
    try:
        files += [(f, f.name > ours) for f in sorted(d.glob("*.cfg")) if f.name not in (ours, Path(layout.legacy_grub_cfg).name)]
    except OSError:
        pass
    for f, wins in files:
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        for m in re.finditer(r"^\s*(?:export\s+)?(%s)=(.*)$" % "|".join(GRUB_KEYS), text, re.M):
            found.append(Override(str(f), m.group(1), m.group(2).strip().strip("\"'"), wins))
    return found


@dataclass
class Fact:
    state: str          # "ok" (applied) | "bad" (NOT applied) | "info"
    text: str


def _newest_initrd(layout: Layout) -> Path | None:
    try:
        files = sorted(layout.p("boot").glob("initrd.img-*"), key=lambda f: f.stat().st_mtime)
        return files[-1] if files else None
    except OSError:
        return None


def status(layout: Layout = DEFAULT, fstypes: Callable | None = None, cmdline: str | None = None, lsinitramfs: Callable | None = None) -> list[Fact]:
    """What is REALLY applied, read back from the files GRUB and Plymouth use (not what Code hopes it did). Never raises."""
    import shutil
    import subprocess
    out: list[Fact] = []

    def add(state: str, text: str):
        out.append(Fact(state, text))
    try:
        on = enabled(layout)
        add("ok" if on else "info", "Quiet boot is ON (Code's marker file exists)." if on else "Quiet boot is OFF (no Code marker file).")
        f = layout.p(layout.grub_cfg)
        add("ok" if f.exists() else "bad", "Code's GRUB setting file is in /etc/default/grub.d." if f.exists() else "Code's GRUB setting file is not there.")
        try:
            cfg = layout.p(layout.grub_menu).read_text(errors="replace")
            hidden = "timeout_style=hidden" in cfg
            tm = re.search(r"set timeout=(\d+)", cfg)
            add("ok" if hidden else "bad", ("GRUB's generated menu (grub.cfg) hides the menu" + (f" (timeout {tm.group(1)} s, Shift / Esc shows it)" if tm else "")) if hidden else
                "GRUB's generated menu (grub.cfg) still SHOWS the menu (no timeout_style=hidden in it)")
            splash = bool(re.search(r"\bquiet\b.*\bsplash\b|\bsplash\b.*\bquiet\b", cfg))
            add("ok" if splash else "bad", "The kernel line in grub.cfg has quiet + splash." if splash else "The kernel line in grub.cfg lacks quiet / splash.")
        except OSError:
            add("info", "GRUB's grub.cfg could not be read here (a different boot loader, or no permission).")
        for o in grub_overrides(layout):
            if o.wins:
                add("bad", f"{o.file} sets {o.key}={o.value} AFTER Code's file, so it can override quiet boot.")
            elif layout.p(layout.grub_cfg).exists() and o.key in ("GRUB_TIMEOUT_STYLE", "GRUB_TIMEOUT", "GRUB_HIDDEN_TIMEOUT"):
                add("info", f"{Path(o.file).name} also sets {o.key}={o.value}; Code's file is read later and wins.")
        try:
            conf = layout.p(layout.plymouth_conf).read_text(errors="replace")
            th = re.search(r"^\s*Theme\s*=\s*(\S+)", conf, re.M)
            name = th.group(1) if th else "(not set)"
            add("ok" if name == "code" else "bad", f"Plymouth's theme (plymouthd.conf) is '{name}'" + ("." if name == "code" else " - not the Code theme."))
        except OSError:
            add("bad" if on else "info", "Plymouth's config (plymouthd.conf) was not found, so the theme is not set that way.")
        theme = layout.p(layout.theme_dir)
        have = (theme / "code.plymouth").exists() and (theme / "code-logo.png").exists()
        add("ok" if have else "bad", "The Code boot-splash theme and logo are installed." if have else "The Code boot-splash theme / logo files are missing.")
        initrd = _newest_initrd(layout)
        if initrd is None:
            add("info", "No boot image (initrd) was found to check.")
        else:
            lsi = lsinitramfs or (lambda p: subprocess.run(["lsinitramfs", str(p)], capture_output=True, text=True, timeout=20))
            try:
                if lsinitramfs is None and not shutil.which("lsinitramfs"):
                    raise OSError("no lsinitramfs")
                r = lsi(initrd)
                if r.returncode == 0:
                    ok = "plymouth/themes/code/code.plymouth" in r.stdout
                    add("ok" if ok else "bad", f"The boot image {initrd.name} " + ("contains the Code theme." if ok else "does NOT contain the Code theme (the logo will not show until update-initramfs runs)."))
                else:
                    add("info", f"The boot image {initrd.name} could not be listed (it needs the administrator).")
            except (OSError, subprocess.SubprocessError):
                add("info", f"The boot image {initrd.name} could not be checked here.")
        others, stale = boot_menu_systems(layout, fstypes)
        if others:
            add("info", "Another system is really on the disk (" + ", ".join(others) + "): the menu stays visible on purpose.")
        if stale:
            add("info", "GRUB lists a leftover entry (" + ", ".join(stale) + ") but no Windows disk exists; it does not block hiding.")
        if cmdline is None:
            try:
                cmdline = layout.p("proc/cmdline").read_text()
            except OSError:
                cmdline = ""
        if cmdline:
            words = cmdline.split()
            q, sp = "quiet" in words, "splash" in words
            add("ok" if (q and sp) else "info", "THIS start-up used: " + ("quiet splash." if q and sp else "no quiet / splash (it was started before quiet boot, or the menu edited it)."))
    except Exception as exc:  # pragma: no cover - never take Code down
        add("info", f"Could not read everything back ({exc}).")
    return out


def status_summary(facts: list[Fact]) -> str:
    bad = [f for f in facts if f.state == "bad"]
    good = [f for f in facts if f.state == "ok"]
    if bad:
        return f"{len(good)} things are applied, {len(bad)} are NOT."
    return f"All {len(good)} checks pass." if good else "Nothing is applied."


def diagnose(layout: Layout = DEFAULT, fstypes: Callable | None = None) -> list[str]:
    """Facts about what is on disk, whether GRUB / Plymouth took the setting, and why Mint's screens might still show. Never raises."""
    import shutil
    import subprocess
    out: list[str] = []

    def line(ok: bool, text: str):
        out.append(("OK     " if ok else "WRONG  ") + text)
    line(enabled(layout), f"quiet boot marker {layout.p(layout.marker)} " + ("exists" if enabled(layout) else "is missing (it is OFF, or failed and was rolled back)"))
    for label, f in (("GRUB setting file", layout.p(layout.grub_cfg)), ("Code boot theme", layout.p(layout.theme_dir) / "code.plymouth")):
        line(f.exists(), f"{label}: {f}")
    if layout.p(layout.legacy_grub_cfg).exists():
        out.append(f"NOTE   leftover file from Code 0.4.2: {layout.p(layout.legacy_grub_cfg)} (turning quiet boot on again removes it)")
    try:
        cfg = layout.p(layout.grub_menu).read_text(errors="replace")
        line("timeout_style=hidden" in cfg, "the generated boot menu (grub.cfg) says timeout_style=hidden - if not, GRUB still shows its menu")
        line(bool(re.search(r"\bsplash\b", cfg)), "the generated boot menu has 'splash' on the kernel line")
    except OSError:
        out.append("NOTE   /boot/grub/grub.cfg was not found or is not readable")
    others, stale = boot_menu_systems(layout, fstypes)
    out.append(("NOTE   other systems in the boot menu: " + ", ".join(others)) if others else "OK     no other system in the boot menu")
    if stale:
        out.append("NOTE   leftover entries (no Windows disk exists any more, they do not block hiding): " + ", ".join(stale))
    try:
        f = layout.p(layout.plymouth_conf)
        theme = re.search(r"^\s*Theme\s*=\s*(\S+)", f.read_text(errors="replace"), re.M)
        out.append(("OK     " if theme and theme.group(1) == "code" else "WRONG  ") + f"/etc/plymouth/plymouthd.conf Theme={theme.group(1) if theme else '(not set)'} (must be code)")
    except OSError:
        out.append("NOTE   no /etc/plymouth/plymouthd.conf (the theme then comes from update-alternatives / the defaults)")
    if shutil.which("plymouth-set-default-theme"):
        try:
            cur = subprocess.run(["plymouth-set-default-theme"], capture_output=True, text=True, timeout=10).stdout.strip()
            line(cur == "code", f"plymouth-set-default-theme says the theme is '{cur}' (must be code)")
        except (OSError, subprocess.SubprocessError):
            pass
    tail = kiosk.log_tail(6)
    out.append("session log (" + str(kiosk.session_log_path()) + "): " + ("" if tail else "nothing written yet"))
    out += ["    " + t for t in tail]
    return out


# One line for a Terminal: shows exactly what Quiet boot did and what GRUB / Plymouth made of it (works on 0.4.2 and newer).
DIAGNOSTIC_COMMAND = ("ls -l /etc/code-boot /etc/default/grub.d /usr/share/plymouth/themes/code; cat /etc/default/grub.d/*code* 2>/dev/null; "
                      "grep -c 'timeout_style=hidden' /boot/grub/grub.cfg; grep -n \"menuentry 'Windows\" /boot/grub/grub.cfg; "
                      "plymouth-set-default-theme; cat /etc/plymouth/plymouthd.conf 2>/dev/null; update-alternatives --display default.plymouth | head -6; "
                      "lsblk -o NAME,FSTYPE,LABEL; tail -20 ~/.local/share/atari/session.log")


def main(argv: list[str] | None = None) -> int:
    """python3 -m atarilauncher.quietboot --check   prints diagnose()."""
    import sys
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--check"]:
        print("\n".join(diagnose()))
        return 0
    print("usage: python3 -m atarilauncher.quietboot --check", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
