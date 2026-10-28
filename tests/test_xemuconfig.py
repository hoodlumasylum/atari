"""xemu "Failed to open flash file ''": xemu.toml must have the four [sys.files] paths. Written from files found, kept when they work,
repaired when empty/wrong, name variants and sizes understood, the missing pieces reported, and the repair page / launch check work."""
import os
import subprocess

import pytest

from atarilauncher import bios, xemuconfig

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from tests.test_features_ui import conf  # noqa: E402
from tests.test_ui_keys import Ui, app  # noqa: E402,F401

FLASH = 256 * 1024


def nowhere(_n):
    return None


@pytest.fixture
def home(tmp_path):
    return tmp_path / "home"


def data_dir(home):
    d = home / ".var/app/app.xemu.xemu/data/xemu/xemu"          # what CodeAque uses when no xemu is installed yet (the Flatpak folder)
    d.mkdir(parents=True, exist_ok=True)
    return d


def put(path, size):
    path.write_bytes(b"\x07" * size)
    return path


def full_set(d, flash="Complex_4627v1.03.bin"):
    put(d / "mcpx_1.0.bin", 512)
    put(d / flash, FLASH)
    put(d / "xbox_hdd.qcow2", 4096)


# ------------------------------------------------------------------ names and sizes
@pytest.mark.parametrize("name", ["Complex_4627.bin", "Complex 4627", "Complex 4627.bin", "complex-4627-v1.03.BIN", "Complex_4627v1.03.bin",
                                  "Complex_4627_v1.03.bin", "cerbios.bin", "Cerbios.bin", "xbox_bios.bin", "Xbox BIOS 5838.bin"])
def test_bios_name_variants_are_recognised(name):
    assert xemuconfig.classify_name(name) == "flashrom_path"
    assert xemuconfig.classify_name(name, generic=False) == "flashrom_path"


@pytest.mark.parametrize("name", ["mcpx_1.0.bin", "MCPX v1.0.rom", "MCPX_1.0.BIN", "mcpx.bin"])
def test_boot_rom_name_variants(name):
    assert xemuconfig.classify_name(name) == "bootrom_path"


def test_other_consoles_files_are_not_taken_for_xbox_files():
    for n in ("scph5501.bin", "dc_boot.bin", "sega_101.bin", "gba_bios.bin", "bios7.bin", "neogeo.zip", "5200.rom", "prod.keys"):
        assert xemuconfig.classify_name(n) == "", n
    assert xemuconfig.classify_name("bios.bin", generic=False) == ""         # too common a name to guess from in an unknown pack
    assert xemuconfig.size_problem("flashrom_path", 100) and not xemuconfig.size_problem("flashrom_path", FLASH)
    assert not xemuconfig.size_problem("flashrom_path", 1024 * 1024) and not xemuconfig.size_problem("flashrom_path", 512 * 1024)
    assert xemuconfig.size_problem("bootrom_path", 511) and not xemuconfig.size_problem("bootrom_path", 512)


def test_the_importer_finds_a_differently_named_bios_and_stores_it_under_the_canonical_name(tmp_path):
    usb = tmp_path / "usb"
    usb.mkdir()
    put(usb / "Complex 4627.bin", FLASH)
    put(usb / "MCPX v1.0.rom", 512)
    put(usb / "my disk.qcow2", 100)
    items = bios.scan_for_bios(usb).items
    by = {i.known.name: i for i in items}
    assert set(by) == {"Complex_4627v1.03.bin", "mcpx_1.0.bin", "xbox_hdd.qcow2"} and all(i.status == "named" for i in items)
    h = tmp_path / "h"
    bios.copy_items(items, None, h, which=nowhere)
    d = h / ".var/app/app.xemu.xemu/data/xemu/xemu"
    assert (d / "Complex_4627v1.03.bin").stat().st_size == FLASH and (d / "mcpx_1.0.bin").is_file()
    text = (d / "xemu.toml").read_text()
    for key in ("bootrom_path", "flashrom_path", "hdd_path"):
        assert key in text
    assert str(d / "Complex_4627v1.03.bin") in text


def test_an_unnamed_bios_is_found_by_size_next_to_the_other_xbox_files_and_marked_unusual(tmp_path):
    usb = tmp_path / "usb"
    usb.mkdir()
    put(usb / "mcpx_1.0.bin", 512)
    put(usb / "x2b7f.bin", FLASH)                          # a name nobody can recognise
    put(usb / "other.bin", 1000)                           # wrong size: ignored
    items = bios.scan_for_bios(usb).items
    flash = [i for i in items if i.known and i.known.name == "Complex_4627v1.03.bin"]
    assert len(flash) == 1 and flash[0].status == "odd" and flash[0].path.name == "x2b7f.bin"
    put(usb / "y.bin", FLASH)                              # two candidates: we do not guess
    assert not [i for i in bios.scan_for_bios(usb).items if i.known and i.known.name == "Complex_4627v1.03.bin"]


def test_a_wrong_sized_file_is_flagged_not_trusted(tmp_path):
    usb = tmp_path / "usb"
    usb.mkdir()
    put(usb / "Complex_4627.bin", 1234)
    put(usb / "mcpx_1.0.bin", 99)
    st = {i.known.name: i.status for i in bios.scan_for_bios(usb).items}
    assert st == {"Complex_4627v1.03.bin": "odd", "mcpx_1.0.bin": "odd"}


# ------------------------------------------------------------------ the settings file
def test_xemu_first_start_leaves_empty_paths_and_repair_fills_them_keeping_other_settings(home):
    d = data_dir(home)
    full_set(d, flash="Complex_4627.bin")
    toml = d / "xemu.toml"
    toml.write_text("[general]\nshow_welcome = false\n\n[sys]\nmem_limit = '128'\n\n[sys.files]\nbootrom_path = ''\nflashrom_path = ''\n"
                    "eeprom_path = ''\nhdd_path = ''\n\n[audio]\nvolume = 0.5\n")
    before = xemuconfig.check(home, nowhere)
    assert not before.ok and {r.key: r.state for r in before.rows}["flashrom_path"] == "todo"
    assert "Failed" not in xemuconfig.launch_problem(before) and "flash" in xemuconfig.launch_problem(before).lower() or "BIOS" in xemuconfig.launch_problem(before)
    assert toml.read_text().count("flashrom_path = ''") == 1                  # checking changed nothing
    rep = xemuconfig.repair(home, nowhere)
    assert rep.ok and str(toml) in rep.written
    vals = xemuconfig.read_files_section(toml.read_text())
    assert vals["bootrom_path"] == str(d / "mcpx_1.0.bin") and vals["flashrom_path"] == str(d / "Complex_4627.bin")
    assert vals["hdd_path"] == str(d / "xbox_hdd.qcow2") and vals["eeprom_path"] == ""         # EEPROM stays optional
    text = toml.read_text()
    assert "show_welcome = false" in text and "mem_limit = '128'" in text and "volume = 0.5" in text    # nothing else touched
    assert (d / xemuconfig.BACKUP_NAME).read_text().count("flashrom_path = ''") == 1                   # the old file was kept once
    import tomllib
    tomllib.loads(text)                                                                               # still valid TOML
    again = xemuconfig.repair(home, nowhere)
    assert again.ok and not again.written                                                              # nothing to change the second time


def test_a_path_the_user_set_that_works_is_never_replaced(home, tmp_path):
    d = data_dir(home)
    full_set(d)
    mine = put(tmp_path / "elsewhere" / "my_bios.bin", FLASH) if (tmp_path / "elsewhere").mkdir() is None else None
    (d / "xemu.toml").write_text(f"[sys.files]\nflashrom_path = '{mine}'\n")
    rep = xemuconfig.repair(home, nowhere)
    vals = xemuconfig.read_files_section((d / "xemu.toml").read_text())
    assert vals["flashrom_path"] == str(mine) and vals["bootrom_path"].endswith("mcpx_1.0.bin")
    assert {r.key: r.state for r in rep.rows}["flashrom_path"] == "ok"


def test_a_path_to_a_file_that_is_gone_is_repaired(home):
    d = data_dir(home)
    full_set(d)
    (d / "xemu.toml").write_text(f"[sys.files]\nflashrom_path = '/nowhere/gone.bin'\nbootrom_path = '{d}/mcpx_1.0.bin'\nhdd_path = '{d}/xbox_hdd.qcow2'\n")
    rep = xemuconfig.repair(home, nowhere)
    assert rep.ok and xemuconfig.read_files_section((d / "xemu.toml").read_text())["flashrom_path"] == str(d / "Complex_4627v1.03.bin")


def test_no_settings_file_at_all_gets_one_and_the_missing_pieces_are_named(home):
    d = data_dir(home)
    put(d / "mcpx_1.0.bin", 512)
    rep = xemuconfig.repair(home, nowhere)
    assert not rep.ok and (d / "xemu.toml").is_file()
    why = xemuconfig.launch_problem(rep)
    assert "BIOS" in why and "hard-disk image" in why and "boot ROM" not in why
    assert {r.key for r in rep.missing} == {"flashrom_path", "hdd_path"}
    put(d / "Complex 4627", FLASH)
    put(d / "xbox_hdd.qcow2", 10)
    assert xemuconfig.repair(home, nowhere).ok
    assert xemuconfig.read_files_section((d / "xemu.toml").read_text())["flashrom_path"] == str(d / "Complex 4627")


def test_corrupt_settings_are_kept_aside_and_replaced(home):
    d = data_dir(home)
    full_set(d)
    (d / "xemu.toml").write_text("[sys.files\nthis is = not toml ][")
    rep = xemuconfig.repair(home, nowhere)
    assert rep.ok and (d / "xemu.toml.codeaque-bad").is_file() and any("could not be read" in n for n in rep.notes)


def test_paths_with_a_quote_in_them_are_written_safely():
    t = xemuconfig.set_files_section("", {"flashrom_path": "/home/o'brien/Complex.bin"})
    import tomllib
    assert tomllib.loads(t)["sys"]["files"]["flashrom_path"] == "/home/o'brien/Complex.bin"


def test_a_portable_xemu_toml_next_to_the_program_is_repaired_too(home, tmp_path):
    d = data_dir(home)
    full_set(d)
    prog = tmp_path / "apps" / "xemu"
    prog.parent.mkdir()
    prog.write_text("#!/bin/sh\n")
    (prog.parent / "xemu.toml").write_text("[sys.files]\nflashrom_path = ''\n")
    rep = xemuconfig.repair(home, lambda n: str(prog) if n == "xemu" else None)
    native = home / ".local/share/xemu/xemu/xemu.toml"                  # a xemu program is on the PATH, so its own data folder is the one in use
    assert str(prog.parent / "xemu.toml") in rep.written and str(native) in rep.written
    assert xemuconfig.read_files_section(native.read_text())["hdd_path"] == str(d / "xbox_hdd.qcow2")
    assert xemuconfig.read_files_section((prog.parent / "xemu.toml").read_text())["flashrom_path"] == str(d / "Complex_4627v1.03.bin")


def test_missing_for_counts_a_variant_named_bios_as_found(home):
    d = data_dir(home)
    full_set(d, flash="Complex 4627.bin")
    (home / ".local/share/flatpak/app/app.xemu.xemu/current").mkdir(parents=True)
    st, text = bios.missing_for("xbox", home, nowhere)
    assert st == "ok", text


# ------------------------------------------------------------------ the empty hard-disk image
def test_create_empty_hdd_needs_the_tool_and_never_overwrites(home):
    d = data_dir(home)
    ok, text = xemuconfig.create_empty_hdd(home, nowhere)
    assert not ok and "qemu-utils" in text and not (d / "xbox_hdd.qcow2").exists()
    calls = []

    def runner(cmd, **kw):
        calls.append(cmd)
        (d / "xbox_hdd.qcow2").write_bytes(b"QFI\xfb" + b"\0" * 200)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    ok, text = xemuconfig.create_empty_hdd(home, lambda n: "/usr/bin/qemu-img" if n == "qemu-img" else None, runner)
    assert ok and calls == [["/usr/bin/qemu-img", "create", "-f", "qcow2", str(d / "xbox_hdd.qcow2"), "8G"]] and "not formatted" in text
    ok, text = xemuconfig.create_empty_hdd(home, lambda n: "/usr/bin/qemu-img", runner)
    assert not ok and "already exists" in text and len(calls) == 1
    (d / "xbox_hdd.qcow2").unlink()
    bad = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "boom")             # noqa: E731
    ok, text = xemuconfig.create_empty_hdd(home, lambda n: "/usr/bin/qemu-img", bad)
    assert not ok and "boom" in text


# ------------------------------------------------------------------ the screen and the launch check
def make_ui(app, tmp_path, monkeypatch, home):
    monkeypatch.setenv("HOME", str(home))
    home.mkdir(parents=True, exist_ok=True)
    conf(tmp_path)
    return Ui(app, tmp_path, monkeypatch, config_exists=True, home=home)


def test_repair_page_shows_exact_paths_and_repairs(app, tmp_path, monkeypatch, home):
    d = data_dir(home)
    full_set(d)
    (d / "xemu.toml").write_text("[sys.files]\nbootrom_path = ''\nflashrom_path = ''\nhdd_path = ''\n")
    ui = make_ui(app, tmp_path, monkeypatch, home)
    try:
        b = ui.backend
        assert b.pageTitle("xemusetup") == "XBOX (XEMU) SETTINGS"
        assert any(r.get("kind") == "xemupage" for r in b.emulatorRows())
        rows = b.pageRows("xemusetup")
        text = " ".join(r["title"] for r in rows)
        assert str(d / "xemu.toml") in text and "Failed to open flash file" not in text
        vals = {r["title"].split(":")[0]: r["value"] for r in rows if r.get("id") == "xmrow"}
        assert vals["Boot ROM (MCPX)"] == vals["BIOS (flash)"] == vals["Hard-disk image"] == "CAN FIX"
        assert b.pageActivate("xemusetup", "xmrepair") == "refresh"
        rows = b.pageRows("xemusetup")
        text = " ".join(r["title"] for r in rows)
        assert str(d / "Complex_4627v1.03.bin") in text and str(d / "mcpx_1.0.bin") in text and "xemu has all it needs" in text
        vals = {r["title"].split(":")[0]: r["value"] for r in rows if r.get("id") == "xmrow"}
        assert set(vals.values()) == {"OK"}
        assert b.pageActivate("xemusetup", "xmbios") == "import:bios"
        assert "xmhdd" not in [r.get("id") for r in rows]                     # the disk exists: no need for the button
    finally:
        ui.close()


def test_hdd_button_only_when_the_disk_is_missing_and_a_tool_exists(app, tmp_path, monkeypatch, home):
    d = data_dir(home)
    put(d / "mcpx_1.0.bin", 512)
    put(d / "Complex_4627.bin", FLASH)
    ui = make_ui(app, tmp_path, monkeypatch, home)
    try:
        b = ui.backend
        monkeypatch.setattr(xemuconfig, "hdd_tool", lambda which=None: "")
        assert "xmhdd" not in [r.get("id") for r in b.pageRows("xemusetup")]
        assert "qemu-utils" in " ".join(r["title"] for r in b.pageRows("xemusetup"))
        monkeypatch.setattr(xemuconfig, "hdd_tool", lambda which=None: "/usr/bin/qemu-img")
        assert "xmhdd" in [r.get("id") for r in b.pageRows("xemusetup")]
        monkeypatch.setattr(xemuconfig, "create_empty_hdd", lambda *a, **k: (True, "Made an empty 8G disk image"))
        assert b.pageActivate("xemusetup", "xmhdd") == "refresh"
        assert "Made an empty" in " ".join(r["title"] for r in b.pageRows("xemusetup"))
    finally:
        ui.close()


def test_launch_repairs_the_settings_first_and_explains_instead_of_xemus_empty_dialog(tmp_path, monkeypatch, home):
    from atarilauncher import config, emulators, launcher
    from atarilauncher.library import Game
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("ATARI_DATA_DIR", str(tmp_path / "data"))
    d = data_dir(home)
    (d / "xemu.toml").write_text("[sys.files]\nflashrom_path = ''\n")
    cfg = config.default_config()
    sc = cfg.systems["xbox"]
    iso = tmp_path / "Game.iso"
    iso.write_bytes(b"x" * 100)
    g = Game(gid="rom:xbox:1", title="Game", platform="xbox", platform_name="Xbox", rom_path=str(iso))
    fake = emulators.Choice(emulators.EMUS["xemu"], ["/bin/true"], "native", "") if hasattr(emulators, "Choice") else None
    if fake is None:
        pytest.skip("emulators.Choice not available")
    monkeypatch.setattr(emulators, "choose", lambda cfg_, sc_, home_=None: fake)
    with pytest.raises(launcher.LaunchError) as e:
        launcher.run_game(cfg, g, lambda: None)
    assert "still needs" in str(e.value) and "xemu cannot start" in str(e.value)
