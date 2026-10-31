import io
import shlex
import zipfile
from pathlib import Path

import pytest

from atarilauncher import emulators, xbox, xemuconfig


def test_fullscreen_on_and_off_for_every_emulator():
    for eid, emu in emulators.EMUS.items():
        on = emulators.with_fullscreen(eid, emu.template, True)
        off = emulators.with_fullscreen(eid, emu.template, False)
        fs = emulators.FULLSCREEN.get(eid, ())
        if fs:
            assert " ".join(fs) in on and on.count(fs[0]) == 1, eid
            assert " ".join(fs) not in off, eid
        assert "{exe}" in shlex.split(on)[0:1] or eid in ("mame",) or shlex.split(on)[0] == "{exe}"
    assert emulators.with_fullscreen("xemu", "{exe} -dvd_path {rom}", True) == "'{exe}' -full-screen -dvd_path '{rom}'"
    assert "-window" in emulators.with_fullscreen("mame", emulators.EMUS["mame"].template, False)
    assert "-video.fs 0" in emulators.with_fullscreen("mednafen", emulators.EMUS["mednafen"].template, False)


def test_ready_hdd_checksums_and_settings(tmp_path, monkeypatch):
    folder = tmp_path / "xemu"
    monkeypatch.setattr(xemuconfig, "data_folders", lambda h=None, w=None: [folder])
    monkeypatch.setattr(xemuconfig, "config_files", lambda h=None, w=None: [folder / "xemu.toml"])
    disk = b"QFI\xfb" + b"x" * 100

    def zipped(data):
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            z.writestr("xbox_hdd.qcow2", data)
        return b.getvalue()
    good = zipped(disk)
    import hashlib
    monkeypatch.setattr(xemuconfig, "READY_HDD_ZIP_SHA256", hashlib.sha256(good).hexdigest())
    monkeypatch.setattr(xemuconfig, "READY_HDD_SHA256", hashlib.sha256(disk).hexdigest())
    ok, msg, p = xemuconfig.get_ready_hdd(fetch=lambda url, dest: Path(dest).write_bytes(b"evil"))
    assert not ok and "checksum" in msg and not (folder / xemuconfig.READY_HDD_NAME).exists()
    ok, msg, p = xemuconfig.get_ready_hdd(fetch=lambda url, dest: Path(dest).write_bytes(good))
    assert ok and p.read_bytes() == disk
    assert xemuconfig.read_files_section((folder / "xemu.toml").read_text())["hdd_path"] == str(p)
    ok, msg, p2 = xemuconfig.get_ready_hdd(fetch=lambda url, dest: (_ for _ in ()).throw(AssertionError("no second download")))
    assert ok and p2 == p
    p.write_bytes(b"used by xemu")                         # xemu wrote to it -> kept as .bak, fresh disk put in place
    ok, msg, p3 = xemuconfig.get_ready_hdd(fetch=lambda url, dest: Path(dest).write_bytes(good))
    baks = list(folder.glob(xemuconfig.READY_HDD_NAME + ".*.bak"))
    assert ok and p3.read_bytes() == disk and len(baks) == 1 and baks[0].read_bytes() == b"used by xemu" and "kept" in msg
    p.write_bytes(b"used again")                           # a bad download puts the old disk back
    ok, msg, _ = xemuconfig.get_ready_hdd(fetch=lambda url, dest: Path(dest).write_bytes(b"evil"))
    assert not ok and p.read_bytes() == b"used again"
    assert xemuconfig.READY_HDD_URL.startswith("https://github.com/xemu-project/")


def iso(path, at):
    with open(path, "wb") as f:
        f.seek(at)
        f.write(xbox.MAGIC)
        f.write(b"\0" * 64)


def test_xiso_detection_and_conversion(tmp_path, monkeypatch):
    x, r, junk = tmp_path / "a.iso", tmp_path / "b.iso", tmp_path / "c.iso"
    iso(x, xbox.XISO_AT)
    iso(r, xbox.REDUMP_AT)
    junk.write_bytes(b"\0" * 10)
    assert xbox.iso_kind(str(x)) == "xiso" and xbox.iso_kind(str(r)) == "redump" and xbox.iso_kind(str(junk)) == "unknown"
    assert xbox.disc_image_for(str(x)) == str(x)
    monkeypatch.setattr(xbox, "find_extract_xiso", lambda: "")
    with pytest.raises(RuntimeError, match="not an XISO"):
        xbox.disc_image_for(str(r), cache_dir=tmp_path / "cache")
    monkeypatch.setattr(xbox, "find_extract_xiso", lambda: "/usr/bin/extract-xiso")

    class P:
        returncode, stdout, stderr = 0, "", ""

    def run(cmd, **k):
        assert cmd[:3] == ["/usr/bin/extract-xiso", "-r", "-d"]
        iso(Path(cmd[3]) / Path(cmd[4]).name, xbox.XISO_AT)
        return P()
    out = xbox.disc_image_for(str(r), runner=run, cache_dir=tmp_path / "cache")
    assert out == str(tmp_path / "cache" / "b.iso") and xbox.iso_kind(str(r)) == "redump"
