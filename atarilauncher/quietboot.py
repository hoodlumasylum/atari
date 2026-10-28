"""Quiet boot ("hide the Mint branding") - an optional extra for CodeAque-only mode. Everything it does can be undone from the same screen.

What turning it ON does (one password window, `pkexec`; nothing else is touched):
  1. /etc/default/grub.d/zz-code-quiet.cfg      GRUB: "quiet splash" and less kernel / systemd text; the boot menu is hidden for a
                                                 2 second window in which Shift (old BIOS) or Esc (UEFI) shows it again - and it is
                                                 NOT hidden when another operating system (Windows, macOS ...) is on the disk
  2. /usr/share/plymouth/themes/code/           a boot-splash theme: black background, the CodeAque logo (code-logo.png) in the middle,
                                                 made the default with update-alternatives (the Mint logo theme stays installed)
  3. /etc/code-boot/quiet-boot                  a note that this is on (and what was changed)
  then `update-grub` and `update-initramfs -u` (the splash is part of the initramfs). If either fails, everything is put back.
Turning it OFF removes exactly those files, takes the CodeAque theme out of update-alternatives (Mint's own splash comes back), and runs
update-grub / update-initramfs again.

Recovery is never removed: the boot menu is one key away (Shift / Esc within the 2 s window; since 0.4.6 it no longer pops up by itself
after a hard power-off either, because /boot/grub/custom.cfg has the last word), "Advanced options" / recovery mode are untouched, and from a text console (Ctrl+Alt+F2) RECOVERY below undoes it all.
Not done on purpose: LightDM's own (Mint) login screen is not restyled - with CodeAque-only mode's auto-login it is skipped anyway.
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
            "sudo sed -i '/^# BEGIN code-quiet-boot/,/^# END code-quiet-boot/d' /boot/grub/custom.cfg; "
            "sudo plymouth-set-default-theme \"$(sed -n 's/^previous_theme=//p' /etc/code-boot/quiet-boot)\"; "
            "sudo update-alternatives --remove default.plymouth /usr/share/plymouth/themes/code/code.plymouth; "
            "sudo update-grub && sudo update-initramfs -u && sudo rm -rf /etc/code-boot /usr/share/plymouth/themes/code")
BIOS_LOGO_NOTE = ("The Dell / manufacturer logo shown right at power-on is drawn by the computer's own firmware (UEFI / BIOS) before Linux or GRUB starts, "
                  "so CodeAque cannot remove it. In the BIOS setup (tap F2 at power-on; F12 is the one-time boot menu) look for Fast Boot (e.g. Settings > POST "
                  "Behavior > Fastboot: Minimal / Auto) and for any 'logo' / 'Full Screen Logo' / 'Quiet' option under Boot, Display or POST Behavior. "
                  "Some models have no switch at all, and CodeAque cannot change firmware settings from Linux.")
HOW_TO_SHOW_MENU = "To see the boot menu: hold Shift (older BIOS) or tap Esc (UEFI) right when the computer starts."
CMDLINE = "quiet splash loglevel=3 rd.systemd.show_status=false systemd.show_status=false rd.udev.log_level=3 vt.global_cursor_default=0"
OTHER_OS = re.compile(r"menuentry\s+['\"]([^'\"]*(Windows|Microsoft|macOS|Mac OS|Darwin|FreeBSD|OpenBSD)[^'\"]*)['\"]", re.I)


@dataclass
class Layout:
    root: Path = Path("/")
    grub_cfg: str = "etc/default/grub.d/zz-code-quiet.cfg"          # "zz": read after every other grub.d file, so nothing overrides it
    legacy_grub_cfg: str = "etc/default/grub.d/90-code-quiet.cfg"   # written by CodeAque 0.4.2; cleaned up
    plymouth_conf: str = "etc/plymouth/plymouthd.conf"
    theme_dir: str = "usr/share/plymouth/themes/code"
    marker_dir: str = "etc/code-boot"
    marker: str = "etc/code-boot/quiet-boot"
    grub_menu: str = "boot/grub/grub.cfg"
    grub_custom: str = "boot/grub/custom.cfg"      # sourced by 41_custom as the LAST thing grub.cfg does: beats os-prober's and the failed-boot menu
    grubenv: str = "boot/grub/grubenv"

    def p(self, rel: str) -> Path:
        return self.root / rel

    @property
    def files(self) -> list[Path]:
        return [self.p(self.grub_cfg), self.p(self.theme_dir), self.p(self.marker)]


DEFAULT = Layout()


def enabled(layout: Layout = DEFAULT) -> bool:
    return layout.p(layout.marker).is_file()


def marker_hide(layout: Layout = DEFAULT) -> bool | None:
    """Whether quiet boot was turned on WITH the boot menu hidden (True), logo and text only (False), or is off / unreadable (None)."""
    try:
        for ln in layout.p(layout.marker).read_text(errors="replace").splitlines():
            if ln.startswith("hide_menu="):
                return ln.split("=", 1)[1].strip() == "yes"
    except OSError:
        pass
    return None


def windows_partitions() -> list[str]:
    """Human text for every Windows-type partition still on the disks (a Dell recovery / WinRE partition counts), e.g. 'nvme0n1p4 (ntfs, 1G, WINRE_DRV)'."""
    import subprocess
    try:
        p = subprocess.run(["lsblk", "-rno", "NAME,FSTYPE,SIZE,LABEL"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return []
    out = []
    for ln in p.stdout.splitlines():
        parts = ln.split(None, 3)
        if len(parts) >= 2 and parts[1].lower() in ("ntfs", "bitlocker", "ntfs3"):
            out.append(f"{parts[0]} ({parts[1]}, {parts[2] if len(parts) > 2 else '?'}" + (f", {parts[3].strip()}" if len(parts) > 3 and parts[3].strip() else "") + ")")
    return out


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
        "This computer does not manage its boot splash with update-alternatives, so CodeAque will not touch it.")
    add(bool(logo and logo.is_file()), True, "CodeAque's logo file was found.", "CodeAque's logo file (code-logo.png) was not found - reinstall CodeAque.")
    has_grub = bool(which("update-grub")) and layout.p(layout.grub_menu).exists()
    add(has_grub, False, "GRUB is the boot menu, so its text and menu can be quietened.",
        "GRUB was not found (another boot loader?): only the splash logo is changed, the boot menu is left alone.")
    others, stale = boot_menu_systems(layout, fstypes) if has_grub else ([], [])
    if stale:
        out.append(Check(True, False, "GRUB still lists " + ", ".join(stale) + ", but no Windows disk (NTFS) is left: it is a leftover and does "
                                      "not stop the boot menu from being hidden."))
    wp = windows_partitions() if others else []
    extra = (" Windows-type partitions still on the disks: " + ", ".join(wp) + ". A Dell keeps recovery partitions (SupportAssist / WinRE) even after "
             "Windows is deleted - if you do not use Windows any more, choose 'hide the boot menu anyway'.") if wp else ""
    add(not others, False, "Only this operating system is on the disk: the boot menu is hidden (Shift / Esc shows it).",
        "Another system is on this disk (" + ", ".join(others) + "): the boot menu stays visible so you can still choose it." + extra)
    return out


def blocked(checks: list[Check]) -> str:
    for c in checks:
        if c.fatal and not c.ok:
            return c.text
    return ""


# ------------------------------------------------------------------ file contents
def render_grub(hide_menu: bool, disable_os_prober: bool = False) -> str:
    lines = ["# Written by CodeAque > Settings > Quiet boot. Remove with Settings > Quiet boot > Turn off."]
    if hide_menu:
        lines += ["GRUB_TIMEOUT_STYLE=hidden", "GRUB_TIMEOUT=2", "GRUB_HIDDEN_TIMEOUT_QUIET=true",     # Shift / Esc inside these 2 seconds shows the menu
                  "GRUB_RECORDFAIL_TIMEOUT=2"]          # Ubuntu / Mint's 00_header otherwise shows the menu for 30 s after a boot that did not finish (hard power-off)
    if disable_os_prober:       # only a leftover "Windows Boot Manager" (no Windows disk) is on the machine: stop GRUB listing it again
        lines += ["GRUB_DISABLE_OS_PROBER=true"]
    lines += [f'GRUB_CMDLINE_LINUX_DEFAULT="$GRUB_CMDLINE_LINUX_DEFAULT {CMDLINE}"', ""]
    return "\n".join(lines)


CUSTOM_BEGIN = "# BEGIN code-quiet-boot (written by CodeAque > Settings > Quiet boot; Turn off removes this block)"
CUSTOM_END = "# END code-quiet-boot"


def render_custom() -> str:
    """The last word on the menu. /etc/grub.d/41_custom sources /boot/grub/custom.cfg at the very end of grub.cfg, after Ubuntu / Mint's own
    rules that force the menu (30_os-prober's 'another OS found: timeout_style=menu, timeout=10', and 00_header's 'last boot did not finish:
    menu for 30 s / for ever' - also always on UEFI when GRUB cannot write its grubenv). Hidden + 2 s: Esc / Shift still shows the menu."""
    return "\n".join([CUSTOM_BEGIN, "set timeout_style=hidden", "set timeout=2", CUSTOM_END, ""])


def render_plymouth(theme_dir: str) -> str:
    return f"""[Plymouth Theme]
Name=CodeAque
Description=CodeAque logo on black
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
    81: "writing the GRUB setting file", 82: "writing the CodeAque boot-splash theme", 83: "rebuilding the boot menu (update-grub)",
    84: "checking that GRUB took the setting (another file overrides it)", 85: "choosing the CodeAque boot-splash theme",
    86: "rebuilding the boot image (update-initramfs)", 87: "checking that the boot image contains the CodeAque theme", 88: "writing the note that quiet boot is on",
    89: "restoring Mint's boot-splash theme", 90: "checking that update-grub really rewrote /boot/grub/grub.cfg",
    91: "writing the last-word menu setting (custom.cfg)",
}


def drop_custom(cc: str) -> str:
    """Shell that removes CodeAque's block from custom.cfg (and the file itself when nothing else is in it). Never fails."""
    return (f"if [ -f {_q(cc)} ]; then sed -i '/^# BEGIN code-quiet-boot/,/^# END code-quiet-boot/d' {_q(cc)} || true; "
            f"[ -s {_q(cc)} ] || rm -f {_q(cc)}; fi")


def enable_script(layout: Layout = DEFAULT, logo: Path | None = None, hide_menu: bool = True, theme_visible_path: str | None = None,
                  grub: bool = True, disable_os_prober: bool = False) -> str:
    """What pkexec runs as root. Any failure puts every file back and ends the script with the exit code of the step that failed (STEPS)."""
    g, lg, t, md, m, gm, pc = (str(layout.p(x)) for x in (layout.grub_cfg, layout.legacy_grub_cfg, layout.theme_dir, layout.marker_dir,
                                                         layout.marker, layout.grub_menu, layout.plymouth_conf))
    cc, genv = str(layout.p(layout.grub_custom)), str(layout.p(layout.grubenv))
    shown = theme_visible_path or "/" + layout.theme_dir          # the path Plymouth reads at boot (never the test folder)
    pfile = f"{t}/code.plymouth"
    initrd = str(layout.p("boot/initrd.img-")) + "$(uname -r)"
    undo = (f"rm -f {_q(g)}; {drop_custom(cc)}; if [ -n \"$PREV\" ] && [ \"$PREV\" != code ] && command -v plymouth-set-default-theme >/dev/null 2>&1; "
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
        f"rm -f {_q(lg)}",                                           # the file CodeAque 0.4.2 wrote
    ]
    if grub:
        lines.append(_write(g, render_grub(hide_menu, disable_os_prober)))
        if hide_menu:
            lines += ["STEP=91", drop_custom(cc), f"mkdir -p {_q(Path(cc).parent)}", f"printf %s {_q(render_custom())} >> {_q(cc)}", f"chmod 644 {_q(cc)}", "STEP=81"]
    lines += [
        "STEP=82",
        f"mkdir -p {_q(t)}\ncp {_q(logo)} {_q(t + '/code-logo.png')}\nchmod 644 {_q(t + '/code-logo.png')}",
        _write(t + "/code.script", PLYMOUTH_SCRIPT),
        _write(pfile, render_plymouth(shown)),
    ]
    if grub:
        lines += [f"BEFORE=\"$(stat -c %y {_q(gm)} 2>/dev/null || echo none)\"",
                  # a failed boot left 'recordfail=1' in grubenv: clear it now so the menu does not show once more for that
                  f"if [ -f {_q(genv)} ] && command -v grub-editenv >/dev/null 2>&1; then grub-editenv {_q(genv)} unset recordfail >/dev/null 2>&1 || true; fi",
                  "STEP=83", "update-grub >/dev/null 2>&1",
                  "STEP=90", f"AFTER=\"$(stat -c %y {_q(gm)} 2>/dev/null || echo none)\"", "[ \"$AFTER\" != none -a \"$AFTER\" != \"$BEFORE\" ]",
                  "STEP=84", f"grep -q splash {_q(gm)}"]
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
        drop_custom(str(layout.p(layout.grub_custom))),
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
    return Path(__file__).resolve().parent / "assets" / "codeaque-logo.png"


OFF_TEXT = "Quiet boot is OFF. Mint's own boot screens come back at the next start."


def on_text(menu_hidden: bool) -> str:
    if menu_hidden:
        return ("Quiet boot is ON. From the next start: no boot menu, no Mint logo, the CodeAque logo on black, hardly any text. "
                + HOW_TO_SHOW_MENU)
    return ("Quiet boot is ON (logo and text only). From the next start: the CodeAque logo on black and hardly any text. "
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
        text = on_text(hide) + readback_text(layout, hide, fstypes)
        _log("on", True, text, [])
        return True, text
    except Exception as exc:  # never take CodeAque down
        text = f"Could not turn quiet boot on: {exc}"
        _log("on", False, text, lines)
        return False, text


def readback_text(layout: Layout, hide: bool, fstypes: Callable | None = None) -> str:
    """After update-grub: read /boot/grub/grub.cfg (and the rest) back and say what is REALLY in it - never what we hoped for."""
    try:
        facts = status(layout, fstypes)
        cfg = layout.p(layout.grub_menu).read_text(errors="replace")
    except Exception:
        return ""
    bits = []
    if hide:
        tm = re.search(r"set timeout=(\d+)", cfg)
        hid = "timeout_style=hidden" in cfg
        block, sourced = _custom_state(layout)
        bits.append(("grub.cfg: menu hidden" + (f", {tm.group(1)} s window" if tm else "")) if hid else "grub.cfg: the menu is NOT hidden")
        bits.append("custom.cfg last word: " + ("yes" if block and sourced else "NO (grub.cfg does not read it)"))
    bits.append("quiet splash: " + ("yes" if re.search(r"\bquiet\b.*\bsplash\b|\bsplash\b.*\bquiet\b", cfg) else "NO"))
    bad = [f.text for f in facts if f.state == "bad"]
    text = " Read back from the files just now - " + "; ".join(bits) + "."
    if bad:
        text += " Still NOT applied: " + " | ".join(bad[:4]) + "."
    return text


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
    wins: bool          # sourced after CodeAque's file, so it would beat it


GRUB_KEYS = ("GRUB_TIMEOUT_STYLE", "GRUB_TIMEOUT", "GRUB_HIDDEN_TIMEOUT", "GRUB_HIDDEN_TIMEOUT_QUIET", "GRUB_DISABLE_OS_PROBER")


def grub_overrides(layout: Layout = DEFAULT) -> list[Override]:
    """Other places that set the boot-menu keys. /etc/default/grub is read BEFORE the grub.d files (CodeAque's file is 'zz-...', the last
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


def menu_forcers(cfg: str) -> list[str]:
    """Things in a generated grub.cfg that can SHOW the menu although timeout_style=hidden was asked for (Ubuntu / Mint patches)."""
    found: list[str] = []
    m = re.search(r"### BEGIN /etc/grub\.d/30_os-prober ###(.*?)### END /etc/grub\.d/30_os-prober ###", cfg, re.S)
    if m and re.search(r"^\s*set timeout_style=menu", m.group(1), re.M):
        found.append("30_os-prober found another system and forces the menu (timeout_style=menu, 10 s)")
    rf = re.search(r'recordfail\}"\s*=\s*1\s*\]\s*;\s*then(.{0,300})', cfg, re.S)
    if rf:
        t = re.search(r"set timeout=(-?\d+)", rf.group(1))
        if t and t.group(1) != "0":
            found.append(f"after a boot that did not finish (recordfail) 00_header shows the menu for {'ever' if t.group(1) == '-1' else t.group(1) + ' s'}")
    if "recordfail support is disabled" in cfg and re.search(r"grub_platform\s*=\s*efi", cfg):
        found.append("GRUB cannot write its grubenv on this disk (recordfail is off), so on UEFI it always shows the menu")
    return found


def _custom_state(layout: Layout) -> tuple[bool, bool]:
    """(CodeAque's block is in custom.cfg, grub.cfg sources custom.cfg)."""
    try:
        block = CUSTOM_BEGIN.split(" (")[0] in layout.p(layout.grub_custom).read_text(errors="replace")
    except OSError:
        block = False
    try:
        sourced = "custom.cfg" in layout.p(layout.grub_menu).read_text(errors="replace")
    except OSError:
        sourced = False
    return block, sourced


def status(layout: Layout = DEFAULT, fstypes: Callable | None = None, cmdline: str | None = None, lsinitramfs: Callable | None = None) -> list[Fact]:
    """What is REALLY applied, read back from the files GRUB and Plymouth use (not what CodeAque hopes it did). Never raises."""
    import shutil
    import subprocess
    out: list[Fact] = []

    def add(state: str, text: str):
        out.append(Fact(state, text))
    try:
        on = enabled(layout)
        add("ok" if on else "info", "Quiet boot is ON (CodeAque's marker file exists)." if on else "Quiet boot is OFF (no CodeAque marker file).")
        f = layout.p(layout.grub_cfg)
        add("ok" if f.exists() else "bad", "CodeAque's GRUB setting file is in /etc/default/grub.d." if f.exists() else "CodeAque's GRUB setting file is not there.")
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
        try:
            cfg_text = layout.p(layout.grub_menu).read_text(errors="replace")
        except OSError:
            cfg_text = ""
        if cfg_text:
            forcers = menu_forcers(cfg_text)
            block, sourced = _custom_state(layout)
            hide_marker = marker_hide(layout)
            if block and sourced:
                add("ok", "Last-word setting: /boot/grub/custom.cfg (read at the very end of grub.cfg) sets the menu hidden, so it wins over os-prober and the failed-boot menu.")
            elif on and hide_marker:
                add("bad", "CodeAque's custom.cfg block is " + ("missing" if not block else "there, but grub.cfg does not read custom.cfg (no 41_custom)") + ": Mint / Ubuntu rules below can still show the menu.")
            for fcr in forcers:
                add("info" if (block and sourced) else "bad", ("Overridden by custom.cfg: " if (block and sourced) else "Can show the menu: ") + fcr + ".")
            try:
                env = layout.p(layout.grubenv).read_text(errors="replace")
                if re.search(r"^recordfail=1\s*$", env, re.M):
                    add("info" if (block and sourced) else "bad", "GRUB's grubenv says the last start did not finish (recordfail=1): that shows the menu once"
                        + (" (custom.cfg hides it anyway)." if (block and sourced) else "; it is cleared after a normal start."))
            except OSError:
                pass
            if on and hide_marker is False:
                add("info", "Quiet boot was turned on WITHOUT hiding the menu (another system looked present). Use 'Hide the boot menu too' on this page if you do not use it.")
        for o in grub_overrides(layout):
            if o.wins:
                add("bad", f"{o.file} sets {o.key}={o.value} AFTER CodeAque's file, so it can override quiet boot.")
            elif layout.p(layout.grub_cfg).exists() and o.key in ("GRUB_TIMEOUT_STYLE", "GRUB_TIMEOUT", "GRUB_HIDDEN_TIMEOUT"):
                add("info", f"{Path(o.file).name} also sets {o.key}={o.value}; CodeAque's file is read later and wins.")
        try:
            conf = layout.p(layout.plymouth_conf).read_text(errors="replace")
            th = re.search(r"^\s*Theme\s*=\s*(\S+)", conf, re.M)
            name = th.group(1) if th else "(not set)"
            add("ok" if name == "code" else "bad", f"Plymouth's theme (plymouthd.conf) is '{name}'" + ("." if name == "code" else " - not the CodeAque theme."))
        except OSError:
            add("bad" if on else "info", "Plymouth's config (plymouthd.conf) was not found, so the theme is not set that way.")
        theme = layout.p(layout.theme_dir)
        have = (theme / "code.plymouth").exists() and (theme / "code-logo.png").exists()
        add("ok" if have else "bad", "The CodeAque boot-splash theme and logo are installed." if have else "The CodeAque boot-splash theme / logo files are missing.")
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
                    add("ok" if ok else "bad", f"The boot image {initrd.name} " + ("contains the CodeAque theme." if ok else "does NOT contain the CodeAque theme (the logo will not show until update-initramfs runs)."))
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
    except Exception as exc:  # pragma: no cover - never take CodeAque down
        add("info", f"Could not read everything back ({exc}).")
    return out


def status_summary(facts: list[Fact]) -> str:
    bad = [f for f in facts if f.state == "bad"]
    good = [f for f in facts if f.state == "ok"]
    if bad:
        return f"{len(good)} things are applied, {len(bad)} are NOT."
    return f"All {len(good)} checks pass." if good else "Nothing is applied."


# ------------------------------------------------------------------ the boot report (a short text file the user can send)
REPORT_NAME = "code-boot-report.txt"
_SECRET = re.compile(r"password|passwd|pbkdf2|secret|token|\bkey\b", re.I)


def _clean(text: str, keep: Callable[[str], bool] | None = None, limit: int = 80, comments: bool = False) -> list[str]:
    """Lines of a config file without comments / blanks / anything that smells like a secret; optionally only lines `keep` accepts."""
    out = []
    for ln in text.splitlines():
        t = ln.strip()
        if not t or (t.startswith("#") and not comments):
            continue
        if _SECRET.search(t):
            out.append("(line left out: looks like a secret)")
            continue
        if keep is None or keep(t):
            out.append(t)
        if len(out) >= limit:
            out.append("... (cut)")
            break
    return out


def boot_report(layout: Layout = DEFAULT, run: Callable | None = None, version: str = "", now: str = "") -> str:
    """A short plain-text report for support: what GRUB / Plymouth / the firmware boot list say. No passwords, no personal files.
    `run(cmd) -> str` returns the output of a command ('' when it is missing / fails) so tests need no real tools. Never raises."""
    import subprocess
    import time

    def default_run(cmd: list[str]) -> str:
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return ""
        return (p.stdout or "") if p.returncode == 0 else ((p.stdout or "") + (p.stderr or ""))
    run = run or default_run
    out: list[str] = []

    def section(title: str, lines: list[str] | str):
        out.append("")
        out.append(f"== {title} ==")
        if isinstance(lines, str):
            lines = lines.splitlines()
        out.extend(lines if lines else ["(nothing / not available)"])

    def read(rel: str) -> str:
        try:
            return layout.p(rel).read_text(errors="replace")
        except OSError:
            return ""
    try:
        out.append("CodeAque boot report")
        out.append(f"CodeAque {version or '?'}   made {now or time.strftime('%Y-%m-%d %H:%M')} (this computer's clock)")
        out.append("No passwords are in this file. It lists boot settings only.")
        osr = {k: v.strip('"') for k, _, v in (ln.partition("=") for ln in read("etc/os-release").splitlines()) if k in ("PRETTY_NAME", "VERSION_CODENAME", "UBUNTU_CODENAME")}
        section("System", [f"{k}={v}" for k, v in osr.items()] + ["kernel: " + (run(["uname", "-r"]).strip() or "?"),
                                                                   "firmware: " + ("UEFI" if layout.p("sys/firmware/efi").exists() else "legacy BIOS (or not readable)"),
                                                                   "this start-up kernel line: " + (read("proc/cmdline").strip() or "?")])
        sb = run(["mokutil", "--sb-state"]).strip()
        if sb:
            out.append("secure boot: " + sb.splitlines()[0])
        on, hide = enabled(layout), marker_hide(layout)
        section("Quiet boot (CodeAque)", [f"marker: {'ON' if on else 'OFF'}" + (f", menu hidden requested: {'yes' if hide else 'no'}" if hide is not None else ""),
                                       "CodeAque's GRUB file: " + ("present" if layout.p(layout.grub_cfg).exists() else "missing")] +
                ["  " + t for t in _clean(read(layout.grub_cfg))])
        section("/etc/default/grub (uncommented lines)", _clean(read("etc/default/grub")))
        d = layout.p("etc/default/grub.d")
        try:
            names = sorted(f for f in d.glob("*.cfg"))
        except OSError:
            names = []
        for f in names:
            section(f"/etc/default/grub.d/{f.name}", _clean(f.read_text(errors="replace") if f.is_file() else ""))
        section("/boot/grub/custom.cfg", _clean(read(layout.grub_custom), comments=True))
        env = [ln for ln in read(layout.grubenv).splitlines() if ln.split("=", 1)[0] in ("recordfail", "saved_entry", "next_entry", "boot_indeterminate")]
        section("/boot/grub/grubenv (only the boot-state keys)", env)
        cfg = read(layout.grub_menu)
        keep = re.compile(r"timeout|recordfail|timeout_style|BEGIN /etc/grub\.d|custom\.cfg|osprober|\bquiet\b|splash|menuentry |grub_platform", re.I)
        section("/boot/grub/grub.cfg (timeout / menu / quiet lines only)", [ln.rstrip()[:200] for ln in cfg.splitlines() if keep.search(ln)][:150] if cfg else "(could not be read)")
        forcers = menu_forcers(cfg) if cfg else []
        section("What could show the menu", forcers or ["nothing found in grub.cfg"])
        section("efibootmgr -v (firmware boot entries)", run(["efibootmgr", "-v"]).strip().splitlines()[:40])
        section("lsblk (disks and partitions)", run(["lsblk", "-o", "NAME,SIZE,FSTYPE,LABEL,MOUNTPOINT"]).strip().splitlines()[:40])
        section("Plymouth", _clean(read(layout.plymouth_conf)) + ["plymouth-set-default-theme: " + (run(["plymouth-set-default-theme"]).strip() or "?")])
        try:
            facts = status(layout)
            section("Read back by CodeAque just now", [f"{ {'ok': 'OK', 'bad': 'NOT APPLIED', 'info': 'note'}[f.state] }: {f.text}" for f in facts])
        except Exception as exc:  # pragma: no cover
            section("Read back by CodeAque just now", [f"(could not: {exc})"])
        tail = [t for t in kiosk.log_tail(60) if re.search(r"quiet boot|steam launch|code-only|kiosk", t, re.I)][-25:]
        section("CodeAque's session log (boot-related lines)", [t[:240] for t in tail if not _SECRET.search(t)])
        section("About the Dell logo", [BIOS_LOGO_NOTE])
    except Exception as exc:  # pragma: no cover - never take CodeAque down
        out.append(f"(report stopped early: {exc})")
    return "\n".join(out) + "\n"


def save_report(text: str, downloads: Path | None = None) -> tuple[bool, str, Path | None]:
    """Write the report to ~/Downloads/code-boot-report.txt. (ok, plain sentence, path)."""
    d = downloads or (Path.home() / "Downloads")
    try:
        d.mkdir(parents=True, exist_ok=True)
        f = d / REPORT_NAME
        f.write_text(text, encoding="utf-8")
        return True, f"Saved {f}. Send that file to whoever is helping you (it has no passwords).", f
    except OSError as exc:
        return False, f"Could not save the boot report: {exc}", None


def diagnose(layout: Layout = DEFAULT, fstypes: Callable | None = None) -> list[str]:
    """Facts about what is on disk, whether GRUB / Plymouth took the setting, and why Mint's screens might still show. Never raises."""
    import shutil
    import subprocess
    out: list[str] = []

    def line(ok: bool, text: str):
        out.append(("OK     " if ok else "WRONG  ") + text)
    line(enabled(layout), f"quiet boot marker {layout.p(layout.marker)} " + ("exists" if enabled(layout) else "is missing (it is OFF, or failed and was rolled back)"))
    for label, f in (("GRUB setting file", layout.p(layout.grub_cfg)), ("CodeAque boot theme", layout.p(layout.theme_dir) / "code.plymouth")):
        line(f.exists(), f"{label}: {f}")
    if layout.p(layout.legacy_grub_cfg).exists():
        out.append(f"NOTE   leftover file from CodeAque 0.4.2: {layout.p(layout.legacy_grub_cfg)} (turning quiet boot on again removes it)")
    try:
        cfg = layout.p(layout.grub_menu).read_text(errors="replace")
        line("timeout_style=hidden" in cfg, "the generated boot menu (grub.cfg) says timeout_style=hidden - if not, GRUB still shows its menu")
        line(bool(re.search(r"\bsplash\b", cfg)), "the generated boot menu has 'splash' on the kernel line")
        block, sourced = _custom_state(layout)
        line(block and sourced, "/boot/grub/custom.cfg has CodeAque's hidden-menu block AND grub.cfg reads custom.cfg (the last word over os-prober / failed-boot menus)")
        for fcr in menu_forcers(cfg):
            out.append("NOTE   can show the menu: " + fcr)
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
                      "cat /boot/grub/custom.cfg; grep -c 'timeout_style=hidden' /boot/grub/grub.cfg; grep -n \"menuentry 'Windows\" /boot/grub/grub.cfg; "
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
