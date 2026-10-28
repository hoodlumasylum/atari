"""End-to-end: Backend launches a fake emulator, tracks play time, recent list and favorites."""
import os
import stat
import time

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication  # noqa: E402

from atarilauncher import backend as be  # noqa: E402
from atarilauncher import config  # noqa: E402
from atarilauncher.store import Store  # noqa: E402


def test_launch_records_playtime_recent_and_favorite(tmp_path, monkeypatch):
    monkeypatch.setenv("ATARI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(be, "MIN_PLAYTIME_SEC", 1)
    app = QCoreApplication.instance() or QCoreApplication([])
    roms = tmp_path / "roms"
    roms.mkdir()
    (roms / "Cool Game (USA).gba").write_bytes(b"x")
    emu = tmp_path / "emu"
    emu.write_text("#!/bin/sh\nsleep 1.3\n")
    emu.chmod(emu.stat().st_mode | stat.S_IEXEC)
    cfg = config.default_config()
    cfg.steam_enabled = False
    cfg.systems["gba"].roms = [str(roms)]
    cfg.systems["gba"].command = f"{emu} {{rom}}"
    cfg.first_run = False
    store = Store(tmp_path / "state.json")
    b = be.Backend(cfg=cfg, store=store, enable_gamepad=False)
    b.setFilter("all")
    assert b.model.rowCount() == 1 and b.totalGames == 1
    assert any(f["key"] == "gba" for f in b.filters)

    b.launch(0)
    assert b.running
    deadline = time.time() + 15
    while b.running and time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)
    assert not b.running
    gid = b.model.game_at(0).gid
    assert store.playtime(gid) >= 1
    assert store.recent_ids() == [gid]
    assert b.toast.startswith("Welcome back")

    b.toggleFavorite(0)
    assert store.is_favorite(gid)
    b.setFilter("favorites")
    assert b.model.rowCount() == 1
    b.toggleFavorite(0)
    assert b.model.rowCount() == 0 and "No favorites" in b.emptyMessage()


def test_launch_missing_emulator_shows_friendly_message(tmp_path, monkeypatch):
    monkeypatch.setenv("ATARI_DATA_DIR", str(tmp_path / "data"))
    app = QCoreApplication.instance() or QCoreApplication([])
    roms = tmp_path / "roms"
    roms.mkdir()
    (roms / "g.nes").write_bytes(b"x")
    cfg = config.default_config()
    cfg.steam_enabled = False
    cfg.systems["nes"].roms = [str(roms)]
    cfg.systems["nes"].command = "no-such-emulator-abc {rom}"
    cfg.first_run = False
    b = be.Backend(cfg=cfg, store=Store(tmp_path / "s.json"), enable_gamepad=False)
    b.setFilter("all")
    b.launch(0)
    deadline = time.time() + 5
    while b.running and time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
    assert "Could not find" in b.toast
