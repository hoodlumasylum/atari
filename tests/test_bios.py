import os
from pathlib import Path

import pytest

from atarilauncher import bios, emulators


def nowhere(_name):
    return None


@pytest.fixture
def stick(tmp_path):
    """A fake USB stick holding a few BIOS files (random bytes: only names/sizes matter, nothing real is bundled)."""
    s = tmp_path / "media" / "STICK"
    (s / "console dumps").mkdir(parents=True)
    (s / "console dumps" / "scph5501.bin").write_bytes(os.urandom(512 * 1024))      # name ok, MD5 unknown -> "odd"
    (s / "console dumps" / "firmware.bin").write_bytes(os.urandom(256 * 1024))      # DS firmware: any dump is fine
    (s / "dc_boot.bin").write_bytes(b"\x01" * 2048)
    (s / "mcpx_1.0.bin").write_bytes(b"\x02" * 512)
    (s / "SCPH-70012.BIN").write_bytes(b"\x03" * (4 * 1024 * 1024))                  # looks like a PS2 BIOS
    (s / "PS3UPDAT.PUP").write_bytes(b"\x04" * 1024)
    (s / "random_other.bin").write_bytes(b"\x05" * 100)                              # not a BIOS: ignored
    (s / "prod.keys").write_text("master_key_00 = 00\n")
    (s / "Game.iso").write_bytes(b"x" * 10)
    (s / ".hidden").mkdir()
    (s / ".hidden" / "bios7.bin").write_bytes(b"z" * 10)                             # hidden folders are skipped
    return s


def test_scan_finds_known_files_only(stick):
    res = bios.scan_for_bios(stick)
    by = {it.name: it for it in res.items}
    assert set(by) == {"scph5501.bin", "firmware.bin", "dc_boot.bin", "mcpx_1.0.bin", "SCPH-70012.BIN", "PS3UPDAT.PUP",
                       "prod.keys"}
    assert by["scph5501.bin"].status == "odd" and by["scph5501.bin"].system == "ps1"
    assert by["firmware.bin"].status == "named"
    assert by["SCPH-70012.BIN"].system == "ps2"
    assert by["PS3UPDAT.PUP"].status == "note" and "Install Firmware" in by["PS3UPDAT.PUP"].note
    assert "random_other.bin" not in by


def test_known_md5_is_verified_when_it_matches(tmp_path, monkeypatch):
    f = tmp_path / "gba_bios.bin"
    f.write_bytes(b"abc")
    kn = bios.KNOWN_BY_NAME["gba_bios.bin"]
    monkeypatch.setattr(bios, "md5_of", lambda p, limit=0: kn.md5[0])
    assert bios.identify(f).status == "ok"
    monkeypatch.setattr(bios, "md5_of", lambda p, limit=0: "0" * 32)
    assert bios.identify(f).status == "odd"


def test_copy_goes_to_each_emulators_folder_and_is_idempotent(stick, tmp_path):
    home = tmp_path / "home"
    (home / ".local/share/duckstation").mkdir(parents=True)          # DuckStation installed natively
    (home / ".local/share/flatpak/app/org.flycast.Flycast/current").mkdir(parents=True)   # Flycast as Flatpak
    items = [i for i in bios.scan_for_bios(stick).items if i.status != "note"]
    r1 = bios.copy_items(items, None, home, which=nowhere)
    assert r1.copied > 0 and not r1.failed
    assert (home / ".local/share/duckstation/bios/scph5501.bin").is_file()
    assert (home / ".var/app/org.flycast.Flycast/data/flycast/dc_boot.bin").is_file()
    assert (home / ".var/app/net.pcsx2.PCSX2/config/PCSX2/bios/SCPH-70012.BIN").is_file()
    assert (home / ".var/app/org.libretro.RetroArch/config/retroarch/system/scph5501.bin").is_file()
    assert (home / ".var/app/org.libretro.RetroArch/config/retroarch/system/dc/dc_boot.bin").is_file()
    assert not list(home.rglob("*.part"))
    assert (stick / "dc_boot.bin").is_file()                                       # the stick is only read
    r2 = bios.copy_items(items, None, home, which=nowhere)
    assert r2.copied == 0 and r2.skipped_same > 0                                    # nothing copied twice


def test_xemu_toml_written_only_if_absent(tmp_path):
    s = tmp_path / "usb"
    s.mkdir()
    for n in ("mcpx_1.0.bin", "Complex_4627v1.03.bin", "xbox_hdd.qcow2"):
        (s / n).write_bytes(b"\x02" * 64)
    items = bios.scan_for_bios(s).items
    assert {i.system for i in items} == {"xbox"} and len(items) == 3
    fresh = tmp_path / "fresh"
    bios.copy_items(items, None, fresh, which=nowhere)
    toml = fresh / ".var/app/app.xemu.xemu/data/xemu/xemu/xemu.toml"
    assert toml.is_file() and "[sys.files]" in toml.read_text() and "mcpx_1.0.bin" in toml.read_text()
    mine = tmp_path / "mine"
    d = mine / ".var/app/app.xemu.xemu/data/xemu/xemu"
    d.mkdir(parents=True)
    (d / "xemu.toml").write_text("# mine\n")
    bios.copy_items(items, None, mine, which=nowhere)
    assert (d / "xemu.toml").read_text() == "# mine\n"


def test_ps3_note_is_reported_not_copied(stick, tmp_path):
    items = [i for i in bios.scan_for_bios(stick).items if i.system == "ps3"]
    r = bios.copy_items(items, None, tmp_path / "h", which=nowhere)
    assert r.copied == 0 and any("RPCS3" in n for n in r.notes)


def test_missing_for_is_plain_english(tmp_path):
    home = tmp_path / "h"
    st, text = bios.missing_for("ps1", home, nowhere)
    assert st == "missing" and "BIOS file from your own console" in text and "Add BIOS files" in text
    assert bios.missing_for("nes", home, nowhere)[0] == "none"
    assert bios.missing_for("ps3", home, nowhere)[0] == "note"
    st, text = bios.missing_for("switch", home, nowhere)
    assert st == "missing" and "prod.keys" in text
    # once the file is in place it is reported as found
    d = home / ".var/app/org.duckstation.DuckStation/config/duckstation/bios"
    d.mkdir(parents=True)
    (d / "scph5501.bin").write_bytes(b"x" * 10)
    (home / ".local/share/flatpak/app/org.duckstation.DuckStation/current").mkdir(parents=True)
    assert bios.missing_for("ps1", home, nowhere)[0] == "ok"


def test_legal_text_is_gentle():
    assert "consoles you own" in bios.LEGAL
