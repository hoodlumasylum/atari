from pathlib import Path

from atarilauncher import usbdrive
from atarilauncher.importer import Drive
from tests.test_xemuconfig import make_ui, app  # noqa: F401
from tests.test_ui_keys import pump


def test_watcher_sees_only_new_sticks():
    state = {"d": [Drive("/media/u/OLD", "OLD")]}
    w = usbdrive.Watcher(lambda: state["d"])
    assert w.tick() == []
    state["d"] = [Drive("/media/u/OLD", "OLD"), Drive("/media/u/NEW", "NEW")]
    assert [d.label for d in w.tick()] == ["NEW"] and w.tick() == []


def test_prepare_makes_folders_and_never_deletes(tmp_path):
    (tmp_path / "keep.txt").write_text("mine")
    ok, msg = usbdrive.prepare(str(tmp_path))
    assert ok and (tmp_path / "CodeAque/snes").is_dir() and (tmp_path / "CodeAque/BIOS").is_dir()
    assert "do not include" not in msg and (tmp_path / "keep.txt").read_text() == "mine"
    assert "does not include or download any commercial games" in (tmp_path / "CodeAque/README.txt").read_text()
    assert usbdrive.game_root(str(tmp_path)) == tmp_path / "CodeAque"


def test_plugged_stick_is_scanned_and_can_be_played_from(app, tmp_path, monkeypatch):  # noqa: F811
    stick = tmp_path / "STICK"
    (stick / "CodeAque/nes").mkdir(parents=True)
    (stick / "CodeAque/nes/Homebrew Hero.nes").write_bytes(b"NES\x1a" + b"\0" * 40000)
    ui = make_ui(app, tmp_path, monkeypatch, tmp_path / "home")
    try:
        b = ui.backend
        state = {"d": []}
        b._usb_watch = usbdrive.Watcher(lambda: state["d"])
        asked = []
        b.pageRequested.connect(asked.append)
        state["d"] = [Drive(str(stick), "STICK")]
        b._usb_tick()
        assert asked == ["findgames"]
        for _ in range(300):
            pump(app, 20)
            if not b._fg_busy and b._fg_res is not None:
                break
        rows = b.pageRows("findgames")
        assert any(r.get("id") == "usbplay" for r in rows), [r["title"] for r in rows]
        assert any(e.system == "nes" for e in b._fg_res.entries)
        b.pageActivate("findgames", "usbplay")
        assert str(stick / "CodeAque/nes") in b.cfg.systems["nes"].roms
    finally:
        ui.close()
