"""0.6.1: Reduce effects (auto on weak chips), grid / list by pad (R3 = V), backdrop and glass parts load."""
from atarilauncher import gpuinfo, gamepad_helper, backend as be, config
from PySide6.QtCore import Qt
from tests.test_ui_keys import app, Ui, pump  # noqa: F401  (the shared Qt app fixture)


def test_weak_gpu_names():
    for r in ["llvmpipe (LLVM 15.0.7, 256 bits)", "Mesa Intel(R) HD Graphics 5500 (BDW GT2)", "Mesa Intel(R) HD Graphics (BYT)",
              "Mesa Intel(R) HD Graphics 505 (APL 3x6)", "SVGA3D; build: RELEASE", "virgl"]:
        assert gpuinfo.is_weak(r), r
    for r in ["Mesa Intel(R) UHD Graphics 620 (KBL GT2)", "Mesa Intel(R) HD Graphics 620 (KBL GT2)", "AMD Radeon Vega 8 Graphics",
              "NVIDIA GeForce GTX 1050/PCIe/SSE2", "Mesa Intel(R) Xe Graphics (TGL GT2)", ""]:
        assert not gpuinfo.is_weak(r), r


def test_env_override(monkeypatch):
    monkeypatch.setenv("CODEAQUE_WEAK_GPU", "1")
    assert gpuinfo.weak_gpu()
    monkeypatch.setenv("CODEAQUE_WEAK_GPU", "0")
    assert not gpuinfo.weak_gpu()


def test_r3_is_grid_list():
    assert gamepad_helper.BUTTON_MAP["rightstick"] == "view"
    assert be.ACTION_KEYS["view"] == Qt.Key_V


def test_config_round_trip(tmp_path):
    p = tmp_path / "config.toml"
    c = config.load_config(p)
    assert c.reduce_effects == "auto" and c.pad_reminder is True
    c.reduce_effects = "on"; c.pad_reminder = False
    config.save_config(c, p)
    c2 = config.load_config(p)
    assert c2.reduce_effects == "on" and c2.pad_reminder is False


def test_effects_setting_cycles_and_v_toggles_list(app, tmp_path, monkeypatch):
    monkeypatch.setenv("CODEAQUE_WEAK_GPU", "1")
    ui = Ui(app, tmp_path, monkeypatch, config_exists=True)
    try:
        b = ui.backend
        assert b.cfg.reduce_effects == "auto" and b.effects is False        # weak chip: effects off by themselves
        row = next(r for r in b.setupRows() if r["kind"] == "effects")
        assert row["value"].startswith("AUTO")
        b.cycleEffects(); assert b.cfg.reduce_effects == "on" and b.effects is False
        b.cycleEffects(); assert b.cfg.reduce_effects == "off" and b.effects is True
        assert ui.win.property("listMode") is False
        ui.key(Qt.Key_V, 100)
        assert ui.win.property("listMode") is True
        ui.key(Qt.Key_V, 100)
        assert ui.win.property("listMode") is False
    finally:
        ui.close()


def test_backdrop_cross_fades_to_the_game_art(app, tmp_path, monkeypatch):
    from PySide6.QtGui import QImage, QColor
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtCore import QUrl
    img = QImage(320, 180, QImage.Format_RGB32); img.fill(QColor("#3366aa"))
    a = tmp_path / "a.png"; img.save(str(a))
    img.fill(QColor("#aa3333")); b = tmp_path / "b.png"; img.save(str(b))
    ui = Ui(app, tmp_path, monkeypatch, config_exists=True)
    try:
        bd = ui.win.findChild(QQuickItem, "homeBackdrop")
        assert bd is not None and bd.property("visible")
        ia, ib = (ui.win.findChild(QQuickItem, n) for n in ("backdropA", "backdropB"))
        bd.setProperty("source", QUrl.fromLocalFile(str(a)).toString()); pump(app, 900)
        shown = [i for i in (ia, ib) if i.property("opacity") > 0.99]
        assert len(shown) == 1 and shown[0].property("progress") == 1.0
        bd.setProperty("source", QUrl.fromLocalFile(str(b)).toString()); pump(app, 900)
        shown2 = [i for i in (ia, ib) if i.property("opacity") > 0.99]
        assert len(shown2) == 1 and shown2[0] is not shown[0]
        assert not ui.warnings, ui.warnings
    finally:
        ui.close()
