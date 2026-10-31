"""0.5.0: Settings > Boot - the CodeAque boot screen (GRUB theme + Plymouth), installed with a backup and restored. Fake root + fake tools."""
import os
import subprocess
from pathlib import Path

from atarilauncher import bootscreen, create


def fake_tools(tmp_path, root, fail=False):
    b = tmp_path / "bin"
    b.mkdir()
    cfg = Path(root) / "boot/grub/grub.cfg"
    (b / "update-grub").write_text(
        "#!/bin/sh\n" + ("exit 1\n" if fail else "") +
        f'mkdir -p {cfg.parent}\nif [ -f {root}/etc/default/grub.d/zzz-codeaque-boot.cfg ]; then '
        f'printf "set theme=/boot/grub/themes/codeaque/theme.txt\\nset timeout=5\\nmenuentry \'CodeAque GNU/Linux\' {{\\n}}\\nmenuentry \\"Windows\\" {{\\n}}\\n" > {cfg}; '
        f'else printf "set timeout=10\\nmenuentry \'Linux Mint\' {{\\n}}\\n" > {cfg}; fi\n')
    (b / "plymouth-set-default-theme").write_text(f"#!/bin/sh\nif [ -n \"$1\" ]; then echo $1 > {tmp_path}/ply; else cat {tmp_path}/ply 2>/dev/null || echo mint-logo; fi\n")
    (b / "update-initramfs").write_text("#!/bin/sh\nexit 0\n")
    for f in b.iterdir():
        f.chmod(0o755)
    env = dict(os.environ, PATH=f"{b}:/usr/bin:/bin")
    return env


def run(script, env):
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env, timeout=60)


def test_install_backup_readback_and_restore(tmp_path):
    root = tmp_path / "root"
    (root / "etc/default").mkdir(parents=True)
    (root / "etc/default/grub").write_text("GRUB_DEFAULT=0\n")
    lay = bootscreen.Layout(str(root))
    env = fake_tools(tmp_path, root)
    p = run(bootscreen.install_script(lay), env)
    assert p.returncode == 0 and "OK" in p.stdout and "WINDOWS=yes" in p.stdout, p.stderr
    th = root / "boot/grub/themes/codeaque"
    assert (th / "theme.txt").is_file() and (th / "background.png").is_file() and (th / "select_c.png").is_file()
    text = (th / "theme.txt").read_text()
    assert "Starting CodeAque in %d s" in text and "boot_menu" in text
    gd = (root / "etc/default/grub.d/zzz-codeaque-boot.cfg").read_text()
    assert "GRUB_DISABLE_OS_PROBER=true" in gd and "GRUB_TIMEOUT=5" in gd and "themes/codeaque/theme.txt" in gd
    assert os.access(root / "etc/grub.d/35_codeaque_windows", os.X_OK)
    ply = root / "usr/share/plymouth/themes/codeaque"
    assert (ply / "codeaque.plymouth").is_file() and (ply / "rain-0.png").is_file() and "ANIM = 1" in (ply / "codeaque.script").read_text()
    assert (tmp_path / "ply").read_text().strip() == "codeaque"
    assert (root / "var/lib/atari-launcher/boot-backup/grub").read_text() == "GRUB_DEFAULT=0\n"
    assert (root / "var/lib/atari-launcher/boot-backup/plymouth").read_text().strip() == "mint-logo"
    assert bootscreen.installed(lay)
    assert bootscreen.read_back(lay)[0].endswith("CodeAque") and "yes" in bootscreen.read_back(lay)[1]
    p = run(bootscreen.restore_script(lay), env)
    assert p.returncode == 0 and "OK" in p.stdout, p.stderr
    assert not th.exists() and not ply.exists() and not bootscreen.installed(lay)
    assert (tmp_path / "ply").read_text().strip() == "mint-logo"
    assert "codeaque" not in (root / "boot/grub/grub.cfg").read_text()


def test_failed_update_grub_puts_everything_back(tmp_path):
    root = tmp_path / "root"
    (root / "etc/default").mkdir(parents=True)
    (root / "etc/default/grub").write_text("GRUB_DEFAULT=0\n")
    lay = bootscreen.Layout(str(root))
    p = run(bootscreen.install_script(lay), fake_tools(tmp_path, root, fail=True))
    assert p.returncode != 0 and "putting the old files back" in p.stderr
    assert not bootscreen.installed(lay) and not (root / "boot/grub/themes/codeaque").exists()
    assert (root / "etc/default/grub").read_text() == "GRUB_DEFAULT=0\n"


def test_static_fallback_and_no_partitioning():
    assert "ANIM = 0" in bootscreen.PLYMOUTH_STATIC and "ANIM = 1" in bootscreen.PLYMOUTH_SCRIPT
    s = bootscreen.install_script()
    for bad in ("parted", "sgdisk", "mkfs", "efibootmgr", "ntfsresize", "fdisk"):
        assert bad not in s
    assert "bootmgfw.efi" in bootscreen.WIN_ENTRY and "Windows" in bootscreen.WIN_ENTRY


def test_assets_exist_and_no_windows_logo_source_kept():
    names = {p.name for p in bootscreen.ASSETS.iterdir()}
    assert {"background-1920x1080.png", "background-1366x768.png", "code-glow.png", "rain-0.png", "select_c.png"} <= names


def test_windows_entry_and_reboot(tmp_path):
    g = tmp_path / "grub.cfg"
    g.write_text("menuentry 'Linux Mint 22' {\n}\nmenuentry 'Windows Boot Manager (on /dev/nvme0n1p1)' --class windows {\n}\n")
    assert create.windows_entry([str(g)]) == "Windows Boot Manager (on /dev/nvme0n1p1)"
    assert create.reboot_commands("W")[0] == ["grub-reboot", "W"]
    g.write_text("menuentry 'Linux Mint 22' {\n}\n")
    assert create.windows_entry([str(g)]) == ""


def test_find_unreal(tmp_path):
    ed = tmp_path / "UnrealEngine" / "Linux_Unreal_Engine_5.6" / "Engine/Binaries/Linux/UnrealEditor"
    ed.parent.mkdir(parents=True)
    ed.write_text("#!/bin/sh\n")
    ed.chmod(0o755)
    assert create.find_unreal(home=tmp_path) == str(ed)
    assert create.find_unreal(home=tmp_path / "none", roots=[tmp_path / "none"]) == ""
    assert create.find_unreal(custom=str(ed), roots=[]) == str(ed)


import pytest  # noqa: E402

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from tests.test_ui_keys import app  # noqa: E402,F401
from tests.test_xemuconfig import make_ui  # noqa: E402


def test_boot_and_create_pages_confirm_first(app, tmp_path, monkeypatch):
    ui = make_ui(app, tmp_path, monkeypatch, tmp_path / "home")
    try:
        b = ui.backend
        assert any(r.get("kind") == "bootpage" for r in b.setupRows())
        ran = []
        assert b._boot_activate("bootinstall", run=lambda s, w: ran.append(w)) == "refresh" and not ran
        assert next(r for r in b.pageRows("boot") if r.get("id") == "bootinstall")["value"] == "CONFIRM"
        b._boot_activate("bootinstall", run=lambda s, w: ran.append((s, w)))
        assert ran and "update-grub" in ran[0][0]
        b._boot_activate("bootanim", run=None)
        assert b.store.get_pref("boot_anim", True) is False
        b._boot_activate("bootrestore", run=lambda s, w: ran.append(w))
        assert len(ran) == 1
        b._boot_activate("bootrestore", run=lambda s, w: ran.append(w))
        assert ran[-1].startswith("Restoring")
        assert b.pageTitle("create") == "CREATE"
        ids = [r.get("id") for r in b.pageRows("create")]
        assert {"crue", "cruelink", "cruepick", "crgodot", "crrbx"} <= set(ids)
        monkeypatch.setattr(create, "windows_entry", lambda *a: "Windows Boot Manager")
        assert "crwin" in [r.get("id") for r in b.pageRows("create")]
        assert b.pageActivate("create", "crwin") == "refresh"
        assert next(r for r in b.pageRows("create") if r.get("id") == "crwin")["value"] == "CONFIRM"
        assert b.pageActivate("create", "cruepick") == "browse:unreal"
    finally:
        ui.close()


def test_quiet_start_keeps_the_hidden_menu_and_sets_the_splash(tmp_path):
    assert "GRUB_TIMEOUT_STYLE" not in bootscreen.grub_defaults(quiet=True) and "quiet splash" in bootscreen.grub_defaults(quiet=True)
    assert "GRUB_TIMEOUT_STYLE=menu" in bootscreen.grub_defaults(quiet=False)
    root = tmp_path / "root"
    (root / "etc/default").mkdir(parents=True)
    (root / "etc/plymouth").mkdir(parents=True)
    (root / "etc/plymouth/plymouthd.conf").write_text("[Daemon]\nTheme=code\nShowDelay=5\n")
    lay = bootscreen.Layout(str(root))
    p = run(bootscreen.install_script(lay, quiet=True), fake_tools(tmp_path, root))
    assert p.returncode == 0 and "OK" in p.stdout, p.stderr
    conf = (root / "etc/plymouth/plymouthd.conf").read_text()
    assert "Theme=codeaque" in conf and "ShowDelay=0" in conf and "Theme=code\n" not in conf
    st = bootscreen.status(lay, quiet_on=True, cmdline="BOOT_IMAGE=/vmlinuz root=UUID=x ro quiet splash")
    assert {k: st[k] for k in {"installed": True, "splash": True, "theme": "codeaque", "quiet": True, "splash_arg": True, "quiet_arg": True}} == {"installed": True, "splash": True, "theme": "codeaque", "quiet": True, "splash_arg": True, "quiet_arg": True}
    line = bootscreen.status_line(st)
    assert "installed: yes" in line and "splash active: yes" in line and "Quiet start: on" in line
    assert "no 'splash'" in bootscreen.status_line(dict(st, splash_arg=False))
    run(bootscreen.restore_script(lay), fake_tools(tmp_path / "b", root) if (tmp_path / "b").mkdir() is None else None)
    assert "Theme=code\n" in (root / "etc/plymouth/plymouthd.conf").read_text()


def test_quiet_boot_uses_the_codeaque_splash_when_installed():
    from atarilauncher import quietboot
    s = quietboot.enable_script(logo=bootscreen.ASSETS / "code-glow.png")
    assert "PT=codeaque" in s and 'plymouth-set-default-theme "$PT"' in s


def test_login_screen_branding_and_restore(tmp_path):
    root = tmp_path / "root"
    (root / "etc/default").mkdir(parents=True)
    (root / "usr/share/slick-greeter").mkdir(parents=True)
    g = root / "etc/lightdm/slick-greeter.conf"
    g.parent.mkdir(parents=True)
    g.write_text("[Greeter]\nbackground=/usr/share/backgrounds/linuxmint/default_background.jpg\ntheme-name=Mint-Y\n")
    lay = bootscreen.Layout(str(root))
    env = fake_tools(tmp_path, root)
    p = run(bootscreen.install_script(lay), env)
    assert p.returncode == 0 and "GREETER=yes" in p.stdout, p.stderr
    text = g.read_text()
    assert "greeter-background.png" in text and "logo=/usr/share/codeaque/boot/blank.png" in text and "theme-name=Mint-Y" in text
    assert "linuxmint" not in text and (root / "usr/share/codeaque/boot/blank.png").is_file()
    assert run(bootscreen.restore_script(lay), env).returncode == 0
    assert "linuxmint/default_background.jpg" in g.read_text() and not (root / "usr/share/codeaque").exists()


def test_firmware_note_is_honest():
    assert "cannot be changed" in bootscreen.FIRMWARE_NOTE


def test_only_codeaque_and_windows_and_restore_turns_mint_entries_back_on(tmp_path):
    root = tmp_path / "root"
    (root / "etc/default").mkdir(parents=True)
    (root / "etc/default/grub").write_text("GRUB_DEFAULT=0\n")
    gd = root / "etc/grub.d"
    gd.mkdir(parents=True)
    for n in ("10_linux", "30_os-prober"):
        (gd / n).write_text("#!/bin/sh\n")
        (gd / n).chmod(0o755)
    lay = bootscreen.Layout(str(root))
    env = fake_tools(tmp_path, root)
    p = run(bootscreen.install_script(lay), env)
    assert p.returncode == 0, p.stderr
    assert not os.access(gd / "10_linux", os.X_OK) and not os.access(gd / "30_os-prober", os.X_OK)
    assert os.access(gd / "06_codeaque", os.X_OK) and not (root / "etc/default/codeaque-recovery").exists()
    p = run(bootscreen.install_script(lay, recovery=True), env)
    assert p.returncode == 0 and os.access(gd / "10_linux", os.X_OK) and (root / "etc/default/codeaque-recovery").exists()
    p = run(bootscreen.install_script(lay), env)
    p = run(bootscreen.restore_script(lay), env)
    assert p.returncode == 0, p.stderr
    assert os.access(gd / "10_linux", os.X_OK) and os.access(gd / "30_os-prober", os.X_OK) and not (gd / "06_codeaque").exists()


def test_codeaque_menu_entry_script_output(tmp_path):
    b = tmp_path / "bin"
    b.mkdir()
    (b / "grub-probe").write_text("#!/bin/sh\necho 1111-UUID\n")
    (b / "grub-mkrelpath").write_text("#!/bin/sh\necho \"$1\"\n")
    for f in b.iterdir():
        f.chmod(0o755)
    script = bootscreen.MENU_ENTRY.replace("/boot/", str(tmp_path) + "/boot/")
    (tmp_path / "boot").mkdir()
    (tmp_path / "boot/vmlinuz").write_text("")
    (tmp_path / "boot/initrd.img").write_text("")
    env = dict(os.environ, PATH=f"{b}:/usr/bin:/bin", GRUB_CMDLINE_LINUX="", GRUB_CMDLINE_LINUX_DEFAULT="quiet splash")
    out = subprocess.run(["sh", "-c", script], capture_output=True, text=True, env=env).stdout
    assert 'menuentry "CodeAque"' in out and "root=UUID=1111-UUID ro" in out and "quiet splash" in out
    assert "search --no-floppy --fs-uuid --set=root 1111-UUID" in out and "recovery" not in out
    assert 'width = 48%' in bootscreen.theme_txt()
