"""Quiet boot 0.4.5: the os-prober / stale Windows entry, competing grub.d overrides, and the honest read-back status."""
import subprocess

import os
from pathlib import Path

import pytest

from atarilauncher import quietboot
from tests.test_features_ui import conf
from tests.test_ui_keys import Ui, app  # noqa: F401
from tests.test_quietboot import machine, linux_only_disk, run_script, which_all  # noqa: F401

STALE = "menuentry 'Linux Mint' {\n}\nmenuentry 'Windows Boot Manager (on /dev/nvme0n1p1)' --class windows {\n}\n"


def lsi(listing, rc=0):
    return lambda p: subprocess.CompletedProcess([], rc, listing, "")


def states(facts):
    return {f.text: f.state for f in facts}


def find(facts, word):
    return [f for f in facts if word in f.text]


def turn_on(machine):
    lay, bin_, log, logo = machine
    ok, text = quietboot.enable(lay, lambda c, o, x: run_script(c[3], bin_), logo=logo, which=which_all)
    return ok, text


def test_render_grub_hides_the_menu_and_can_switch_the_os_prober_off():
    a = quietboot.render_grub(True)
    assert "GRUB_TIMEOUT_STYLE=hidden" in a and "GRUB_TIMEOUT=2" in a and "GRUB_HIDDEN_TIMEOUT_QUIET=true" in a and "GRUB_DISABLE_OS_PROBER" not in a
    b = quietboot.render_grub(True, disable_os_prober=True)
    assert "GRUB_DISABLE_OS_PROBER=true" in b
    c = quietboot.render_grub(False)
    assert "GRUB_TIMEOUT_STYLE=hidden" not in c and "quiet splash" in c


def test_a_stale_windows_entry_turns_the_os_prober_off_so_it_is_not_listed_again(machine):
    lay = machine[0]
    (lay.root / "boot/grub/grub.cfg").write_text(STALE)
    ok, _ = turn_on(machine)
    assert ok and "GRUB_DISABLE_OS_PROBER=true" in lay.p(lay.grub_cfg).read_text()


def test_the_os_prober_is_left_alone_on_a_normal_single_system(machine):
    lay = machine[0]
    ok, _ = turn_on(machine)
    assert ok and "GRUB_DISABLE_OS_PROBER" not in lay.p(lay.grub_cfg).read_text()


def test_a_real_other_system_keeps_the_prober_on(machine, monkeypatch):
    lay, bin_, log, logo = machine
    monkeypatch.setattr(quietboot, "disk_filesystems", lambda: ["ext4", "ntfs"])
    (lay.root / "boot/grub/grub.cfg").write_text("menuentry 'Windows Boot Manager' {\n}\n")
    ok, _ = quietboot.enable(lay, lambda c, o, x: run_script(c[3], bin_), logo=logo, which=which_all, force_hide=True)
    assert ok and "GRUB_DISABLE_OS_PROBER" not in lay.p(lay.grub_cfg).read_text()


def test_grub_overrides_say_which_files_win(machine):
    lay = machine[0]
    d = lay.root / "etc/default/grub.d"
    d.mkdir(parents=True, exist_ok=True)
    (d / "50_linuxmint.cfg").write_text('GRUB_TIMEOUT_STYLE=menu\nGRUB_TIMEOUT=10\nOTHER=1\n')
    (d / "zzz-late.cfg").write_text("export GRUB_TIMEOUT_STYLE=countdown\n")
    (lay.root / "etc/default/grub").write_text('GRUB_TIMEOUT="5"\n#GRUB_TIMEOUT_STYLE=x\n')
    by = {(o.file.rsplit("/", 1)[-1], o.key): o for o in quietboot.grub_overrides(lay)}
    assert by[("50_linuxmint.cfg", "GRUB_TIMEOUT_STYLE")].value == "menu" and not by[("50_linuxmint.cfg", "GRUB_TIMEOUT_STYLE")].wins
    assert by[("zzz-late.cfg", "GRUB_TIMEOUT_STYLE")].wins and by[("zzz-late.cfg", "GRUB_TIMEOUT_STYLE")].value == "countdown"
    assert by[("grub", "GRUB_TIMEOUT")].value == "5" and not by[("grub", "GRUB_TIMEOUT")].wins
    assert ("grub", "GRUB_TIMEOUT_STYLE") not in by and not any(k[1] == "OTHER" for k in by)


def test_a_grub_that_ignores_our_file_names_the_competing_setting(machine):
    lay, bin_, log, logo = machine
    d = lay.root / "etc/default/grub.d"
    d.mkdir(parents=True, exist_ok=True)
    (d / "zzz-late.cfg").write_text("GRUB_TIMEOUT_STYLE=menu\n")
    ok, text = quietboot.enable(lay, lambda c, o, x: run_script(c[3], bin_, GRUB_IGNORE="1"), logo=logo, which=which_all)
    assert not ok and "Competing settings" in text and "zzz-late.cfg sets GRUB_TIMEOUT_STYLE=menu" in text


def test_status_when_off_says_off_and_nothing_is_claimed(machine):
    lay = machine[0]
    facts = quietboot.status(lay, cmdline="BOOT_IMAGE=/vmlinuz root=/dev/sda2 ro", lsinitramfs=lsi(""))
    assert facts[0].state == "info" and "OFF" in facts[0].text
    assert find(facts, "setting file")[0].state == "bad" and find(facts, "grub.cfg) still SHOWS")[0].state == "bad"
    assert find(facts, "THIS start-up")[0].state == "info"
    assert "NOT" in quietboot.status_summary(facts)


def test_status_after_turning_on_reads_everything_back(machine):
    lay = machine[0]
    ok, _ = turn_on(machine)
    assert ok
    (lay.root / "etc/plymouth").mkdir(exist_ok=True)
    (lay.root / "etc/plymouth/plymouthd.conf").write_text("[Daemon]\nTheme=code\n")
    (lay.root / "boot/initrd.img-6.8.0-1").write_text("x")
    facts = quietboot.status(lay, cmdline="BOOT_IMAGE=/vmlinuz quiet splash", lsinitramfs=lsi("usr/share/plymouth/themes/code/code.plymouth\n"))
    bad = [f.text for f in facts if f.state == "bad"]
    assert not bad, bad
    assert "ON" in facts[0].text and find(facts, "boot image initrd.img-6.8.0-1 contains")[0].state == "ok"
    assert find(facts, "THIS start-up used: quiet splash")[0].state == "ok"
    assert quietboot.status_summary(facts).startswith("All ")


def test_status_catches_each_thing_that_is_not_applied(machine):
    lay = machine[0]
    turn_on(machine)
    (lay.root / "etc/plymouth").mkdir(exist_ok=True)
    (lay.root / "etc/plymouth/plymouthd.conf").write_text("[Daemon]\nTheme=mint-logo\n")
    (lay.root / "boot/initrd.img-6.8.0-1").write_text("x")
    d = lay.root / "etc/default/grub.d"
    (d / "zzz-late.cfg").write_text("GRUB_TIMEOUT_STYLE=menu\n")
    facts = quietboot.status(lay, cmdline="BOOT_IMAGE=/vmlinuz ro", lsinitramfs=lsi("some/other\n"))
    bad = " | ".join(f.text for f in facts if f.state == "bad")
    assert "'mint-logo'" in bad and "does NOT contain the CodeAque theme" in bad and "zzz-late.cfg sets GRUB_TIMEOUT_STYLE=menu AFTER" in bad
    assert find(facts, "THIS start-up")[0].state == "info"
    assert "NOT" in quietboot.status_summary(facts)


def test_status_notes_the_stale_windows_entry_and_a_unreadable_initrd(machine):
    lay = machine[0]
    (lay.root / "boot/grub/grub.cfg").write_text(STALE)
    (lay.root / "boot/initrd.img-6.8.0-1").write_text("x")
    facts = quietboot.status(lay, cmdline="", lsinitramfs=lsi("", rc=1))
    assert find(facts, "leftover entry")[0].state == "info" and find(facts, "could not be listed")[0].state == "info"


def test_status_never_raises(machine, monkeypatch):
    monkeypatch.setattr(quietboot, "enabled", lambda l: (_ for _ in ()).throw(RuntimeError("boom")))
    facts = quietboot.status(machine[0])
    assert facts and "boom" in facts[-1].text


def test_the_quiet_boot_page_shows_the_read_back_rows(app, tmp_path, monkeypatch, machine):
    lay, bin_, log, logo = machine
    conf(tmp_path, "[steam]\nenabled = false\n")
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        b = ui.backend
        b._qb_layout = lay
        monkeypatch.setattr(quietboot, "status", lambda layout=lay, **kw: [quietboot.Fact("ok", "Plymouth is fine."), quietboot.Fact("bad", "GRUB still shows the menu."),
                                                                       quietboot.Fact("info", "A side note.")])
        rows = b.pageRows("quietboot")
        titles = [r.get("title", "") for r in rows]
        assert any("WHAT IS APPLIED RIGHT NOW" in t for t in titles)
        assert "OK   Plymouth is fine." in titles and "NOT APPLIED   GRUB still shows the menu." in titles and "Note   A side note." in titles
        monkeypatch.setattr(quietboot, "status", lambda layout=lay, **kw: [quietboot.Fact("ok", "changed")])
        assert not any("changed" in t for t in b.pageRows("quietboot"))            # cached for a few seconds
        b._qb_facts_cache = None
        b._qb_facts_at = 0
    finally:
        ui.close()


# ---------------------------------------------------------------- 0.4.6: Mint / Ubuntu menu forcers, custom.cfg last word, read-back
OSPROBER = """### BEGIN /etc/grub.d/30_os-prober ###
menuentry 'Windows Boot Manager (on /dev/nvme0n1p1)' --class windows $menuentry_id_option 'osprober-efi-ABCD' {
}
set timeout_style=menu
if [ "${timeout}" = 0 ]; then
  set timeout=10
fi
### END /etc/grub.d/30_os-prober ###
"""
RECORDFAIL = """### BEGIN /etc/grub.d/00_header ###
if [ "${recordfail}" = 1 ] ; then
  set timeout=30
else
  if [ x$feature_timeout_style = xy ] ; then
    set timeout_style=hidden
    set timeout=2
  fi
fi
### END /etc/grub.d/00_header ###
"""


def test_menu_forcers_are_recognised_in_a_generated_grub_cfg():
    assert quietboot.menu_forcers("") == []
    f = quietboot.menu_forcers(RECORDFAIL + OSPROBER)
    assert any("30_os-prober" in x for x in f) and any("30 s" in x for x in f)
    assert any("for ever" in x for x in quietboot.menu_forcers(RECORDFAIL.replace("=30", "=-1")))
    assert any("grubenv" in x for x in quietboot.menu_forcers("# GRUB lacks write support for btrfs, so recordfail support is disabled.\nif [ $grub_platform = efi ]; then\n"))
    assert quietboot.menu_forcers(RECORDFAIL.replace("=30", "=0")) == []


def test_turning_on_writes_the_custom_cfg_last_word_and_the_recordfail_timeout(machine):
    lay = machine[0]
    ok, text = turn_on(machine)
    assert ok
    cfg = lay.p(lay.grub_cfg).read_text()
    assert "GRUB_RECORDFAIL_TIMEOUT=2" in cfg
    custom = lay.p(lay.grub_custom).read_text()
    assert custom.startswith("# BEGIN code-quiet-boot") and "set timeout_style=hidden" in custom and "set timeout=2" in custom and custom.rstrip().endswith("# END code-quiet-boot")
    assert quietboot.marker_hide(lay) is True
    assert "Read back from the files just now - grub.cfg: menu hidden" in text and "custom.cfg last word: yes" in text and "quiet splash: yes" in text


def test_existing_custom_cfg_content_is_kept_and_the_block_is_not_duplicated_and_turn_off_removes_only_ours(machine):
    lay, bin_, log, logo = machine
    lay.p(lay.grub_custom).write_text("menuentry 'My own' {\n}\n")
    for _ in range(2):
        assert turn_on(machine)[0]
    text = lay.p(lay.grub_custom).read_text()
    assert text.count("BEGIN code-quiet-boot") == 1 and text.startswith("menuentry 'My own'")
    assert quietboot.disable(lay, lambda c, o, x: run_script(c[3], bin_))[0]
    assert lay.p(lay.grub_custom).read_text() == "menuentry 'My own' {\n}\n"


def test_turn_off_deletes_a_custom_cfg_that_only_had_our_block(machine):
    lay, bin_, log, logo = machine
    assert turn_on(machine)[0] and lay.p(lay.grub_custom).exists()
    assert quietboot.disable(lay, lambda c, o, x: run_script(c[3], bin_))[0]
    assert not lay.p(lay.grub_custom).exists() and not lay.p(lay.grub_cfg).exists()


def test_a_failed_step_removes_the_custom_block_again(machine):
    lay, bin_, log, logo = machine
    ok, text = quietboot.enable(lay, lambda c, o, x: run_script(c[3], bin_, fail="update-initramfs"), logo=logo, which=which_all)
    assert not ok and not lay.p(lay.grub_custom).exists()


def test_update_grub_that_did_not_rewrite_grub_cfg_is_caught(machine):
    lay, bin_, log, logo = machine
    (lay.root / "boot/grub/grub.cfg").write_text("menuentry 'Linux Mint' {\n}\nset timeout_style=hidden\nlinux /vmlinuz quiet splash\n")   # stale file that already "looks right"
    ok, text = quietboot.enable(lay, lambda c, o, x: run_script(c[3], bin_, GRUB_NO_WRITE="1"), logo=logo, which=which_all)
    assert not ok and "really rewrote /boot/grub/grub.cfg" in text and not lay.p(lay.grub_cfg).exists() and not lay.p(lay.grub_custom).exists()


def test_force_hide_with_a_real_other_system_keeps_os_prober_but_custom_cfg_still_hides(machine, monkeypatch):
    lay, bin_, log, logo = machine
    monkeypatch.setattr(quietboot, "disk_filesystems", lambda: ["ext4", "ntfs"])             # a Dell recovery partition is NTFS
    (lay.root / "boot/grub/grub.cfg").write_text(OSPROBER)
    ok, text = quietboot.enable(lay, lambda c, o, x: run_script(c[3], bin_), logo=logo, which=which_all, force_hide=True)
    assert ok and "GRUB_DISABLE_OS_PROBER" not in lay.p(lay.grub_cfg).read_text()
    assert "set timeout_style=hidden" in lay.p(lay.grub_custom).read_text()
    facts = quietboot.status(lay, cmdline="", lsinitramfs=lsi(""))
    assert [f for f in facts if "Overridden by custom.cfg" in f.text and "30_os-prober" in f.text]
    assert find(facts, "Last-word setting")[0].state == "ok"


def test_without_41_custom_in_grub_cfg_the_status_says_the_forcers_can_still_win(machine):
    lay, bin_, log, logo = machine
    ok, _ = quietboot.enable(lay, lambda c, o, x: run_script(c[3], bin_, GRUB_NO_41="1"), logo=logo, which=which_all)
    assert ok
    cfg = lay.p(lay.grub_menu)
    cfg.write_text(cfg.read_text() + RECORDFAIL + OSPROBER)
    facts = quietboot.status(lay, cmdline="", lsinitramfs=lsi(""))
    assert find(facts, "does not read custom.cfg")[0].state == "bad"
    assert any(f.state == "bad" and "Can show the menu" in f.text for f in facts)
    ok, text = True, quietboot.readback_text(lay, True)
    assert "custom.cfg last word: NO" in text and "Still NOT applied" in text


def test_grubenv_recordfail_is_reported(machine):
    lay = machine[0]
    turn_on(machine)
    lay.p(lay.grubenv).write_text("# GRUB Environment Block\nsaved_entry=0\nrecordfail=1\n")
    facts = quietboot.status(lay, cmdline="", lsinitramfs=lsi(""))
    assert find(facts, "recordfail=1")[0].state == "info"                        # custom.cfg hides it anyway
    lay.p(lay.grub_custom).unlink()
    facts = quietboot.status(lay, cmdline="", lsinitramfs=lsi(""))
    assert find(facts, "recordfail=1")[0].state == "bad"


def test_on_without_hiding_is_flagged_and_marker_says_so(machine, monkeypatch):
    lay, bin_, log, logo = machine
    monkeypatch.setattr(quietboot, "disk_filesystems", lambda: ["ext4", "ntfs"])
    (lay.root / "boot/grub/grub.cfg").write_text("menuentry 'Windows Boot Manager' {\n}\n")
    ok, text = quietboot.enable(lay, lambda c, o, x: run_script(c[3], bin_), logo=logo, which=which_all)
    assert ok and quietboot.marker_hide(lay) is False and not lay.p(lay.grub_custom).exists()
    assert any("WITHOUT hiding the menu" in f.text for f in quietboot.status(lay, cmdline="", lsinitramfs=lsi("")))
    assert quietboot.marker_hide(machine[0].__class__(root=lay.root / "nowhere")) is None


def test_step_codes_are_explained():
    assert "update-grub really rewrote" in quietboot.explain(90, "x", [])
    assert "custom.cfg" in quietboot.explain(91, "x", [])


def test_preflight_names_the_windows_type_partitions_and_the_dell_recovery_hint(machine, monkeypatch):
    lay, bin_, log, logo = machine
    monkeypatch.setattr(quietboot, "disk_filesystems", lambda: ["ext4", "ntfs"])
    monkeypatch.setattr(quietboot, "windows_partitions", lambda: ["nvme0n1p4 (ntfs, 1G, WINRE_DRV)"])
    (lay.root / "boot/grub/grub.cfg").write_text("menuentry 'Windows Boot Manager' {\n}\n")
    cs = quietboot.preflight(lay, which=which_all, logo=logo)
    text = " ".join(c.text for c in cs)
    assert "nvme0n1p4 (ntfs, 1G, WINRE_DRV)" in text and "Dell keeps recovery partitions" in text and "hide the boot menu anyway" in text


# ---------------------------------------------------------------- 0.4.6: boot report, Dell logo note, the page
def fake_run(cmd):
    return {"efibootmgr": "BootCurrent: 0001\nBoot0001* ubuntu\tHD(1,GPT)/File(\\EFI\\ubuntu\\shimx64.efi)\nBoot0002* Windows Boot Manager\tHD(1,GPT)\n",
            "lsblk": "NAME SIZE FSTYPE LABEL MOUNTPOINT\nnvme0n1p4 1G ntfs WINRE_DRV\n", "uname": "6.8.0-1-generic\n", "mokutil": "SecureBoot disabled\n",
            "plymouth-set-default-theme": "code\n"}.get(cmd[0], "")


def test_boot_report_has_the_boot_settings_and_no_secrets(machine, tmp_path):
    lay = machine[0]
    turn_on(machine)
    d = lay.root / "etc/default/grub.d"
    (d / "50_linuxmint.cfg").write_text('GRUB_DISTRIBUTOR="Ubuntu"\nGRUB_DISABLE_OS_PROBER=false\n')
    (lay.root / "etc/default").mkdir(exist_ok=True)
    (lay.root / "etc/default/grub").write_text('GRUB_TIMEOUT_STYLE=hidden\n# a comment\nGRUB_TIMEOUT=0\nGRUB_PASSWORD="hunter2secret"\n')
    (lay.root / "etc").mkdir(exist_ok=True)
    (lay.root / "etc/os-release").write_text('PRETTY_NAME="Linux Mint 22"\nUBUNTU_CODENAME=noble\n')
    lay.p(lay.grubenv).write_text("# GRUB Environment Block\nsaved_entry=0\nrecordfail=1\nsome_secret_token=abc\n")
    cfg = lay.p(lay.grub_menu)
    cfg.write_text(cfg.read_text() + RECORDFAIL + OSPROBER + 'password_pbkdf2 root grub.pbkdf2.sha512.10000.AAAA\n')
    rep = quietboot.boot_report(lay, run=fake_run, version="0.4.6", now="2026-10-28 15:00")
    for want in ("CodeAque boot report", "CodeAque 0.4.6", "Linux Mint 22", "6.8.0-1-generic", "SecureBoot disabled", "GRUB_TIMEOUT_STYLE=hidden", "GRUB_DISABLE_OS_PROBER=false",
                 "50_linuxmint.cfg", "BEGIN code-quiet-boot", "recordfail=1", "timeout_style=hidden", "Windows Boot Manager", "WINRE_DRV", "30_os-prober found another system",
                 "Read back by CodeAque just now", "About the Dell logo", "firmware (UEFI / BIOS)", "Fastboot"):
        assert want in rep, want
    assert "hunter2secret" not in rep and "pbkdf2.sha512" not in rep and "some_secret_token" not in rep and "(line left out" in rep
    assert "# a comment" not in rep


def test_boot_report_never_raises_when_everything_is_missing(tmp_path):
    rep = quietboot.boot_report(quietboot.Layout(root=tmp_path / "empty"), run=lambda c: "")
    assert "CodeAque boot report" in rep and "(nothing / not available)" in rep


def test_the_report_is_saved_in_downloads(tmp_path):
    ok, text, f = quietboot.save_report("hello\n", tmp_path / "home" / "Downloads")
    assert ok and f.name == "code-boot-report.txt" and f.read_text() == "hello\n" and "no passwords" in text
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert quietboot.save_report("x", blocker / "Downloads")[0] is False


def test_quiet_boot_page_and_settings_have_the_report_button_the_dell_note_and_the_hide_too_button(app, tmp_path, monkeypatch, machine):
    lay, bin_, log, logo = machine
    conf(tmp_path, "[steam]\nenabled = false\n")
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        b = ui.backend
        b._qb_layout = lay
        monkeypatch.setattr(quietboot, "status", lambda layout=lay, **kw: [])
        rows = b.pageRows("quietboot")
        ids = [r.get("id") for r in rows]
        assert "qbreport" in ids and any("Dell" in r.get("title", "") and "firmware" in r.get("title", "") for r in rows)
        srows = b.setupRows()
        assert [r for r in srows if r.get("kind") == "bootreport"] and [r for r in srows if r.get("kind") == "info" and "Dell logo" in r["title"] and "Fast" in r["detail"]]
        # ON but the menu was left visible: the page says so and offers "Hide the boot menu too"
        lay.p(lay.marker_dir).mkdir(parents=True, exist_ok=True)
        lay.p(lay.marker).write_text("hide_menu=no\nprevious_theme=mint-logo\n")
        rows = b.pageRows("quietboot")
        assert any(r.get("id") == "qbforce" and r["title"] == "Hide the boot menu too" for r in rows)
        assert any("NOT hidden" in r.get("title", "") for r in rows)
        lay.p(lay.marker).write_text("hide_menu=yes\nprevious_theme=mint-logo\n")
        assert not any(r.get("id") == "qbforce" for r in b.pageRows("quietboot"))
        # the button writes the file
        monkeypatch.setattr(quietboot, "boot_report", lambda layout, **kw: "REPORT TEXT\n")
        assert b.pageActivate("quietboot", "qbreport") == "refresh"
        from tests.test_features_ui import wait_for
        dest = Path(os.environ["HOME"]) / "Downloads" / "code-boot-report.txt"
        assert wait_for(app, lambda: dest.exists() and not b._qb_report_busy, 10)
        assert dest.read_text() == "REPORT TEXT\n" and "Saved" in b._qb_report_msg
        assert any("Boot report:" in r.get("title", "") for r in b.pageRows("quietboot"))
        dest.unlink()
        b.saveBootReport()
        assert wait_for(app, lambda: dest.exists() and not b._qb_report_busy, 10)
    finally:
        ui.close()
