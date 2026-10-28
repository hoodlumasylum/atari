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
    """A fake root with Plymouth, GRUB (one system) and stand-ins for update-grub / update-initramfs / update-alternatives /
    plymouth-set-default-theme that log every call and behave like the real ones (update-grub puts the settings of the grub.d file
    into grub.cfg; the theme tool remembers the theme). FAIL=<name> makes that command fail; GRUB_IGNORE=1 makes GRUB ignore our file."""
    root = tmp_path / "root"
    for d in ("usr/share/plymouth/themes", "etc/alternatives", "boot/grub", "usr/lib/x86_64-linux-gnu/plymouth", "etc/default"):
        (root / d).mkdir(parents=True)
    (root / "usr/lib/x86_64-linux-gnu/plymouth/script.so").write_text("")
    (root / "etc/alternatives/default.plymouth").write_text("mint-logo")
    (root / "boot/grub/grub.cfg").write_text("menuentry 'Linux Mint 22 Cinnamon' {\n}\nsubmenu 'Advanced options for Linux Mint' {\n}\n")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    log = tmp_path / "calls.log"
    state = tmp_path / "theme"
    state.write_text("mint-logo")
    stubs = {
        "update-grub": f'''f="$ROOT/etc/default/grub.d/zz-code-quiet.cfg"
if [ -z "$GRUB_NO_WRITE" ]; then
  echo "# regenerated" >> "$ROOT/boot/grub/grub.cfg"
  [ -z "$GRUB_NO_41" ] && printf '### BEGIN /etc/grub.d/41_custom ###\\nif [ -f  ${{config_directory}}/custom.cfg ]; then\\n  source ${{config_directory}}/custom.cfg\\nfi\\n### END /etc/grub.d/41_custom ###\\n' >> "$ROOT/boot/grub/grub.cfg"
fi
if [ -f "$f" ] && [ -z "$GRUB_IGNORE" ] && [ -z "$GRUB_NO_WRITE" ]; then
  grep -q GRUB_TIMEOUT_STYLE=hidden "$f" && echo "set timeout_style=hidden" >> "$ROOT/boot/grub/grub.cfg"
  echo "linux /vmlinuz quiet splash" >> "$ROOT/boot/grub/grub.cfg"
fi''',
        "update-initramfs": f'''[ -f "$ROOT/etc/default/grub.d/zz-code-quiet.cfg" ] || true''',
        "update-alternatives": "true",
        "plymouth-set-default-theme": f'''if [ -z "$1" ]; then cat "{state}"; else echo "$1" > "{state}"; fi''',
    }
    for name, body in stubs.items():
        f = bin_ / name
        f.write_text(f'#!/bin/sh\necho "{name} $*" >> "{log}"\n[ "$FAIL" = "{name}" ] && exit 1\n{body}\nexit 0\n')
        f.chmod(0o755)
    logo = tmp_path / "code-logo.png"
    logo.write_bytes(b"\x89PNG fake")
    lay = quietboot.Layout(root=root)
    lay.state = state
    return lay, bin_, log, logo


def run_script(script, bin_, fail="", **extra):
    root = str(bin_.parent / "root")
    env = dict(os.environ, PATH=f"{bin_}:{os.environ['PATH']}", FAIL=fail, ROOT=root, **extra)
    return subprocess.run(["sh", "-c", script], capture_output=True, text=True, env=env).returncode


@pytest.fixture(autouse=True)
def linux_only_disk(monkeypatch):
    monkeypatch.setattr(quietboot, "disk_filesystems", lambda: ["ext4", "vfat", "swap"])


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


def test_another_operating_system_keeps_the_boot_menu_visible(machine, monkeypatch):
    lay, bin_, log, logo = machine
    monkeypatch.setattr(quietboot, "disk_filesystems", lambda: ["ext4", "vfat", "ntfs"])             # a Windows disk is really there
    (lay.root / "boot/grub/grub.cfg").write_text("menuentry 'Linux Mint' {\n}\nmenuentry 'Windows Boot Manager (on /dev/sda1)' --class windows {\n}\n")
    cs = quietboot.preflight(lay, which=which_all, logo=logo)
    assert quietboot.blocked(cs) == "" and any("Windows Boot Manager" in c.text and not c.ok for c in cs)
    ok, text = quietboot.enable(lay, lambda cmd, out, cancel: run_script(cmd[3], bin_), checks=cs, logo=logo, which=which_all)
    assert ok and "menu was left visible" in text
    cfg = lay.p(lay.grub_cfg).read_text()
    assert "GRUB_TIMEOUT_STYLE=hidden" not in cfg and "quiet splash" in cfg                 # quiet text, but the menu is not hidden
    assert "timeout_style=hidden" not in lay.p(lay.grub_menu).read_text()


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
        "boot/grub/custom.cfg", "boot/grub/grub.cfg", "etc/alternatives/default.plymouth", "usr/lib/x86_64-linux-gnu/plymouth/script.so"]


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


@pytest.mark.parametrize("failing,step", [("update-grub", "rebuilding the boot menu"), ("update-initramfs", "rebuilding the boot image"),
                                           ("plymouth-set-default-theme", "choosing the Code boot-splash theme")])
def test_a_failed_step_puts_everything_back_and_names_the_step(machine, failing, step):
    lay, bin_, log, logo = machine
    ok, text = quietboot.enable(lay, lambda c, o, x: run_script(c[3], bin_, fail=failing), logo=logo, which=which_all)
    assert not ok and f"Failed while {step}" in text and "Everything was put back" in text and not quietboot.enabled(lay)
    assert not lay.p(lay.grub_cfg).exists() and not lay.p(lay.theme_dir).exists() and not lay.p(lay.marker_dir).exists()
    assert lay.state.read_text().strip() == "mint-logo"                      # Mint's own theme is the current one again
    if failing != "update-grub":
        assert "update-grub" in log.read_text()                       # the menu is rebuilt without our file


def test_a_grub_that_ignores_our_file_is_caught_instead_of_pretending_it_worked(machine):
    """The Dell's symptom: everything 'worked' but the Mint menu still showed. Now it is verified in grub.cfg and rolled back."""
    lay, bin_, log, logo = machine
    ok, text = quietboot.enable(lay, lambda c, o, x: run_script(c[3], bin_, GRUB_IGNORE="1"), logo=logo, which=which_all)
    assert not ok and "checking that GRUB took the setting" in text and not quietboot.enabled(lay) and not lay.p(lay.grub_cfg).exists()


def test_a_boot_image_without_the_theme_is_caught(machine):
    lay, bin_, log, logo = machine
    (lay.root / "boot").mkdir(exist_ok=True)
    kernel = subprocess.run(["uname", "-r"], capture_output=True, text=True).stdout.strip()
    (lay.root / f"boot/initrd.img-{kernel}").write_text("x")
    ls = bin_ / "lsinitramfs"
    ls.write_text("#!/bin/sh\necho usr/share/plymouth/themes/mint-logo/mint-logo.plymouth\n")
    ls.chmod(0o755)
    ok, text = quietboot.enable(lay, lambda c, o, x: run_script(c[3], bin_), logo=logo, which=which_all)
    assert not ok and "boot image contains the Code theme" in text and not quietboot.enabled(lay)
    ls.write_text("#!/bin/sh\necho usr/share/plymouth/themes/code/code.plymouth\n")
    assert quietboot.enable(lay, lambda c, o, x: run_script(c[3], bin_), logo=logo, which=which_all)[0]


def test_the_theme_is_set_with_the_plymouth_tool_so_plymouthd_conf_follows(machine):
    lay, bin_, log, logo = machine
    assert quietboot.enable(lay, lambda c, o, x: run_script(c[3], bin_), logo=logo, which=which_all)[0]
    assert lay.state.read_text().strip() == "code" and "plymouth-set-default-theme code" in log.read_text()
    assert "previous_theme=mint-logo" in lay.p(lay.marker).read_text()
    assert quietboot.enable(lay, lambda c, o, x: run_script(c[3], bin_), logo=logo, which=which_all)[0]      # twice: still remembers Mint's
    assert "previous_theme=mint-logo" in lay.p(lay.marker).read_text()
    assert quietboot.disable(lay, lambda c, o, x: run_script(c[3], bin_))[0]
    assert lay.state.read_text().strip() == "mint-logo"                      # Mint's own splash is back


def test_a_leftover_windows_entry_without_a_windows_disk_does_not_block_hiding(machine):
    """GRUB keeps listing 'Windows Boot Manager' after Windows is deleted (the old boot files stay on the EFI partition)."""
    lay, bin_, log, logo = machine
    (lay.root / "boot/grub/grub.cfg").write_text("menuentry 'Linux Mint' {\n}\nmenuentry 'Windows Boot Manager (on /dev/nvme0n1p1)' --class windows {\n}\n")
    cs = quietboot.preflight(lay, which=which_all, logo=logo)
    assert all(c.ok for c in cs) and any("leftover" in c.text for c in cs)
    ok, text = quietboot.enable(lay, lambda c, o, x: run_script(c[3], bin_), logo=logo, which=which_all)
    assert ok and "no boot menu" in text and "GRUB_TIMEOUT_STYLE=hidden" in lay.p(lay.grub_cfg).read_text()


def test_a_real_other_system_can_still_be_overruled_by_the_person(machine, monkeypatch):
    lay, bin_, log, logo = machine
    monkeypatch.setattr(quietboot, "disk_filesystems", lambda: ["ext4", "ntfs"])
    (lay.root / "boot/grub/grub.cfg").write_text("menuentry 'Windows Boot Manager (on /dev/sda1)' {\n}\n")
    ok, text = quietboot.enable(lay, lambda c, o, x: run_script(c[3], bin_), logo=logo, which=which_all, force_hide=True)
    assert ok and "GRUB_TIMEOUT_STYLE=hidden" in lay.p(lay.grub_cfg).read_text()


def test_an_unreadable_disk_list_is_treated_as_windows_present(machine, monkeypatch):
    lay, _, _, logo = machine
    monkeypatch.setattr(quietboot, "disk_filesystems", lambda: None)
    (lay.root / "boot/grub/grub.cfg").write_text("menuentry 'Windows Boot Manager' {\n}\n")
    assert quietboot.other_systems(lay) == ["Windows Boot Manager"]


def test_the_legacy_0_4_2_file_is_cleaned_up_and_removed_when_turning_off(machine):
    lay, bin_, log, logo = machine
    legacy = lay.p(lay.legacy_grub_cfg)
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("old")
    assert quietboot.enable(lay, lambda c, o, x: run_script(c[3], bin_), logo=logo, which=which_all)[0]
    assert not legacy.exists()
    legacy.write_text("old")
    assert quietboot.disable(lay, lambda c, o, x: run_script(c[3], bin_))[0] and not legacy.exists()


def test_every_outcome_is_written_to_the_session_log(machine, tmp_path, monkeypatch):
    lay, bin_, log, logo = machine
    monkeypatch.delenv("ATARI_NO_SESSIONLOG", raising=False)
    monkeypatch.setattr(kiosk.Path, "home", classmethod(lambda cls: tmp_path / "h"))
    ok, _ = quietboot.enable(lay, lambda c, o, x: run_script(c[3], bin_), logo=logo, which=which_all)
    bad, text = quietboot.enable(lay, lambda c, o, x: run_script(c[3], bin_, fail="update-grub"), logo=logo, which=which_all)
    quietboot.disable(lay, lambda c, o, x: 127)
    lines = (tmp_path / "h/.local/share/atari/session.log").read_text()
    assert "quiet boot on: asking for the password" in lines and "quiet boot on: OK" in lines
    assert "quiet boot on: FAILED - Failed while rebuilding the boot menu" in lines and "quiet boot off: FAILED - No password was entered" in lines


def test_explain_covers_password_and_step_codes():
    assert quietboot.explain(0, "x", []) == ""
    assert "No password was entered" in quietboot.explain(126, "x", []) and "No password was entered" in quietboot.explain(127, "x", [])
    assert "Failed while writing the GRUB setting file" in quietboot.explain(81, "x", [])
    assert "code 3" in quietboot.explain(3, "turn quiet boot on", [])
    assert set(quietboot.STEPS) >= {81, 82, 83, 84, 85, 86, 87, 88, 89}


def test_diagnose_names_what_is_wrong(machine):
    lay, bin_, log, logo = machine
    facts = " | ".join(quietboot.diagnose(lay))
    assert "WRONG  quiet boot marker" in facts and "timeout_style=hidden" in facts
    assert quietboot.enable(lay, lambda c, o, x: run_script(c[3], bin_), logo=logo, which=which_all)[0]
    facts = quietboot.diagnose(lay)
    assert not [f for f in facts if f.startswith("WRONG")], facts
    assert "plymouth-set-default-theme" in quietboot.DIAGNOSTIC_COMMAND and "grub.cfg" in quietboot.DIAGNOSTIC_COMMAND
    assert subprocess.run(["sh", "-n", "-c", quietboot.DIAGNOSTIC_COMMAND]).returncode == 0
    out = subprocess.run([sys.executable, "-m", "atarilauncher.quietboot", "--check"], capture_output=True, text=True,
                         cwd=Path(quietboot.__file__).resolve().parent.parent, timeout=60)
    assert out.returncode == 0 and "quiet boot marker" in out.stdout


def test_a_closed_password_window_changes_nothing(machine):
    lay, bin_, log, logo = machine
    ok, text = quietboot.enable(lay, lambda c, o, x: 126, logo=logo, which=which_all)
    assert not ok and "No password was entered" in text and "nothing was changed" in text and not any(p.exists() for p in lay.files)


def test_without_grub_only_the_splash_is_changed(machine):
    lay, bin_, log, logo = machine
    (lay.root / "boot/grub/grub.cfg").unlink()
    which = lambda n: None if n == "update-grub" else "/usr/bin/" + n  # noqa: E731
    ok, text = quietboot.enable(lay, lambda c, o, x: run_script(c[3], bin_), logo=logo, which=which)
    assert ok and not lay.p(lay.grub_cfg).exists() and quietboot.enabled(lay) and "update-grub" not in log.read_text()


def test_recovery_text_names_the_exact_undo_commands():
    assert "rm -f /etc/default/grub.d/zz-code-quiet.cfg" in quietboot.RECOVERY and "update-initramfs -u" in quietboot.RECOVERY
    assert "Shift" in quietboot.HOW_TO_SHOW_MENU and "Esc" in quietboot.HOW_TO_SHOW_MENU


def test_the_bundled_logo_exists_and_is_code_branding():
    assert quietboot.logo_path().is_file() and quietboot.logo_path().name == "code-logo.png"


def test_settings_row_and_screen_always_show_a_visible_result(app, tmp_path, monkeypatch, machine):
    lay, bin_, log, logo = machine
    conf(tmp_path, "[steam]\nenabled = false\n")
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        b = ui.backend
        b._qb_layout = lay
        orig_pre = quietboot.preflight
        monkeypatch.setattr(quietboot, "logo_path", lambda: logo)
        monkeypatch.setattr(quietboot, "preflight", lambda layout=lay, **kw: orig_pre(layout, which=which_all, logo=logo))
        row = [r for r in b.setupRows() if r.get("kind") == "quietbootpage"][0]
        assert row["value"] == "OFF" and "Mint" in row["title"]
        rows = b.pageRows("quietboot")
        text = " ".join(r.get("title", "") for r in rows)
        assert "Shift" in text and "puts everything back" in text and "which step failed" in text
        assert [r.get("id") for r in rows if r["kind"] != "info"] == ["qbon", "qbreport", "back"]
        orig_en, orig_dis = quietboot.enable, quietboot.disable
        env = {}
        monkeypatch.setattr(quietboot, "enable", lambda l, **kw: orig_en(l, lambda c, o, x: run_script(c[3], bin_, **env), logo=logo, which=which_all, **kw))
        monkeypatch.setattr(quietboot, "disable", lambda l: orig_dis(l, lambda c, o, x: run_script(c[3], bin_)))
        # a failure is shown, with the reason, first on the page and in the toast
        env["GRUB_IGNORE"] = "1"
        assert b.pageActivate("quietboot", "qbon") == "refresh"
        assert [r.get("title") for r in b.pageRows("quietboot") if r.get("id") == "noop"] == ["Working ..."]
        assert wait_for(app, lambda: not b._qb_busy and b._qb_msg, 15), b.toast
        first = b.pageRows("quietboot")[0]
        assert first["kind"] == "info" and first["title"].startswith("FAILED:") and "checking that GRUB took the setting" in first["title"]
        assert b.toast.startswith("Failed:") and not quietboot.enabled(lay)
        # then success: DONE first, ON in Settings
        env.clear()
        assert b.pageActivate("quietboot", "qbon") == "refresh"
        assert wait_for(app, lambda: quietboot.enabled(lay) and not b._qb_busy, 15), b.toast
        rows = b.pageRows("quietboot")
        assert rows[0]["title"].startswith("DONE:") and b.toast.startswith("Done:")
        assert [r.get("id") for r in rows if r["kind"] != "info"] == ["qboff", "qbreport", "back"]
        assert [r for r in b.setupRows() if r.get("kind") == "quietbootpage"][0]["value"] == "ON"
        assert b.pageActivate("quietboot", "qboff") == "refresh"
        assert wait_for(app, lambda: not quietboot.enabled(lay) and not b._qb_busy, 15)
        qml = (Path(quietboot.__file__).parent / "qml" / "Main.qml").read_text()
        assert 'r.kind === "quietbootpage"' in qml and 'openPage("quietboot")' in qml and b.pageTitle("quietboot") == "QUIET BOOT"
    finally:
        ui.close()


def test_the_screen_offers_to_hide_anyway_when_another_system_is_listed(app, tmp_path, monkeypatch, machine):
    lay, bin_, log, logo = machine
    conf(tmp_path, "[steam]\nenabled = false\n")
    monkeypatch.setattr(quietboot, "disk_filesystems", lambda: ["ntfs", "ext4"])
    (lay.root / "boot/grub/grub.cfg").write_text("menuentry 'Windows Boot Manager (on /dev/sda1)' {\n}\n")
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        b = ui.backend
        b._qb_layout = lay
        orig_pre = quietboot.preflight
        monkeypatch.setattr(quietboot, "logo_path", lambda: logo)
        monkeypatch.setattr(quietboot, "preflight", lambda layout=lay, **kw: orig_pre(layout, which=which_all, logo=logo))
        rows = b.pageRows("quietboot")
        assert [r.get("id") for r in rows if r["kind"] != "info"] == ["qbon", "qbforce", "qbreport", "back"]
        assert "Another system is on this disk" in " ".join(r.get("title", "") for r in rows)
        seen = []
        monkeypatch.setattr(quietboot, "enable", lambda l, **kw: (seen.append(kw) or (True, "ok")))
        b.pageActivate("quietboot", "qbforce")
        assert wait_for(app, lambda: seen and not b._qb_busy, 10) and seen == [{"force_hide": True}]
    finally:
        ui.close()
