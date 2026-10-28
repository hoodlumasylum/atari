"""Zipped BIOS packs: one-button unpack with a progress bar, find the files each emulator needs, copy them, say what is missing."""
import io
import os
import tarfile
import threading
import zipfile
from pathlib import Path

import pytest

from atarilauncher import bios, files

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from tests.test_features_ui import conf, wait_for  # noqa: E402
from tests.test_ui_keys import Ui, app, pump  # noqa: E402,F401

XBOX = {"Xbox/mcpx_1.0.bin": b"M" * 512, "Xbox/Complex_4627v1.03.bin": b"B" * 4096,
        "Xbox/my disk.qcow2": b"Q" * 200_000, "Xbox/eeprom.bin": b"E" * 256, "readme.txt": b"hello"}


def make_zip(path, entries):
    with zipfile.ZipFile(path, "w") as z:
        for n, d in entries.items():
            z.writestr(n, d)
    return path


def make_tar(path, entries):
    with tarfile.open(path, "w:gz") as t:
        for n, d in entries.items():
            ti = tarfile.TarInfo(n)
            ti.size = len(d)
            t.addfile(ti, io.BytesIO(d))
    return path


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "Downloads").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("ATARI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ATARI_CONFIG_DIR", str(tmp_path / "conf"))
    return home


# ------------------------------------------------------------------ what is recognised
def test_xbox_files_are_recognised_whatever_the_disk_image_or_flash_file_is_called(tmp_path):
    for name, canon, system in (("mcpx_1.0.bin", "mcpx_1.0.bin", "xbox"), ("Complex_4627.bin", "Complex_4627v1.03.bin", "xbox"),
                                ("xbox_bios.bin", "Complex_4627v1.03.bin", "xbox"),
                                ("My Xbox Disk.QCOW2", "xbox_hdd.qcow2", "xbox"), ("eeprom.bin", "eeprom.bin", "xbox")):
        p = tmp_path / name
        p.write_bytes(b"x" * 300)
        it = bios.identify(p)
        assert it is not None and it.system == "xbox" and it.known.name == canon and it.targets == ("xemu",), name


def test_scan_finds_the_xbox_files_in_an_unpacked_pack_and_ignores_the_rest(tmp_path):
    for n, d in XBOX.items():
        f = tmp_path / n
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(d)
    res = bios.scan_for_bios(tmp_path)
    assert sorted(i.known.name for i in res.items) == ["Complex_4627v1.03.bin", "eeprom.bin", "mcpx_1.0.bin", "xbox_hdd.qcow2"]


def test_what_is_still_missing(env):
    assert bios.missing_detail("xbox", home=env) == ["mcpx_1.0.bin", "Complex_4627v1.03.bin", "xbox_hdd.qcow2"]
    assert bios.missing_detail("xbox", {"mcpx_1.0.bin", "xbox_hdd.qcow2"}, home=env) == ["Complex_4627v1.03.bin"]
    assert bios.missing_detail("xbox", {"mcpx_1.0.bin", "xbox_hdd.qcow2", "Complex_4627v1.03.bin"}, home=env) == []
    assert bios.missing_detail("ps2", home=env) and bios.missing_detail("ps3", home=env) == []
    assert "one of" in bios.missing_detail("saturn", home=env)[0]


def test_pack_summary_says_found_everything_or_what_is_missing(tmp_path, env):
    def item(n):
        p = tmp_path / n
        p.write_bytes(b"x" * 300)
        return bios.identify(p)
    full = bios.pack_summary([item("mcpx_1.0.bin"), item("Complex_4627.bin"), item("d.qcow2")], env)
    assert full == ["Xbox Classic: found everything it needs."]
    part = bios.pack_summary([item("mcpx_1.0.bin")], env)
    assert "still missing Complex_4627v1.03.bin, xbox_hdd.qcow2" in part[0]


# ------------------------------------------------------------------ unpacking from anywhere with progress
def test_extract_into_a_work_folder_from_a_usb_stick_and_reports_progress(tmp_path, env):
    usb = tmp_path / "usb"
    usb.mkdir()
    z = make_zip(usb / "pack.zip", XBOX)
    dest = tmp_path / "work" / "pack"
    seen = []
    res = files.extract(z, progress=seen.append, into=dest)
    assert res.ok and res.dest == dest and (dest / "Xbox" / "mcpx_1.0.bin").is_file()
    assert seen and seen[-1].fraction == 1.0 and any(p.name for p in seen)
    # the same without `into` is still refused outside Downloads / Games / Videos
    assert not files.extract(z, home=env).ok
    t = make_tar(usb / "pack.tar.gz", XBOX)
    assert files.extract(t, into=tmp_path / "work" / "t").ok and (tmp_path / "work" / "t" / "Xbox" / "eeprom.bin").is_file()


def test_cancel_removes_the_half_unpacked_folder(tmp_path, env):
    z = make_zip(tmp_path / "pack.zip", XBOX)
    ev = threading.Event()
    ev.set()
    dest = tmp_path / "work" / "pack"
    res = files.extract(z, cancel=ev, into=dest)
    assert not res.ok and not dest.exists()


# ------------------------------------------------------------------ the whole flow in the app
def states_of(ui):
    seen, prog = [], []
    ui.backend.importChanged.connect(lambda: seen.append(ui.backend.importState))
    ui.backend.importProgressChanged.connect(lambda: prog.append((ui.backend.importProgress, ui.backend.importCurrent)))
    return seen, prog


def xemu_files(home):
    return {p.name: p for p in home.rglob("*") if p.is_file() and p.parent.name == "xemu" and p.parent.parent.name == "xemu"}


def test_full_pack_flow_copies_xbox_files_and_deletes_the_unpacked_copy(app, tmp_path, monkeypatch, env):
    conf(tmp_path)
    z = make_zip(tmp_path / "usb-pack.zip", XBOX)
    ui = Ui(app, tmp_path, monkeypatch, config_exists=True, home=env)
    try:
        b = ui.backend
        assert not [w for w in ui.warnings if "ImportScreen" in w]
        b.openImportKind("bios")
        assert any(r["kind"] == "pack" for r in b.importRows())
        seen, prog = states_of(ui)
        b.startImportScan(str(z))
        assert b.importState == "unpacking" and "Unpacking usb-pack.zip" in b.importMessage
        assert wait_for(app, lambda: b.importState == "list", 15)
        assert "unpacking" in seen
        assert (1.0, ) == (max(p[0] for p in prog),)
        msg = b.importMessage
        assert "Found 4 BIOS" in msg and "in the pack usb-pack.zip" in msg and "Xbox Classic: found everything it needs." in msg
        assert b.import_model.rowCount() == 4
        b.setAllImport(True)
        b.startImportCopy()
        assert wait_for(app, lambda: b.importState == "done", 20)
        got = xemu_files(env)
        assert {"mcpx_1.0.bin", "Complex_4627v1.03.bin", "xbox_hdd.qcow2", "eeprom.bin"} <= set(got)
        assert got["xbox_hdd.qcow2"].read_bytes() == b"Q" * 200_000
        assert (got["mcpx_1.0.bin"].parent / "xemu.toml").is_file()          # xemu is pointed at the files
        assert "Copied 4 BIOS" in b.importMessage and "deleted" in b.importMessage and "Nothing else is missing" in b.importMessage
        assert not (tmp_path / "data" / "bios-unpack").exists()
        assert z.is_file()                                                   # the user's pack is never touched
        assert bios.missing_for("xbox", env)[0] == "ok"
    finally:
        pass


def test_a_partial_pack_lists_what_is_still_missing_after_the_copy(app, tmp_path, monkeypatch, env):
    conf(tmp_path)
    z = make_tar(tmp_path / "half.tar.gz", {"a/mcpx_1.0.bin": b"M" * 512})
    ui = Ui(app, tmp_path, monkeypatch, config_exists=True, home=env)
    b = ui.backend
    b.openImportKind("bios")
    b.startImportScan(str(z))
    assert wait_for(app, lambda: b.importState == "list", 15)
    assert "still missing Complex_4627v1.03.bin, xbox_hdd.qcow2" in b.importMessage
    b.setAllImport(True)
    b.startImportCopy()
    assert wait_for(app, lambda: b.importState == "done", 20)
    assert "Still missing: Xbox Classic still needs Complex_4627v1.03.bin, xbox_hdd.qcow2" in b.importMessage


def test_pack_without_bios_files_and_not_an_archive(app, tmp_path, monkeypatch, env):
    conf(tmp_path)
    ui = Ui(app, tmp_path, monkeypatch, config_exists=True, home=env)
    b = ui.backend
    b.openImportKind("bios")
    b.startImportScan(str(make_zip(tmp_path / "empty.zip", {"x.txt": b"1"})))
    assert wait_for(app, lambda: b.importState == "list", 15)
    assert "No known BIOS files found in the pack empty.zip" in b.importMessage
    assert not (tmp_path / "data" / "bios-unpack").exists()
    b.openImportKind("bios")
    odd = tmp_path / "notes.pdf"
    odd.write_bytes(b"x")
    b.startImportScan(str(odd))
    assert b.importState == "drives" and "not a folder or a BIOS pack" in b.importMessage


def test_cancel_while_unpacking_goes_back_and_cleans_up(app, tmp_path, monkeypatch, env):
    conf(tmp_path)
    z = make_zip(tmp_path / "pack.zip", XBOX)
    ui = Ui(app, tmp_path, monkeypatch, config_exists=True, home=env)
    b = ui.backend
    started = threading.Event()
    real = files.extract

    def slow(archive, password="", progress=None, cancel=None, **kw):
        started.set()
        for _ in range(100):
            if cancel.is_set():
                break
            threading.Event().wait(0.02)
        return real(archive, password, progress, cancel, **kw)
    monkeypatch.setattr(files, "extract", slow)
    b.openImportKind("bios")
    b.startImportScan(str(z))
    assert wait_for(app, started.is_set, 5)
    b.cancelImport()
    assert b.importState == "drives"
    pump(app, 500)
    assert b.importState == "drives"
    assert wait_for(app, lambda: not list((tmp_path / "data" / "bios-unpack").glob("*")) if (tmp_path / "data" / "bios-unpack").exists() else True, 5)


def test_protected_pack_asks_for_the_password_and_gives_up_politely(app, tmp_path, monkeypatch, env):
    conf(tmp_path)
    z = make_zip(tmp_path / "pack.zip", XBOX)
    ui = Ui(app, tmp_path, monkeypatch, config_exists=True, home=env)
    b = ui.backend
    monkeypatch.setattr(files, "extract", lambda *a, **k: files.Extraction(False, "protected", needs_password=True))
    asked = []
    monkeypatch.setattr(b, "ask_text_blocking", lambda *a, **k: asked.append(a) or "")
    b.openImportKind("bios")
    b.startImportScan(str(z))
    assert wait_for(app, lambda: b.importState == "drives", 10)
    assert asked and "No password was entered" in b.importMessage


def test_a_missing_7z_tool_is_explained(app, tmp_path, monkeypatch, env):
    conf(tmp_path)
    ui = Ui(app, tmp_path, monkeypatch, config_exists=True, home=env)
    b = ui.backend
    monkeypatch.setattr(files, "extract", lambda *a, **k: files.Extraction(False, "Code needs 7-Zip to open .7z files.", needs_tool="7zip"))
    f = tmp_path / "p.7z"
    f.write_bytes(b"x")
    b.openImportKind("bios")
    b.startImportScan(str(f))
    assert wait_for(app, lambda: b.importState == "drives", 10)
    assert "7-Zip" in b.importMessage and "Emulators" in b.importMessage


# ------------------------------------------------------------------ picking the pack
def test_pick_from_my_files_and_the_file_chooser(app, tmp_path, monkeypatch, env):
    conf(tmp_path)
    z = make_zip(env / "Downloads" / "bios pack.zip", XBOX)
    (env / "Downloads" / "pic.png").write_bytes(b"x")
    ui = Ui(app, tmp_path, monkeypatch, config_exists=True, home=env)
    try:
        b = ui.backend
        data = b.listFiles(str(env / "Downloads"), "archive")
        assert [f["name"] for f in data["files"]] == ["bios pack.zip"]
        make_tar(env / "Downloads" / "x.tar.gz", XBOX)
        assert [f["name"] for f in b.listFiles(str(env / "Downloads"), "archive")["files"]] == ["bios pack.zip", "x.tar.gz"]
        b._fm_pick = z
        rows = b.pageRows("fileact")
        assert any(r.get("id") == "fmbios" and r["title"] == "Use as BIOS pack" for r in rows)
        assert b.pageActivate("fileact", "fmbios") == "import:biospick"
        b.openImportKind("bios")
        b.importBiosFromPick("")
        assert wait_for(app, lambda: b.importState == "list", 15)
        assert "Xbox Classic" in b.importMessage
        # a non-archive file in My files has no such button
        b._fm_pick = env / "Downloads" / "pic.png"
        assert not any(r.get("id") == "fmbios" for r in b.pageRows("fileact"))
        # the games importer has no pack row
        b.openImportKind("games")
        assert not any(r["kind"] == "pack" for r in b.importRows())
    finally:
        pass
