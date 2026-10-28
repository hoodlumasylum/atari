import os
import subprocess
import sys
from pathlib import Path

import pytest

from atarilauncher import kiosk, quietboot

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from tests.test_features_ui import conf, wait_for  # noqa: E402
from tests.test_ui_keys import Ui, app  # noqa: E402,F401


@pytest.fixture
def machine(tmp_path):
    """A fake root with Plymouth, GRUB (one system) and stand-ins for update-grub / update-initramfs / update-alternatives that log
    every call. FAIL=<name> in the environment makes that command fail."""
    root = tmp_path / "root"
    for d in ("usr/share/plymouth/themes", "etc/alternatives", "boot/grub", "usr/lib/x86_64-linux-gnu/plymouth", "etc/default"):
        (root / d).mkdir(parents=True)
    (root / "usr/lib/x86_64-linux-gnu/plymouth/script.so").write_text("")
    (root / "etc/alternatives/default.plymouth").write_text("mint-logo")
    (root / "boot/grub/grub.cfg").write_text("menuentry 'Linux Mint 22 Cinnamon' {\n}\nsubmenu 'Advanced options for Linux Mint' {\n}\n")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    log = tmp_path / "calls.log"
    for name in ("update-grub", "update-initramfs", "update-alternatives"):
        f = bin_ / name
        f.write_text(f'#!/bin/sh\necho "{name} $*" >> "{log}"\n[ "$FAIL" = "{name}" ] && exit 1\nexit 0\n')
        f.chmod(0o755)
    logo = tmp_path / "code-logo.png"
    logo.write_bytes(b"\x89PNG fake")
    lay = quietboot.Layout(root=root)
    return lay, bin_, log, logo


def run_script(script, bin_, fail=""):
    env = dict(os.environ, PATH=f"{bin_}:{os.environ['PATH']}", FAIL=fail)
    return subprocess.run(["sh", "-c", script], capture_output=True, text=True, env=env).returncode


def which_all(n):
    return "/usr/bin/" + n


def test_preflight_passes_on_a_single_system_mint(machine):
    lay, _, _, logo = machine
    cs = quietboot.preflight(lay, which=which_all, logo=logo)
    assert quietboot.blocked(cs) == "" and all(c.ok for c in cs)


@pytest.mark.parametrize("what,word", [("pkexec", "pkexec"), ("plymouth", "Plymouth"), ("script", "script module"), ("alt", "update-alternatives")])
def test_preflight_blocks_with_plain_english(machine, what, word):
    lay, _, _, logo = machine
    which = which_all
    if what == "pkexec":
        which = lambda n: None if n == "pkexec" else "/usr/bin/" + n  # noqa: E731
    if what == "plymouth":
        (lay.root / "usr/share/plymouth/themes").rmdir()
    if what == "script":
        (lay.root / "usr/lib/x86_64-linux-gnu/plymouth/script.so").unlink()
    if what == "alt":
        (lay.root / "etc/alternatives/default.plymouth").unlink()
    assert word in quietboot.blocked(quietboot.preflight(lay, which=which, logo=logo))


def test_another_operating_system_keeps_the_boot_menu_visible(machine):
    lay, bin_, log, logo = machine
    (lay.root / "boot/grub/grub.cfg").write_text("menuentry 'Linux Mint' {\n}\nmenuentry 'Windows Boot Manager (on /dev/sda1)' --class windows {\n}\n")
    cs = quietboot.preflight(lay, which=which_all, logo=logo)
    assert quietboot.blocked(cs) == "" and any("Windows Boot Manager" in c.text and not c.ok for c in cs)
    ok, text = quietboot.enable(lay, lambda cmd, out, cancel: run_script(cmd[3], bin_), checks=cs, logo=logo, which=which_all)
    assert ok and "menu was left visible" in text
    cfg = lay.p(lay.grub_cfg).read_text()
    assert "GRUB_TIMEOUT_STYLE=hidden" not in cfg and "quiet splash" in cfg                 # quiet text, but the menu is not hidden


def test_turning_it_on_writes_exactly_the_files_and_runs_the_rebuilds(machine):
    lay, bin_, log, logo = machine
    calls = []

    def run(cmd, out, cancel):
        calls.append(cmd)
        assert cmd[:3] == ["pkexec", "sh", "-c"]
        return run_script(cmd[3], bin_)
    ok, text = quietboot.enable(lay, run, logo=logo, which=which_all)
    assert ok and text.startswith("Quiet boot is ON") and "Shift" in text and "Esc" in text
    assert quietboot.enabled(lay)
    cfg = lay.p(lay.grub_cfg).read_text()
    assert "GRUB_TIMEOUT_STYLE=hidden" in cfg and "GRUB_TIMEOUT=2" in cfg                    # hidden, but Shift / Esc has a 2 second window
    assert '"$GRUB_CMDLINE_LINUX_DEFAULT quiet splash' in cfg                               # the user's own kernel options are kept
    theme = lay.p(lay.theme_dir)
    assert (theme / "code-logo.png").read_bytes() == logo.read_bytes()
    assert "ModuleName=script" in (theme / "code.plymouth").read_text() and "code-logo.png" in (theme / "code.script").read_text()
    seen = log.read_text()
    assert seen.index("update-grub") < seen.index("update-initramfs")
    assert "update-alternatives --install /usr/share/plymouth/themes/default.plymouth default.plymouth" in seen and "--set default.plymouth" in seen
    # nothing outside the three places was written
    written = sorted(str(p.relative_to(lay.root)) for p in lay.root.rglob("*") if p.is_file())
    assert [w for w in written if not w.startswith(("usr/share/plymouth/themes/code/", "etc/default/grub.d/", "etc/code-boot/"))] == [
        "boot/grub/grub.cfg", "etc/alternatives/default.plymouth", "usr/lib/x86_64-linux-gnu/plymouth/script.so"]


def test_the_plymouth_theme_points_at_the_real_install_path_not_the_test_folder(machine):
    lay, _, _, logo = machine
    text = quietboot.render_plymouth("/usr/share/plymouth/themes/code")
    assert "ImageDir=/usr/share/plymouth/themes/code" in text and "ScriptFile=/usr/share/plymouth/themes/code/code.script" in text
    assert "Mint" not in quietboot.PLYMOUTH_SCRIPT and "SetBackgroundTopColor(0, 0, 0)" in quietboot.PLYMOUTH_SCRIPT


def test_turning_it_off_removes_everything_and_gives_mint_its_splash_back(machine):
    lay, bin_, log, logo = machine
    assert quietboot.enable(lay, lambda c, o, x: run_script(c[3], bin_), logo=logo, which=which_all)[0]
    log.write_text("")
    ok, text = quietboot.disable(lay, lambda c, o, x: run_script(c[3], bin_))
    assert ok and text.startswith("Quiet boot is OFF") and not quietboot.enabled(lay)
    assert not lay.p(lay.grub_cfg).exists() and not lay.p(lay.theme_dir).exists() and not lay.p(lay.marker_dir).exists()
    seen = log.read_text()
    assert "update-alternatives --remove default.plymouth" in seen and "update-grub" in seen and "update-initramfs -u" in seen


@pytest.mark.parametrize("failing", ["update-grub", "update-alternatives", "update-initramfs"])
def test_a_failed_step_puts_everything_back(machine, failing):
    lay, bin_, log, logo = machine
    ok, text = quietboot.enable(lay, lambda c, o, x: run_script(c[3], bin_, fail=failing), logo=logo, which=which_all)
    assert not ok and "Could not turn quiet boot on" in text and not quietboot.enabled(lay)
    assert not lay.p(lay.grub_cfg).exists() and not lay.p(lay.theme_dir).exists() and not lay.p(lay.marker_dir).exists()
    if failing != "update-grub":
        assert "update-grub" in log.read_text()                       # the menu is rebuilt without our file


def test_a_closed_password_window_changes_nothing(machine):
    lay, bin_, log, logo = machine
    ok, text = quietboot.enable(lay, lambda c, o, x: 126, logo=logo, which=which_all)
    assert not ok and "nothing was changed" in text and not any(p.exists() for p in lay.files)


def test_without_grub_only_the_splash_is_changed(machine):
    lay, bin_, log, logo = machine
    (lay.root / "boot/grub/grub.cfg").unlink()
    which = lambda n: None if n == "update-grub" else "/usr/bin/" + n  # noqa: E731
    ok, text = quietboot.enable(lay, lambda c, o, x: run_script(c[3], bin_), logo=logo, which=which)
    assert ok and not lay.p(lay.grub_cfg).exists() and quietboot.enabled(lay) and "update-grub" not in log.read_text()


def test_recovery_text_names_the_exact_undo_commands():
    assert "rm /etc/default/grub.d/90-code-quiet.cfg" in quietboot.RECOVERY and "update-initramfs -u" in quietboot.RECOVERY
    assert "Shift" in quietboot.HOW_TO_SHOW_MENU and "Esc" in quietboot.HOW_TO_SHOW_MENU


def test_the_bundled_logo_exists_and_is_code_branding():
    assert quietboot.logo_path().is_file() and quietboot.logo_path().name == "code-logo.png"


def test_settings_row_and_screen(app, tmp_path, monkeypatch, machine):
    lay, bin_, log, logo = machine
    conf(tmp_path, "[steam]\nenabled = false\n")
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        b = ui.backend
        b._qb_layout = lay
        monkeypatch.setattr(quietboot, "logo_path", lambda: logo)
        monkeypatch.setattr(quietboot, "preflight", (lambda orig: lambda layout=lay, **kw: orig(layout, which=which_all, logo=logo))(quietboot.preflight))
        row = [r for r in b.setupRows() if r.get("kind") == "quietbootpage"][0]
        assert row["value"] == "OFF" and "Mint" in row["title"]
        rows = b.pageRows("quietboot")
        text = " ".join(r.get("title", "") for r in rows)
        assert "Shift" in text and "Windows" in text and "puts everything back" in text
        assert [r.get("id") for r in rows if r["kind"] != "info"] == ["qbon", "back"]
        orig_en, orig_dis = quietboot.enable, quietboot.disable
        monkeypatch.setattr(quietboot, "enable", lambda l: orig_en(l, lambda c, o, x: run_script(c[3], bin_), logo=logo, which=which_all))
        monkeypatch.setattr(quietboot, "disable", lambda l: orig_dis(l, lambda c, o, x: run_script(c[3], bin_)))
        assert b.pageActivate("quietboot", "qbon") == "refresh"
        assert wait_for(app, lambda: quietboot.enabled(lay) and not b._qb_busy, 15), b.toast
        assert [r.get("id") for r in b.pageRows("quietboot") if r["kind"] != "info"] == ["qboff", "back"]
        assert [r for r in b.setupRows() if r.get("kind") == "quietbootpage"][0]["value"] == "ON"
        assert b.pageActivate("quietboot", "qboff") == "refresh"
        assert wait_for(app, lambda: not quietboot.enabled(lay) and not b._qb_busy, 15)
        qml = (Path(quietboot.__file__).parent / "qml" / "Main.qml").read_text()
        assert 'r.kind === "quietbootpage"' in qml and 'openPage("quietboot")' in qml and b.pageTitle("quietboot") == "QUIET BOOT"
    finally:
        ui.close()
