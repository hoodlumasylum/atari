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
    assert "GRUB_DISABLE_OS_PROBER=false" in gd and "GRUB_TIMEOUT=5" in gd and "themes/codeaque/theme.txt" in gd
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
