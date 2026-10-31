import os

import pytest

from atarilauncher import worldgames


def test_region_tags():
    assert worldgames.region_of("Super Game (Japan).sfc") == "jp"
    assert worldgames.region_of("Game (J) [!].gb") == "jp"
    assert worldgames.region_of("Game (Japan, USA).iso") == "jp"
    assert worldgames.region_of("Game (Korea).nds") == "kr"
    assert worldgames.region_of("Game (China).nds") == "cn"
    assert worldgames.region_of("Game (USA).sfc") == ""
    assert worldgames.region_of("Jumping Jack") == ""


def test_free_list_is_official_links_only():
    for g in worldgames.FREE:
        assert g.url.startswith("https://store.steampowered.com/app/" + g.steam_appid + "/")
        assert g.about and g.year > 1990 and g.region in ("jp", "cn", "kr")
    assert all(worldgames.free_for(r) for r, _ in worldgames.REGIONS)


pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from tests.test_ui_keys import app  # noqa: E402,F401
from tests.test_xemuconfig import make_ui  # noqa: E402


def test_page_tabs(app, tmp_path, monkeypatch):
    ui = make_ui(app, tmp_path, monkeypatch, tmp_path / "home")
    try:
        b = ui.backend
        assert b.pageTitle("worldgames") == "WORLD GAMES"
        rows = b.pageRows("worldgames")
        assert any(r.get("title", "").startswith("Yume Nikki") for r in rows)
        assert b.pageActivate("worldgames", "wgtab:kr") == "refresh"
        assert any(r.get("title", "").startswith("MapleStory") for r in b.pageRows("worldgames"))
        side = ui.win.property("sideList")
        side = side.toVariant() if hasattr(side, "toVariant") else side
        keys = [s["key"] for s in side]
        assert "__world" in keys and "__theme" in keys
        assert b.setupRows()[1]["kind"] == "themepage"
    finally:
        ui.close()
