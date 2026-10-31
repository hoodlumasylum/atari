"""0.5.0: themes (one file each, readable, live, saved) and the Find my BIOS / Find my games pages."""
import os
import time

import pytest

from atarilauncher import themes

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from tests.test_ui_keys import app, pump  # noqa: E402,F401
from tests.test_xemuconfig import make_ui  # noqa: E402
from tests.test_bluetooth_pads import items, texts  # noqa: E402


def test_five_original_themes_all_readable():
    ts = themes.all_themes()
    assert [t.name for t in ts] == ["CodeAque Gold", "Midnight", "Neon", "Light", "Hoodlum Asylum"]
    for t in ts:
        assert themes.problems(t) == [], t.id
    assert themes.get("nope").id == themes.DEFAULT and themes.get("hoodlum-asylum").rain


def test_an_unreadable_theme_file_is_refused_and_a_new_file_is_picked_up(tmp_path, monkeypatch):
    monkeypatch.setattr(themes, "folders", lambda: [tmp_path])
    good = (themes.folders.__wrapped__ if hasattr(themes.folders, "__wrapped__") else None)
    base = open(os.path.join(os.path.dirname(themes.__file__), "themes", "midnight.toml")).read()
    (tmp_path / "mine.toml").write_text(base.replace('name = "Midnight"', 'name = "Mine"'))
    (tmp_path / "bad.toml").write_text(base.replace('text = "#e8ecf6"', 'text = "#0b0f1a"'))
    assert [t.name for t in themes.all_themes()] == ["Mine"]
    del good


def test_theme_applies_live_and_is_saved(app, tmp_path, monkeypatch):
    ui = make_ui(app, tmp_path, monkeypatch, tmp_path / "home")
    try:
        b = ui.backend
        assert ui.win.property("color").name() == "#08090e"
        assert any(r.get("kind") == "themepage" for r in b.setupRows())
        assert "SELECTED" == next(r for r in b.pageRows("theme") if r.get("id") == "th:codeaque-gold")["value"]
        b.pageActivate("theme", "th:light")
        pump(app, 100)
        assert ui.win.property("color").name() == "#eef1f6" and b.store.get_pref("theme") == "light"
        assert not items(ui.win, "rainDrop")
        b.pageActivate("theme", "th:hoodlum-asylum")
        pump(app, 100)
        assert "Rain effect: ON" in texts(b.pageRows("theme"))
        assert b.themeColors["rain"] is True and b.themeColors["redBright"] == "#e8b649"
        if ui.win.property("visibility") != 3 and b.animations:
            assert len(items(ui.win, "rainDrop")) == 70
        b.pageActivate("theme", "thrain")
        assert b.themeColors["rain"] is False and "Rain effect: OFF" in texts(b.pageRows("theme"))
        pump(app, 100)
        assert not items(ui.win, "rainDrop")
    finally:
        ui.close()


def wait(app, cond, secs=8):
    t = time.time()
    while time.time() - t < secs:
        pump(app, 40)
        if cond():
            return True
    return False


def test_find_my_bios_page_looks_by_itself_and_copies(app, tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "Downloads").mkdir(parents=True)
    (home / "Downloads" / "mcpx_1.0.bin").write_bytes(b"\x01" * 512)
    ui = make_ui(app, tmp_path, monkeypatch, home)
    try:
        b = ui.backend
        assert b.pageActivate("addgames", "biosfind") == "page:biosfind"
        b.pageRows("biosfind")                                    # opening the page starts looking (one press)
        assert wait(app, lambda: not b._bf_busy and b._bf_res is not None)
        t = texts(b.pageRows("biosfind"))
        assert "Found 1 BIOS file" in t and "mcpx_1.0.bin" in t and "goes to" in t
        b.pageActivate("biosfind", "bfcopy")
        assert wait(app, lambda: not b._bf_busy)
        assert "Copied 1 file" in texts(b.pageRows("biosfind"))
    finally:
        ui.close()


def test_find_my_games_page(app, tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "Downloads").mkdir(parents=True)
    (home / "Downloads" / "Plumber (USA).nes").write_bytes(b"x" * 100)
    from atarilauncher import findgames
    monkeypatch.setattr(findgames, "default_roots", lambda home=None, drives=None: [home / "Downloads"])
    ui = make_ui(app, tmp_path, monkeypatch, home)
    try:
        b = ui.backend
        b.pageRows("findgames")
        assert wait(app, lambda: not b._fg_busy and b._fg_res is not None)
        t = texts(b.pageRows("findgames"))
        assert "own games and backups" in t and "Plumber (USA)" in t and "Copy 1 game into my games" in t
        b.pageActivate("findgames", "fgmode")
        assert "Move 1 game" in texts(b.pageRows("findgames"))
        b.pageActivate("findgames", "fggo")
        assert wait(app, lambda: not b._fg_busy)
        assert "Moved 1 game" in texts(b.pageRows("findgames"))
        assert (home / "Games/CodeAque/nes/Plumber (USA).nes").is_file() and not (home / "Downloads/Plumber (USA).nes").exists()
    finally:
        ui.close()
