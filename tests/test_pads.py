"""Controllers: pads read from the kernel list, SDL GUIDs, and the player-1 binding written into xemu.toml."""
import tomllib

from atarilauncher import pads, xemuconfig

PROC = '''I: Bus=0019 Vendor=0000 Product=0001 Version=0000
N: Name="Power Button"
H: Handlers=kbd event0

I: Bus=0003 Vendor=045e Product=028e Version=0114
N: Name="Microsoft X-Box 360 pad"
H: Handlers=js0 event5 

I: Bus=0003 Vendor=054c Product=09cc Version=8111
N: Name="Wireless Controller Touchpad"
H: Handlers=mouse2 event7

I: Bus=0005 Vendor=054c Product=09cc Version=8100
N: Name="Wireless Controller"
H: Handlers=event6 js1 
'''


def test_only_blocks_with_a_joystick_handler_are_pads():
    ps = pads.parse(PROC)
    assert [p.name for p in ps] == ["Microsoft X-Box 360 pad", "Wireless Controller"]
    assert [p.js for p in ps] == ["js0", "js1"]
    assert [p.how for p in ps] == ["USB", "Bluetooth"]
    assert ps[0].ids == "045e:028e"


def test_guid_matches_the_known_sdl_values():
    ps = pads.parse(PROC)
    assert ps[0].guid == "030000005e0400008e02000014010000"          # the well known SDL value for the Xbox 360 pad
    assert ps[1].guid == "050000004c050000cc09000000810000"          # DualShock 4 over Bluetooth


def test_guid_without_ids_uses_a_name_checksum():
    g = pads.sdl_guid(3, 0, 0, 0, "Odd Pad")
    assert len(g) == 32 and g.startswith("0300")


def test_detect_missing_or_unreadable_file(tmp_path):
    assert pads.detect(str(tmp_path / "nope")) == []
    f = tmp_path / "devs"
    f.write_text(PROC)
    assert len(pads.detect(str(f))) == 2


def data(home):
    d = home / ".var/app/app.xemu.xemu/data/xemu/xemu"
    d.mkdir(parents=True)
    return d / "xemu.toml"


def none(_n):
    return None


def test_set_pad_creates_the_input_tables(tmp_path):
    home = tmp_path / "h"
    ok, files, msg = xemuconfig.set_pad("abcd", home, none)
    assert ok and len(files) == 1
    t = tomllib.loads(open(files[0]).read())
    assert t["input"]["auto_bind"] is True
    assert t["input"]["bindings"] == {"port1_driver": "usb-xbox-gamepad", "port1": "abcd"}
    assert xemuconfig.read_pad(home, none)["guid"] == "abcd"


def test_set_pad_keeps_other_settings_and_a_backup(tmp_path):
    home = tmp_path / "h"
    toml = data(home)
    toml.write_text("# mine\n[general]\nshow_welcome = false\n\n[input]\nauto_bind = false\n\n[input.bindings]\nport1 = 'old'\nport2 = 'two'\n\n[sys.files]\nhdd_path = 'x'\n")
    ok, files, _ = xemuconfig.set_pad("new", home, none)
    assert ok
    text = toml.read_text()
    t = tomllib.loads(text)
    assert "# mine" in text
    assert t["general"]["show_welcome"] is False and t["sys"]["files"]["hdd_path"] == "x"
    assert t["input"]["auto_bind"] is True
    assert t["input"]["bindings"]["port1"] == "new" and t["input"]["bindings"]["port2"] == "two"
    assert (toml.parent / xemuconfig.BACKUP_NAME).read_text().startswith("# mine")
    again = xemuconfig.set_pad("new", home, none)
    assert again[0] and again[1] == []                                   # second time: nothing to change


def test_set_pad_refuses_a_broken_file(tmp_path):
    home = tmp_path / "h"
    toml = data(home)
    toml.write_text("this is [[ not toml")
    ok, files, msg = xemuconfig.set_pad("g", home, none)
    assert not ok and files == [] and "Repair" in msg
    assert toml.read_text() == "this is [[ not toml"


def test_read_pad_without_a_file(tmp_path):
    assert xemuconfig.read_pad(tmp_path / "h", none)["guid"] == ""


# ------------------------------------------------------------------ the page in CodeAque
import os  # noqa: E402

import pytest  # noqa: E402

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt  # noqa: E402
from tests.test_ui_keys import Ui, app, pump  # noqa: E402,F401
from tests.test_xemuconfig import make_ui  # noqa: E402,F401


def pad_file(tmp_path, monkeypatch, text=PROC):
    f = tmp_path / "devices"
    f.write_text(text)
    monkeypatch.setattr(pads, "PROC_DEVICES", str(f))
    monkeypatch.setattr(pads, "detect", lambda path=str(f): pads.parse(open(path).read()))
    return f


def texts(rows):
    return " | ".join(r["title"] + " " + r.get("detail", "") for r in rows)


def test_controllers_page_lists_pads_and_sets_up_player_one(app, tmp_path, monkeypatch):
    home = tmp_path / "home"
    pad_file(tmp_path, monkeypatch)
    ui = make_ui(app, tmp_path, monkeypatch, home)
    try:
        b = ui.backend
        assert b.pageTitle("controllers") == "CONTROLLERS"
        rows = b.pageRows("controllers")
        t = texts(rows)
        assert "Microsoft X-Box 360 pad" in t and "Wireless Controller" in t and "030000005e0400008e02000014010000" in t
        assert "has no settings file yet" in t and "Honest note" in t
        ids = [r.get("id") for r in rows]
        assert "ctxemu:0" in ids and "ctxemu:1" in ids and "cttest" in ids
        assert b.pageActivate("controllers", "ctxemu:1") == "refresh"
        t = texts(b.pageRows("controllers"))
        assert "Wireless Controller is now player 1" in t and "050000004c050000cc09000000810000" in t
        got = xemuconfig.read_pad()
        assert got["guid"] == "050000004c050000cc09000000810000" and got["driver"] == "usb-xbox-gamepad" and got["auto_bind"] is True
        assert b.pageActivate("controllers", "ctxemu:9") == "refresh" and "no longer plugged in" in texts(b.pageRows("controllers"))
    finally:
        ui.close()


def test_controllers_page_with_no_pad_says_what_to_do(app, tmp_path, monkeypatch):
    pad_file(tmp_path, monkeypatch, "I: Bus=0019 Vendor=0000 Product=0001 Version=0000\nN: Name=\"Power Button\"\nH: Handlers=kbd event0\n")
    ui = make_ui(app, tmp_path, monkeypatch, tmp_path / "home")
    try:
        rows = ui.backend.pageRows("controllers")
        assert "No gamepad found" in texts(rows) and not [r for r in rows if str(r.get("id", "")).startswith("ctxemu")]
    finally:
        ui.close()


def test_live_button_readout_and_the_pad_does_not_move_the_menu_while_testing(app, tmp_path, monkeypatch):
    pad_file(tmp_path, monkeypatch)
    ui = make_ui(app, tmp_path, monkeypatch, tmp_path / "home")
    try:
        b = ui.backend
        sent = []
        monkeypatch.setattr(b, "send_action", lambda a: sent.append(a))
        b._read_gamepad_text = None
        b.pageRows("controllers")
        b._pad_info_line("#btn a")
        assert b._pad_events == ["A pressed"] or b._pad_events == []          # not testing yet: still shown once the page is open
        b.pageActivate("controllers", "cttest")
        b._pad_info_line("#btn leftshoulder")
        b._pad_info_line("#axis lefty up")
        b._pad_info_line("#axis triggerright pulled")
        b._pad_info_line("#btn dpad_left")
        t = texts(b.pageRows("controllers"))
        assert "Left bumper (LB) pressed" in t and "Left stick up" in t and "Right trigger (RT) pulled" in t and "D-pad left pressed" in t
        assert "Testing: press buttons" in t and b.pad_testing
        # menu actions from the pad are held back while testing, and flow again after
        class P:
            def readAllStandardOutput(self):
                return b"down\n#btn b\n"
        b._gamepad_proc = P()
        b._read_gamepad()
        assert sent == [] and b._pad_events[0] == "B pressed"
        b.pageActivate("controllers", "ctstop")
        b._read_gamepad()
        assert sent == ["down"]
        assert len(b._pad_events) <= 8
    finally:
        b._gamepad_proc = None
        ui.close()


def test_controllers_is_in_the_left_list_and_in_settings(app, tmp_path, monkeypatch):
    pad_file(tmp_path, monkeypatch)
    ui = make_ui(app, tmp_path, monkeypatch, tmp_path / "home")
    try:
        b = ui.backend
        side = ui.win.property("sideList").toVariant()
        keys = [s["key"] for s in side]
        assert keys[-2:] == ["__settings", "__controllers"] and side[-1]["label"] == "Controllers"
        assert any(r.get("kind") == "controllerspage" for r in b.setupRows())
    finally:
        ui.close()


def test_pressing_controllers_in_the_left_list_opens_the_page(app, tmp_path, monkeypatch):
    pad_file(tmp_path, monkeypatch)
    ui = make_ui(app, tmp_path, monkeypatch, tmp_path / "home")
    try:
        from PySide6.QtCore import QMetaObject, Q_ARG
        n = len(ui.win.property("sideList").toVariant())
        QMetaObject.invokeMethod(ui.win, "activateSide", Q_ARG("QVariant", n - 1))
        pump(app, 200)
        assert ui.mode == "page" and ui.win.property("pageName") == "controllers"
    finally:
        ui.close()
