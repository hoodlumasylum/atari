"""Settings > Boot: the CodeAque boot screen for dual-boot computers (GRUB theme + Plymouth splash), and putting the old one back.

Made from Code's own final boot art (docs/branding/codeaque-boot-art-clean.png: the four-pane window shape was replaced by an original
ankh made of falling-code glyphs, and the baked-in text and bar were painted out - they are live in Plymouth; scripts/clean_boot_art.py + scripts/make_boot_assets.py build the pictures). The menu entries are plain gold text:
"CodeAque" (default) and "Windows"; the distro's "Advanced options" stay as a small last line for recovery.

What Install does (as root, after you confirm, in CodeAque's password box):
  1. backs up /etc/default/grub, CodeAque's own grub.d file, any old theme folder and the Plymouth choice to /var/lib/atari-launcher/boot-backup
     (only the first time, so Restore always goes back to how the computer was);
  2. copies the theme to /boot/grub/themes/codeaque and the splash to /usr/share/plymouth/themes/codeaque;
  3. writes /etc/default/grub.d/zzz-codeaque-boot.cfg (theme, 5-second countdown, menu shown, os-prober ON so Windows is listed) and
     /etc/grub.d/35_codeaque_windows (a "Windows" entry that starts \\EFI\\Microsoft\\Boot\\bootmgfw.efi - nothing on Windows is written);
  4. runs update-grub and update-initramfs, then reads grub.cfg back (theme line, "CodeAque", "Windows"). Any failure puts the old files back.
It never touches partitions, the disk layout or firmware settings. Not tested on a real computer's boot (only with fake tools here)."""
from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path

ASSETS = Path(__file__).with_name("bootscreen")
GRUB_THEME_DIR = "/boot/grub/themes/codeaque"
PLY_DIR = "/usr/share/plymouth/themes/codeaque"
BACKUP_DIR = "/var/lib/atari-launcher/boot-backup"
GRUB_D = "/etc/default/grub.d/zzz-codeaque-boot.cfg"
WIN_SCRIPT = "/etc/grub.d/35_codeaque_windows"
GRUB_CFG = "/boot/grub/grub.cfg"
FONT_TTF = ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
GOLD, GOLD_LIGHT, DIM = "#e2b64a", "#ffe9a8", "#bda772"


def theme_txt() -> str:
    """GRUB theme: positions in % so it fits 1366x768 up to 4K; big fonts (made with grub-mkfont at install time)."""
    return f"""# CodeAque boot menu - made by CodeAque (Settings > Boot)
title-text: ""
desktop-image: "background.png"
desktop-image-scale-method: "crop"
desktop-color: "#050807"
terminal-font: "CodeAque Regular 20"
terminal-box: "terminal_box_*.png"

+ boot_menu {{
    left = 33%
    top = 76%
    width = 34%
    height = 14%
    item_font = "CodeAque Regular 36"
    selected_item_font = "CodeAque Regular 36"
    item_color = "{GOLD}"
    selected_item_color = "#140d02"
    item_height = 50
    item_padding = 18
    item_spacing = 8
    icon_width = 0
    icon_height = 0
    selected_item_pixmap_style = "select_*.png"
    scrollbar = false
}}

+ label {{
    id = "__timeout__"
    left = 25%
    top = 92%
    width = 50%
    align = "center"
    color = "{GOLD_LIGHT}"
    font = "CodeAque Regular 24"
    text = "Starting CodeAque in %d s   -   Up / Down and Enter to choose"
}}
"""


def grub_defaults(quiet: bool = False) -> str:
    """quiet = Quiet boot is on: its hidden menu (Shift / Esc shows it) is kept; only the theme and the splash change."""
    menu = "" if quiet else 'GRUB_TIMEOUT_STYLE=menu\nGRUB_TIMEOUT=5\n'
    return (f'# BEGIN CodeAque boot screen (Settings > Boot). Remove with "Restore old boot screen".\n'
            'GRUB_DISTRIBUTOR="CodeAque"\n'
            + menu +
            'GRUB_DISABLE_OS_PROBER=false\n'
            'GRUB_GFXMODE="1920x1080,1366x768,auto"\n'
            'GRUB_GFXPAYLOAD_LINUX=keep\n'
            'GRUB_TERMINAL_OUTPUT=gfxterm\n'
            f'GRUB_THEME="{GRUB_THEME_DIR}/theme.txt"\n'
            'GRUB_CMDLINE_LINUX_DEFAULT="$GRUB_CMDLINE_LINUX_DEFAULT quiet splash"\n'
            '# END CodeAque boot screen\n')


WIN_ENTRY = r"""#!/bin/sh
# CodeAque: a plain "Windows" entry (starts Windows' own boot manager; nothing on Windows is changed). Added by Settings > Boot.
set -e
for f in /boot/efi/EFI/Microsoft/Boot/bootmgfw.efi /boot/efi/EFI/microsoft/boot/bootmgfw.efi; do
  if [ -f "$f" ]; then
    cat <<'GRUBEOF'
menuentry "Windows" --class windows {
    insmod part_gpt
    insmod fat
    insmod chain
    search --no-floppy --file --set=root /EFI/Microsoft/Boot/bootmgfw.efi
    chainloader /EFI/Microsoft/Boot/bootmgfw.efi
}
GRUBEOF
    exit 0
  fi
done
exit 0
"""


def plymouth_theme() -> str:
    return f"""[Plymouth Theme]
Name=CodeAque
Description=CodeAque boot art with a gold glow, a live spinner and an emerald progress line
ModuleName=script

[script]
ImageDir={PLY_DIR}
ScriptFile={PLY_DIR}/codeaque.script
"""


PLYMOUTH_SCRIPT_TEMPLATE = """// CodeAque splash (CodeAque Settings > Boot). The art fills the screen; green symbols fall in columns (our own glyphs: 0/1 and
// hieroglyph-style marks); the eyes, the logo and the ankh glow slowly; a live green / gold progress bar and text; fade in and out.
// Light on old GPUs: ~24 moving sprites and one pulsing glow; no drawing per frame. ANIM = 0 is the still version.
ANIM = @ANIM@;
Window.SetBackgroundTopColor(0, 0, 0);
Window.SetBackgroundBottomColor(0, 0, 0);
W = Window.GetWidth(); H = Window.GetHeight(); X = Window.GetX(); Y = Window.GetY();
bg.image = Image("background-1920x1080.png");
k = Math.Max(W / bg.image.GetWidth(), H / bg.image.GetHeight());
bw = bg.image.GetWidth() * k; bh = bg.image.GetHeight() * k;
bx = X + W / 2 - bw / 2; by = Y + H / 2 - bh / 2;
bg.image = bg.image.Scale(bw, bh);
bg.sprite = Sprite(bg.image); bg.sprite.SetX(bx); bg.sprite.SetY(by); bg.sprite.SetZ(0);
glow.image = Image("code-glow.png").Scale(bw, bh);
glow.sprite = Sprite(glow.image); glow.sprite.SetX(bx); glow.sprite.SetY(by); glow.sprite.SetZ(5);
NCOL = 24;
if (ANIM) {
  for (j = 0; j < 6; j++) rimg[j] = Image("rain-" + j + ".png");
  rh = rimg[0].GetHeight();
  for (j = 0; j < NCOL; j++) {
    side = j % 2;
    // columns stay at the sides (over the pillars and the sky), away from the menu area in the middle
    if (side == 0) cx = X + W * (0.02 + 0.28 * Math.Random()); else cx = X + W * (0.70 + 0.28 * Math.Random());
    drop[j].sprite = Sprite(rimg[j % 6]);
    drop[j].sprite.SetX(cx);
    drop[j].y = Y - rh - Math.Random() * H;
    drop[j].speed = 2 + Math.Random() * 4;
    drop[j].sprite.SetY(drop[j].y);
    drop[j].sprite.SetZ(2);
    drop[j].sprite.SetOpacity(0);
  }
}
bar_w = W * 0.34; bar_x = X + W / 2 - bar_w / 2; bar_y = Y + H * 0.865;
track.image = Image("code-track.png").Scale(bar_w, 6);
track.sprite = Sprite(track.image); track.sprite.SetX(bar_x); track.sprite.SetY(bar_y); track.sprite.SetZ(6);
line.base = Image("code-line.png");
line.sprite = Sprite(); line.sprite.SetX(bar_x); line.sprite.SetY(bar_y); line.sprite.SetZ(7);
head.image = Image("code-head.png");
head.sprite = Sprite(head.image); head.sprite.SetY(bar_y - 3); head.sprite.SetX(bar_x); head.sprite.SetZ(8);
t1.image = Image.Text("CODEAQUE  OS", 0.89, 0.71, 0.29, 1, "Sans Bold 26");
t1.sprite = Sprite(t1.image); t1.sprite.SetX(X + W / 2 - t1.image.GetWidth() / 2); t1.sprite.SetY(Y + H * 0.765); t1.sprite.SetZ(6);
t2.image = Image.Text("SYSTEM INITIALISING...", 0.83, 0.93, 0.85, 1, "Sans 16");
t2.sprite = Sprite(t2.image); t2.sprite.SetX(X + W / 2 - t2.image.GetWidth() / 2); t2.sprite.SetY(Y + H * 0.815); t2.sprite.SetZ(6);
t = 0; fade = 0; quitting = 0; progress = 0;
fun refresh() {
  t++;
  if (quitting) fade = Math.Max(0, fade - 0.05); else fade = Math.Min(1, fade + 0.03);
  bg.sprite.SetOpacity(fade); track.sprite.SetOpacity(fade); line.sprite.SetOpacity(fade); head.sprite.SetOpacity(fade);
  t1.sprite.SetOpacity(fade); t2.sprite.SetOpacity(fade * (0.75 + 0.25 * Math.Sin(t / 12)));
  glow.sprite.SetOpacity(fade * (0.25 + 0.35 * (0.5 + 0.5 * Math.Sin(t / 40))));     // slow pulse, about 5 s
  if (ANIM) {
    for (j = 0; j < NCOL; j++) {
      drop[j].y = drop[j].y + drop[j].speed;
      if (drop[j].y > Y + H) drop[j].y = Y - rh;
      drop[j].sprite.SetY(drop[j].y);
      drop[j].sprite.SetOpacity(fade * 0.8);
    }
  }
}
Plymouth.SetRefreshFunction(refresh);
fun progress_cb(duration, p) {
  if (p > progress) progress = p;
  w = Math.Max(1, Math.Int(bar_w * progress));
  line.sprite.SetImage(line.base.Scale(w, 6));
  head.sprite.SetX(bar_x + w - head.image.GetWidth() / 2);
}
Plymouth.SetBootProgressFunction(progress_cb);
fun quit_cb() { quitting = 1; }
Plymouth.SetQuitFunction(quit_cb);
"""
PLYMOUTH_SCRIPT = PLYMOUTH_SCRIPT_TEMPLATE.replace("@ANIM@", "1")
PLYMOUTH_STATIC = PLYMOUTH_SCRIPT_TEMPLATE.replace("@ANIM@", "0")     # still version (Settings > Boot > Animated splash: OFF)



@dataclass
class Layout:
    """Every path the scripts touch, under a root (tests use a temporary folder)."""
    root: str = "/"

    def p(self, path: str) -> str:
        return str(Path(self.root) / path.lstrip("/")) if self.root != "/" else path


def _q(s) -> str:
    return shlex.quote(str(s))


def _write(path: str, text: str, mode: str = "644") -> str:
    return f"mkdir -p {_q(str(Path(path).parent))}\nprintf %s {_q(text)} > {_q(path)}\nchmod {mode} {_q(path)}"


def install_script(lay: Layout = Layout(), assets: Path = ASSETS, animated: bool = True, quiet: bool = False) -> str:
    th, ply, bk = lay.p(GRUB_THEME_DIR), lay.p(PLY_DIR), lay.p(BACKUP_DIR)
    gd, ws, cfg, dg = lay.p(GRUB_D), lay.p(WIN_SCRIPT), lay.p(GRUB_CFG), lay.p("/etc/default/grub")
    lines = [
        "set -u", "STEP=1",
        f"restore() {{ echo \"failed at step $STEP - putting the old files back\" >&2; {restore_body(lay)}; exit 1; }}",
        "trap restore ERR", "set -E",
        # 1. backup (first time only)
        f"if [ ! -f {_q(bk + '/done')} ]; then mkdir -p {_q(bk)}; "
        f"[ -f {_q(dg)} ] && cp -a {_q(dg)} {_q(bk + '/grub')}; "
        f"[ -d {_q(th)} ] && cp -a {_q(th)} {_q(bk + '/theme')}; "
        f"if command -v plymouth-set-default-theme >/dev/null 2>&1; then plymouth-set-default-theme > {_q(bk + '/plymouth')} 2>/dev/null || true; fi; "
        f"touch {_q(bk + '/done')}; fi",
        "STEP=2",
        f"mkdir -p {_q(th)} {_q(ply)}",
        f"cp {_q(str(assets / 'background-1920x1080.png'))} {_q(th + '/background.png')}",
        f"cp {_q(str(assets / 'background-1366x768.png'))} {_q(th + '/background-1366x768.png')}",
        f"cp {_q(str(assets))}/select_*.png {_q(th)}/",
        f"for p in n s e w ne nw se sw c; do cp {_q(str(assets))}/select_c.png {_q(th)}/terminal_box_$p.png; done",
        _write(th + "/theme.txt", theme_txt()),
        # fonts: GRUB needs .pf2; made from DejaVu (on every Mint / Ubuntu) when grub-mkfont is there, else GRUB's own font is used
        "if command -v grub-mkfont >/dev/null 2>&1; then for f in " + " ".join(_q(f) for f in FONT_TTF) + "; do "
        f"if [ -f \"$f\" ]; then for s in 20 24 36; do grub-mkfont -n CodeAque -s $s -o {_q(th)}/codeaque-$s.pf2 \"$f\" >/dev/null 2>&1 || true; done; break; fi; done; fi",
        f"cp {_q(str(assets))}/background-1920x1080.png {_q(str(assets))}/code-glow.png {_q(str(assets))}/code-line.png "
        f"{_q(str(assets))}/code-track.png {_q(str(assets))}/code-head.png {_q(str(assets))}/rain-*.png {_q(ply)}/",
        _write(ply + "/codeaque.script", PLYMOUTH_SCRIPT if animated else PLYMOUTH_STATIC),
        _write(ply + "/codeaque.plymouth", plymouth_theme()),
        "STEP=3",
        _write(gd, grub_defaults(quiet)),
        # NVIDIA's own driver shows no splash without early mode setting
        f"if lsmod 2>/dev/null | grep -q '^nvidia_drm'; then echo 'GRUB_CMDLINE_LINUX_DEFAULT=\"$GRUB_CMDLINE_LINUX_DEFAULT nvidia-drm.modeset=1\"' >> {_q(gd)}; fi",
        _write(ws, WIN_ENTRY, "755"),
        "STEP=4",
        "update-grub >/dev/null 2>&1",
        "STEP=5",
        f"grep -q {_q('theme')} {_q(cfg)} && grep -q CodeAque {_q(cfg)}",
        "STEP=6",
        "if command -v plymouth-set-default-theme >/dev/null 2>&1; then plymouth-set-default-theme codeaque >/dev/null 2>&1 || true; fi",
        f"if command -v update-alternatives >/dev/null 2>&1 && [ -d /etc/alternatives ] && [ {_q(lay.root)} = / ]; then "
        f"update-alternatives --install /usr/share/plymouth/themes/default.plymouth default.plymouth {PLY_DIR}/codeaque.plymouth 310 >/dev/null 2>&1 || true; "
        f"update-alternatives --set default.plymouth {PLY_DIR}/codeaque.plymouth >/dev/null 2>&1 || true; fi",
        # show the splash at once (a fast SSD otherwise reaches CodeAque before the default delay ends)
        f"PC={_q(lay.p('/etc/plymouth/plymouthd.conf'))}; mkdir -p \"$(dirname \"$PC\")\"; "
        f"[ -f {_q(bk + '/plymouthd.conf')} ] || {{ [ -f \"$PC\" ] && cp -a \"$PC\" {_q(bk + '/plymouthd.conf')}; }} || true; "
        "grep -q '^\\[Daemon\\]' \"$PC\" 2>/dev/null || printf '[Daemon]\\n' >> \"$PC\"; "
        "sed -i '/^Theme=/d;/^ShowDelay=/d;/^DeviceTimeout=/d' \"$PC\"; "
        "sed -i 's/^\\[Daemon\\]$/[Daemon]\\nTheme=codeaque\\nShowDelay=0\\nDeviceTimeout=8/' \"$PC\"",
        "if command -v update-initramfs >/dev/null 2>&1; then update-initramfs -u >/dev/null 2>&1; fi",
        f"INITRD={_q(lay.p('/boot/initrd.img-'))}$(uname -r)",
        "if [ -f \"$INITRD\" ] && command -v lsinitramfs >/dev/null 2>&1; then "
        "if lsinitramfs \"$INITRD\" | grep -q 'plymouth/themes/codeaque/codeaque.plymouth'; then echo SPLASH=yes; else echo SPLASH=no; fi; fi",
        "STEP=7",
        greeter_script(lay, assets),
        f"grep -q 'menuentry .Windows' {_q(cfg)} && echo 'WINDOWS=yes' || echo 'WINDOWS=no'",
        "echo OK",
    ]
    return "\n".join(lines) + "\n"


SHARE = "/usr/share/codeaque/boot"
GREETER = "/etc/lightdm/slick-greeter.conf"


def greeter_script(lay: Layout = Layout(), assets: Path = ASSETS) -> str:
    """The login screen (LightDM's slick greeter, Mint's default): CodeAque's art as the background and no distro logo. Only when the
    slick greeter is installed; the old file is backed up first (or noted as missing, so Restore deletes ours)."""
    sh, g, bk = lay.p(SHARE), lay.p(GREETER), lay.p(BACKUP_DIR)
    return (f"if [ -d {_q(lay.p('/usr/share/slick-greeter'))} ] || command -v slick-greeter >/dev/null 2>&1 || [ -f {_q(g)} ]; then "
            f"mkdir -p {_q(sh)} {_q(str(Path(g).parent))}; "
            f"cp {_q(str(assets / 'background-1920x1080.png'))} {_q(sh + '/greeter-background.png')}; "
            f"cp {_q(str(assets / 'blank.png'))} {_q(sh + '/blank.png')}; "
            f"if [ ! -e {_q(bk + '/greeter.saved')} ]; then if [ -f {_q(g)} ]; then cp -a {_q(g)} {_q(bk + '/slick-greeter.conf')}; fi; "
            f"touch {_q(bk + '/greeter.saved')}; fi; "
            f"[ -f {_q(g)} ] || printf '[Greeter]\\n' > {_q(g)}; "
            f"grep -q '^\\[Greeter\\]' {_q(g)} || printf '[Greeter]\\n' >> {_q(g)}; "
            f"sed -i '/^background=/d;/^logo=/d;/^other-monitors-logo=/d;/^draw-grid=/d;/^background-color=/d' {_q(g)}; "
            # slick-greeter.conf has one [Greeter] section: our keys go at its end
            f"printf '%s\\n' 'background={SHARE}/greeter-background.png' 'background-color=#050807' 'logo={SHARE}/blank.png' "
            f"'other-monitors-logo={SHARE}/blank.png' 'draw-grid=false' >> {_q(g)}; "
            "echo GREETER=yes; else echo GREETER=no; fi")


def restore_body(lay: Layout = Layout()) -> str:
    th, ply, bk = lay.p(GRUB_THEME_DIR), lay.p(PLY_DIR), lay.p(BACKUP_DIR)
    g = lay.p(GREETER)
    return (f"if [ -e {_q(bk + '/greeter.saved')} ]; then if [ -f {_q(bk + '/slick-greeter.conf')} ]; then "
            f"cp -a {_q(bk + '/slick-greeter.conf')} {_q(g)}; else rm -f {_q(g)}; fi; rm -f {_q(bk + '/greeter.saved')}; fi; "
            f"rm -rf {_q(lay.p(SHARE))}; rmdir {_q(str(Path(lay.p(SHARE)).parent))} 2>/dev/null || true; "
            f"rm -f {_q(lay.p(GRUB_D))} {_q(lay.p(WIN_SCRIPT))}; rm -rf {_q(th)} {_q(ply)}; "
            f"if [ -f {_q(bk + '/grub')} ]; then cp -a {_q(bk + '/grub')} {_q(lay.p('/etc/default/grub'))}; fi; "
            f"if [ -d {_q(bk + '/theme')} ]; then cp -a {_q(bk + '/theme')} {_q(th)}; fi; "
            f"if [ -f {_q(bk + '/plymouthd.conf')} ]; then cp -a {_q(bk + '/plymouthd.conf')} {_q(lay.p('/etc/plymouth/plymouthd.conf'))}; fi; "
            f"update-alternatives --remove default.plymouth {PLY_DIR}/codeaque.plymouth >/dev/null 2>&1 || true; "
            f"if [ -s {_q(bk + '/plymouth')} ] && command -v plymouth-set-default-theme >/dev/null 2>&1; then "
            f"plymouth-set-default-theme \"$(cat {_q(bk + '/plymouth')})\" >/dev/null 2>&1 || true; fi; "
            "update-grub >/dev/null 2>&1 || true; command -v update-initramfs >/dev/null 2>&1 && update-initramfs -u >/dev/null 2>&1 || true")


def restore_script(lay: Layout = Layout()) -> str:
    bk = lay.p(BACKUP_DIR)
    return ("set -u\n" + restore_body(lay) + "\n"
            f"rm -rf {_q(bk)}\n"
            f"if grep -q codeaque {_q(lay.p(GRUB_CFG))} 2>/dev/null; then echo STILL; exit 1; fi\necho OK\n")


def installed(lay: Layout = Layout()) -> bool:
    return Path(lay.p(GRUB_D)).is_file()


def read_back(lay: Layout = Layout()) -> list[str]:
    """Plain lines about what grub.cfg says now."""
    try:
        text = Path(lay.p(GRUB_CFG)).read_text(errors="replace")
    except OSError:
        return ["Could not read " + lay.p(GRUB_CFG) + " (normal when it is only readable by the administrator)."]
    out = ["Boot screen theme: " + ("CodeAque" if "themes/codeaque" in text else "the old one")]
    out.append("Windows in the menu: " + ("yes" if "Windows" in text else "no (none found)"))
    import re
    m = re.search(r"set timeout=(\d+)", text)
    out.append("Countdown: " + (m.group(1) + " s" if m else "unknown"))
    return out


def status(lay: Layout = Layout(), quiet_on: bool | None = None, cmdline: str | None = None) -> dict:
    """What the Boot screen page shows on its status line: installed, splash active, quiet start, and this start's kernel options."""
    try:
        conf = Path(lay.p("/etc/plymouth/plymouthd.conf")).read_text(errors="replace")
    except OSError:
        conf = ""
    import re
    m = re.search(r"^Theme=(\S+)", conf, re.M)
    theme = m.group(1) if m else ""
    if not theme:
        try:
            theme = Path(os.path.realpath(lay.p("/etc/alternatives/default.plymouth"))).stem
        except OSError:
            theme = ""
    if cmdline is None:
        try:
            cmdline = Path("/proc/cmdline").read_text()
        except OSError:
            cmdline = ""
    if quiet_on is None:
        from . import quietboot
        quiet_on = quietboot.enabled()
    return {"installed": installed(lay), "splash": theme == "codeaque" and Path(lay.p(PLY_DIR + "/codeaque.plymouth")).is_file(),
            "theme": theme or "unknown", "quiet": bool(quiet_on), "splash_arg": "splash" in cmdline.split(),
            "quiet_arg": "quiet" in cmdline.split()}


def status_line(st: dict) -> str:
    yn = lambda b: "yes" if b else "no"      # noqa: E731
    line = (f"Boot screen installed: {yn(st['installed'])}  |  CodeAque splash active: {yn(st['splash'])}"
            f" (Plymouth theme: {st['theme']})  |  Quiet start: {'on' if st['quiet'] else 'off'}")
    if not st["splash_arg"]:
        line += "\nThis start had no 'splash' in its kernel options, so no splash could show - Install (or Quiet boot) adds it."
    return line


FIRMWARE_NOTE = ("The Dell logo at the very first second comes from the computer's own firmware (BIOS) and cannot be changed by CodeAque. "
                 "After it, the CodeAque splash replaces the Linux Mint logo at start, restart and shut-down.")
