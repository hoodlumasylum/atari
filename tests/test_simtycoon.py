from pathlib import Path

from atarilauncher import simtycoon, appinstall, apps


def _th(root: Path) -> Path:
    d = root / "GOG Games" / "Theme Hospital"
    (d / "DATA").mkdir(parents=True)
    (d / "DATA" / "VBLK-0.TAB").write_bytes(b"x")
    (d / "LEVELS").mkdir()
    return d


def test_titles_and_tags():
    assert simtycoon.is_sim_title("Theme Hospital")
    assert simtycoon.is_sim_title("RollerCoaster Tycoon 2")
    assert simtycoon.is_sim_title("Cities: Skylines")
    assert not simtycoon.is_sim_title("Halo 2")
    assert simtycoon.in_section("g1", "Halo 2", ["g1"], [])
    assert not simtycoon.in_section("g2", "SimCity 2000", [], ["g2"])
    assert simtycoon.in_section("g3", "Some Game", [], [], genre="Simulation, Strategy")


def test_find_theme_hospital_case_insensitive(tmp_path):
    d = _th(tmp_path)
    roots = simtycoon.search_roots(home=tmp_path)
    assert simtycoon.find_data("th", roots) == str(d)
    assert simtycoon.find_data("rct2", roots) == ""


def test_find_rct2_in_steam(tmp_path):
    d = tmp_path / "lib" / "steamapps" / "common" / "Rollercoaster Tycoon 2" / "Data"
    d.mkdir(parents=True)
    (d / "g1.dat").write_bytes(b"x")
    roots = simtycoon.search_roots(home=tmp_path, steam_libraries=[tmp_path / "lib"])
    assert simtycoon.find_data("rct2", roots).endswith("Rollercoaster Tycoon 2")


def test_point_corsixth_keeps_other_settings(tmp_path):
    cfg = tmp_path / ".config/CorsixTH/config.txt"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("language = [[English]]\ntheme_hospital_install = [[X:\\old]]\n")
    calls = []
    written = simtycoon.point_engine_at("corsixth", "/d/TH", home=tmp_path, which=lambda x: "/usr/bin/flatpak",
                                        runner=lambda *a, **k: calls.append(a[0]))
    text = cfg.read_text()
    assert "language = [[English]]" in text and "theme_hospital_install = [[/d/TH]]" in text and "old" not in text
    assert len(written) == 2       # native + Flatpak config
    assert calls[0][:3] == ["flatpak", "override", "--user"] and "--filesystem=/d/TH:ro" in calls[0]


def test_point_openrct2_section(tmp_path):
    simtycoon.point_engine_at("openrct2", "/d/RCT2", home=tmp_path, which=lambda x: None)
    text = (tmp_path / ".config/OpenRCT2/config.ini").read_text()
    assert "[general]" in text and 'game_path = "/d/RCT2"' in text


def test_engines_installable_only_on_request():
    for e in simtycoon.ENGINES:
        assert appinstall.target_for(e.app.id) is not None
        assert e.app.id not in appinstall.all_ids()      # never part of "Install everything"
    assert simtycoon.BY_ID["openttd"].needs_data is False
    assert "Theme Hospital files" in simtycoon.NO_TH_DATA


def test_no_wine_word_in_helper_titles():
    assert all("wine" not in a.title.lower() for a in apps.HELPERS)


# ------------------------------------------------------------------ in CodeAque
import os  # noqa: E402

import pytest  # noqa: E402

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from tests.test_ui_keys import app, pump  # noqa: E402,F401
from tests.test_xemuconfig import make_ui  # noqa: E402


def _wait(app, cond, secs=5.0):
    import time
    t = time.time()
    while time.time() - t < secs and not cond():
        pump(app, 50)


def test_sim_page_hero_needs_files_then_finds_them(app, tmp_path, monkeypatch):
    home = tmp_path / "home"
    ui = make_ui(app, tmp_path, monkeypatch, home)
    try:
        b = ui.backend
        assert b.pageTitle("simtycoon") == "SIM & TYCOON"
        b.pageRows("simtycoon")
        _wait(app, lambda: not getattr(b, "_sim_busy", False))
        hero = b.pageRows("simtycoon")[0]
        assert hero["id"] == "simhero" and hero["value"] == "NEED FILES" and "You need your own Theme Hospital files" in hero["detail"]
        _th(home)
        assert b.pageActivate("simtycoon", "simlook") == "refresh"
        _wait(app, lambda: not getattr(b, "_sim_busy", False))
        hero = b.pageRows("simtycoon")[0]
        assert hero["value"] in ("INSTALL", "PLAY") and "Theme Hospital" in hero["detail"]
        ids = [r.get("id") for r in b.pageRows("simtycoon")]
        assert {"simeng:corsixth", "simeng:openrct2", "simeng:openttd", "simeng:augustus", "simpick"} <= set(ids)
    finally:
        ui.close()


def test_side_list_has_sim_and_copy_steam_log(app, tmp_path, monkeypatch):
    ui = make_ui(app, tmp_path, monkeypatch, tmp_path / "home")
    try:
        side = ui.win.property("sideList").toVariant() if hasattr(ui.win.property("sideList"), "toVariant") else ui.win.property("sideList")
        assert "__sim" in [s["key"] for s in side]
        b = ui.backend
        b._running, b._running_appid = True, "4242"
        b.runningStatusChanged.emit()
        assert b.runningSteam
        path = b.copySteamLog()
        assert path.endswith("CodeAque-steam-log.txt") and "CodeAque Steam log" in open(path).read()
        b._running, b._running_appid = False, ""
    finally:
        ui.close()
