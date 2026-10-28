"""Quiet boot 0.4.5: the os-prober / stale Windows entry, competing grub.d overrides, and the honest read-back status."""
import subprocess

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
    assert "'mint-logo'" in bad and "does NOT contain the Code theme" in bad and "zzz-late.cfg sets GRUB_TIMEOUT_STYLE=menu AFTER" in bad
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
