"""Quiet boot ("hide the Mint branding") - an optional extra for Code-only mode. Everything it does can be undone from the same screen.

What turning it ON does (one password window, `pkexec`; nothing else is touched):
  1. /etc/default/grub.d/90-code-quiet.cfg      GRUB: "quiet splash" and less kernel / systemd text; the boot menu is hidden for a
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

RECOVERY = ("To undo quiet boot by hand (Ctrl+Alt+F2, log in): sudo rm /etc/default/grub.d/90-code-quiet.cfg && "
            "sudo update-alternatives --remove default.plymouth /usr/share/plymouth/themes/code/code.plymouth && "
            "sudo update-grub && sudo update-initramfs -u && sudo rm -rf /etc/code-boot /usr/share/plymouth/themes/code")
HOW_TO_SHOW_MENU = "To see the boot menu: hold Shift (older BIOS) or tap Esc (UEFI) right when the computer starts."
CMDLINE = "quiet splash loglevel=3 rd.systemd.show_status=false systemd.show_status=false rd.udev.log_level=3 vt.global_cursor_default=0"
OTHER_OS = re.compile(r"menuentry\s+['\"]([^'\"]*(Windows|Microsoft|macOS|Mac OS|Darwin|FreeBSD|OpenBSD)[^'\"]*)['\"]", re.I)


@dataclass
class Layout:
    root: Path = Path("/")
    grub_cfg: str = "etc/default/grub.d/90-code-quiet.cfg"
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


def other_systems(layout: Layout = DEFAULT) -> list[str]:
    """Names of other operating systems GRUB offers (Windows ...). Unreadable menu counts as 'unknown' = one entry, to stay safe."""
    try:
        text = layout.p(layout.grub_menu).read_text(errors="replace")
    except OSError:
        return ["(the boot menu could not be read)"] if layout.p(layout.grub_menu).exists() else []
    return sorted({m.group(1) for m in OTHER_OS.finditer(text)})


@dataclass
class Check:
    ok: bool
    fatal: bool
    text: str


def preflight(layout: Layout = DEFAULT, which: Callable = None, logo: Path | None = None) -> list[Check]:
    import shutil
    which = which or shutil.which
    out: list[Check] = []

    def add(ok: bool, fatal: bool, good: str, bad: str):
        out.append(Check(ok, fatal, good if ok else bad))
    add(bool(which("pkexec")), True, "The password window (pkexec) is available.", "The password window (pkexec) is missing: install the 'policykit-1' package.")
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
    others = other_systems(layout) if has_grub else []
    add(not others, False, "Only this operating system is on the disk: the boot menu is hidden (Shift / Esc shows it).",
        "Another system is on this disk (" + ", ".join(others) + "): the boot menu stays visible so you can still choose it.")
    return out


def blocked(checks: list[Check]) -> str:
    for c in checks:
        if c.fatal and not c.ok:
            return c.text
    return ""


# ------------------------------------------------------------------ file contents
def render_grub(hide_menu: bool) -> str:
    lines = ["# Written by Code > Settings > Quiet boot. Remove with Settings > Quiet boot > Turn off."]
    if hide_menu:
        lines += ["GRUB_TIMEOUT_STYLE=hidden", "GRUB_TIMEOUT=2"]          # Shift / Esc inside these 2 seconds shows the menu
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
    return (f"mkdir -p {_q(Path(path).parent)} && printf %s {_q(content)} > {_q(path)} && chmod {mode} {_q(path)}")


def enable_script(layout: Layout = DEFAULT, logo: Path | None = None, hide_menu: bool = True, theme_visible_path: str | None = None,
                  grub: bool = True) -> str:
    """What pkexec runs as root. On any failure the trap puts every file back before the script ends."""
    g, t, md, m = (str(layout.p(x)) for x in (layout.grub_cfg, layout.theme_dir, layout.marker_dir, layout.marker))
    shown = theme_visible_path or "/" + layout.theme_dir          # the path Plymouth reads at boot (never the test folder)
    pfile = f"{t}/code.plymouth"
    undo = (f"rm -f {_q(g)}; update-alternatives --remove default.plymouth {_q(pfile)} >/dev/null 2>&1 || true; "
            f"rm -rf {_q(t)} {_q(md)}; update-grub >/dev/null 2>&1 || true")
    return "\n".join([
        "set -e",
        f"undo() {{ {undo}; }}",
        "trap 'rc=$?; if [ $rc -ne 0 ]; then undo; fi' EXIT",
        *([_write(g, render_grub(hide_menu))] if grub else []),
        f"mkdir -p {_q(t)} && cp {_q(logo)} {_q(t + '/code-logo.png')} && chmod 644 {_q(t + '/code-logo.png')}",
        _write(t + "/code.script", PLYMOUTH_SCRIPT),
        _write(pfile, render_plymouth(shown)),
        *(["update-grub >/dev/null 2>&1"] if grub else []),
        f"update-alternatives --install /usr/share/plymouth/themes/default.plymouth default.plymouth {_q(pfile)} 300 >/dev/null",
        f"update-alternatives --set default.plymouth {_q(pfile)} >/dev/null",
        "update-initramfs -u >/dev/null",
        _write(m, f"hide_menu={'yes' if hide_menu else 'no'}\n"),
    ])


def disable_script(layout: Layout = DEFAULT) -> str:
    g, t, md = (str(layout.p(x)) for x in (layout.grub_cfg, layout.theme_dir, layout.marker_dir))
    pfile = f"{t}/code.plymouth"
    return "\n".join([
        "set -e",
        f"rm -f {_q(g)}",
        f"update-alternatives --remove default.plymouth {_q(pfile)} >/dev/null 2>&1 || true",
        f"rm -rf {_q(t)}",
        "update-grub >/dev/null 2>&1 || true",
        "update-initramfs -u >/dev/null",
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


def enable(layout: Layout = DEFAULT, run: Callable | None = None, out: Callable[[str], None] = lambda s: None,
           checks: list[Check] | None = None, logo: Path | None = None, which: Callable = None) -> tuple[bool, str]:
    import shutil
    which = which or shutil.which
    try:
        logo = logo or logo_path()
        checks = checks if checks is not None else preflight(layout, which=which, logo=logo)
        why = blocked(checks)
        if why:
            return False, why
        grub = bool(which("update-grub")) and layout.p(layout.grub_menu).exists()
        hide = grub and all(c.ok for c in checks)               # another OS on the disk: the menu is left alone
        rc = _run(layout, enable_script(layout, logo, hide_menu=hide, grub=grub), run, out)
        ok, text = kiosk._result_text(rc, on_text(hide), "Could not turn quiet boot on")
        if ok and not enabled(layout):
            return False, "The files were not written - nothing changed. Try again (Settings > Help > Copy log)."
        return ok, text
    except Exception as exc:  # never take Code down
        return False, f"Could not turn quiet boot on: {exc}"


def disable(layout: Layout = DEFAULT, run: Callable | None = None, out: Callable[[str], None] = lambda s: None) -> tuple[bool, str]:
    try:
        rc = _run(layout, disable_script(layout), run, out)
        ok, text = kiosk._result_text(rc, OFF_TEXT, "Could not turn quiet boot off")
        if ok and enabled(layout):
            return False, "The files are still there. In a Terminal:  " + RECOVERY
        return ok, text
    except Exception as exc:
        return False, f"Could not turn quiet boot off: {exc}"
