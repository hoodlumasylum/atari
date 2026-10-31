"""0.5.0: pairing Bluetooth controllers (bluetoothctl), controller batteries in the top bar, Screen to TV."""
import os
import subprocess
import time

import pytest

from atarilauncher import bluetooth, padbattery, pads, rootauth, screentv

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from tests.test_ui_keys import app, pump  # noqa: E402,F401
from tests.test_xemuconfig import make_ui  # noqa: E402


class R:
    def __init__(self, out="", rc=0, err=""):
        self.stdout, self.returncode, self.stderr = out, rc, err


class FakeBt:
    """A pretend bluetoothctl. state: powered, present, blocked; devices: {mac: info text}."""

    def __init__(self, powered=True, present=True, blocked=False):
        self.powered, self.present, self.blocked = powered, present, blocked
        self.calls = []
        self.paired = set()
        self.pair_out = "Attempting to pair with AA:BB:CC:DD:EE:01\nPairing successful\n"
        self.names = {"AA:BB:CC:DD:EE:01": ("Wireless Controller", "input-gaming"), "AA:BB:CC:DD:EE:02": ("Kitchen Speaker", "audio-card")}

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        if cmd[0] != "bluetoothctl":
            return R("", 0)
        a = cmd[1:]
        if a == ["show"]:
            if not self.present:
                return R("No default controller available\n", 1)
            return R(f"Controller 00:11:22:33:44:55 (public)\n\tPowered: {'yes' if self.powered else 'no'}\n"
                     + ("\tPowerState: off-blocked\n" if self.blocked else ""))
        if a == ["power", "on"]:
            if self.blocked:
                return R("Failed to set power on: org.bluez.Error.Blocked\n", 1)
            self.powered = True
            return R("Changing power on succeeded\n")
        if a[:1] == ["--timeout"]:
            return R("Discovery started\n[NEW] Device AA:BB:CC:DD:EE:01 Wireless Controller\n[NEW] Device AA:BB:CC:DD:EE:02 Kitchen Speaker\n")
        if a == ["devices"]:
            return R("".join(f"Device {m} {n}\n" for m, (n, _i) in self.names.items()))
        if a[0] == "info":
            n, i = self.names[a[1]]
            return R(f"Device {a[1]} (public)\n\tName: {n}\n\tIcon: {i}\n\tPaired: {'yes' if a[1] in self.paired else 'no'}\n"
                     f"\tTrusted: no\n\tConnected: {'yes' if a[1] in self.paired else 'no'}\n\tBattery Percentage: 0x4b (75)\n")
        if a[0] == "pair":
            if "successful" in self.pair_out:
                self.paired.add(a[1])
            return R(self.pair_out, 0 if "successful" in self.pair_out else 1)
        if a[0] == "trust":
            return R("Changing AA trust succeeded\n")
        if a[0] == "connect":
            return R("Attempting to connect\nConnection successful\n")
        if a[0] == "remove":
            self.paired.discard(a[1])
            return R("Device has been removed\n")
        return R("", 1)


def which_all(n):
    return "/usr/bin/" + n


def test_bluetoothctl_output_is_read():
    assert bluetooth.parse_devices("Device AA:BB:CC:DD:EE:01 Pad One\n[NEW] Device 11:22:33:44:55:66 Two\n[DEL] Device 00:00:00:00:00:01 X\n") == \
        [("AA:BB:CC:DD:EE:01", "Pad One"), ("11:22:33:44:55:66", "Two")]
    d = bluetooth.parse_info("AA:BB:CC:DD:EE:01", "", "\tName: Pro Controller\n\tIcon: input-gaming\n\tPaired: yes\n\tConnected: no\n\tBattery Percentage: 0x32 (50)\n")
    assert d.name == "Pro Controller" and d.is_pad and d.paired and not d.connected and d.battery == 50
    assert not bluetooth.parse_info("x", "Speaker", "\tIcon: audio-card\n").is_pad


def test_scan_lists_controllers_first_and_pairs_trusts_connects():
    bt = FakeBt()
    found = bluetooth.scan(bt, seconds=1)
    assert [d.name for d in found] == ["Wireless Controller", "Kitchen Speaker"] and found[0].is_pad
    assert ["bluetoothctl", "--timeout", "1", "scan", "on"] in bt.calls
    steps = []
    ok, text = bluetooth.connect_pad("AA:BB:CC:DD:EE:01", bt, steps.append)
    assert ok and "Connected" in text
    order = [c[1] for c in bt.calls if c[1] in ("pair", "trust", "connect")]
    assert order == ["pair", "trust", "connect"] and len(steps) == 3


def test_pairing_failures_are_explained():
    bt = FakeBt()
    bt.pair_out = "Failed to pair: org.bluez.Error.AuthenticationTimeout\n"
    ok, text = bluetooth.connect_pad("AA:BB:CC:DD:EE:01", bt)
    assert not ok and "pairing mode again" in text
    bt.pair_out = "Failed to pair: org.bluez.Error.AlreadyExists\n"
    assert bluetooth.connect_pad("AA:BB:CC:DD:EE:01", bt)[0]                # already paired: carry on to trust + connect
    assert not bluetooth.connect_pad("not-a-mac", bt)[0]


def test_bluetooth_is_switched_on_without_a_password_when_it_is_only_off():
    bt = FakeBt(powered=False)
    ok, text = bluetooth.ensure_on(bt, which_all)
    assert ok and not any(c[0] in ("sudo", "pkexec") for c in bt.calls)


def test_blocked_bluetooth_asks_for_the_password_in_codeaque(monkeypatch):
    bt = FakeBt(powered=False, blocked=True)
    asked = []
    monkeypatch.setattr(rootauth, "prepare", lambda cmd, which=None, runner=None: (asked.append(cmd) or ["sudo", "-S", "--", *cmd[1:]], b"pw\n", None))

    real = bt.__call__

    def run(cmd, **kw):
        if cmd[:3] == ["sudo", "-S", "--"] and cmd[3:] == ["rfkill", "unblock", "bluetooth"]:
            assert kw.get("input") == "pw\n"
            bt.blocked = False
            return R("")
        return real(cmd, **kw)
    ok, text = bluetooth.ensure_on(run, which_all)
    assert ok and asked in ([], [["pkexec", "rfkill", "unblock", "bluetooth"]])   # 0.5.2: tries without a password first


def test_no_tools_or_no_adapter_say_so():
    assert "sudo apt install bluez" in bluetooth.ensure_on(FakeBt(), lambda n: None)[1]
    bt = FakeBt(present=False)
    ok, text = bluetooth.ensure_on(lambda cmd, **kw: bt(cmd, **kw) if cmd[0] == "bluetoothctl" else R("", 1), which_all)
    assert not ok and "No Bluetooth adapter" in text


def test_pairing_steps_are_generic_plain_english():
    text = " ".join(bluetooth.PAIRING_STEPS)
    assert "pairing mode" in text and "Xbox-style" in text and "PlayStation-style" in text and "Bluetooth sign" in text


# ------------------------------------------------------------------ batteries
def make_sys(tmp_path, pad_bus="0005", with_batt=True, cap="12", status="Discharging", level=""):
    sysr = tmp_path / "sys"
    hid = sysr / "devices/virtual/hid" / f"{pad_bus}:054C:09CC.0003"
    inp = hid / "input/input25"
    inp.mkdir(parents=True)
    (sysr / "class/input/js0").mkdir(parents=True)
    os.symlink(inp, sysr / "class/input/js0/device")
    ps = sysr / "class/power_supply"
    ps.mkdir(parents=True)
    laptop = ps / "BAT0"
    laptop.mkdir()
    (laptop / "capacity").write_text("88\n")
    (laptop / "scope").write_text("System\n")
    if with_batt:
        b = ps / "sony_controller_battery_aa:bb"
        b.mkdir()
        if cap is not None:
            (b / "capacity").write_text(cap + "\n")
        (b / "status").write_text(status + "\n")
        (b / "scope").write_text("Device\n")
        if level:
            (b / "capacity_level").write_text(level + "\n")
        os.symlink(hid, b / "device")
    return str(sysr)


def pad(bus=5):
    return pads.Pad("Wireless Controller", bus, 0x054C, 0x09CC, 0x8100, "js0", "event6")


def test_battery_is_matched_to_the_pad_and_the_laptop_battery_is_ignored(tmp_path):
    rows = padbattery.for_pads([pad()], make_sys(tmp_path))
    assert rows == [{"name": "Wireless Controller", "text": "12%", "low": True, "charging": False, "percent": 12, "known": True}]


def test_charging_full_and_level_only(tmp_path):
    assert padbattery.for_pads([pad()], make_sys(tmp_path / "a", cap="40", status="Charging"))[0]["text"] == "Charging 40%"
    assert padbattery.for_pads([pad()], make_sys(tmp_path / "b", cap="100", status="Full"))[0]["text"] == "Full"
    r = padbattery.for_pads([pad()], make_sys(tmp_path / "c", cap=None, level="Low"))[0]
    assert r["text"] == "Battery low" and r["low"]
    assert padbattery.describe(16, "Discharging")[1] is False and padbattery.describe(15, "Discharging")[1] is True


def test_no_report_wireless_pad_is_unknown_wired_pad_is_hidden(tmp_path):
    s = make_sys(tmp_path / "a", with_batt=False)
    assert padbattery.for_pads([pad(5)], s)[0]["text"] == "Battery unknown"
    assert padbattery.for_pads([pad(3)], make_sys(tmp_path / "b", pad_bus="0003", with_batt=False)) == []


def test_upower_is_the_second_source(tmp_path):
    dump = ("Device: /org/freedesktop/UPower/devices/battery_BAT0\n  native-path: BAT0\n  battery\n    percentage: 90%\n\n"
            "Device: /org/freedesktop/UPower/devices/gaming_input_x\n  model:  Wireless Controller\n  gaming-input\n"
            "    state:  discharging\n    percentage:  55%\n")
    up = padbattery.upower_batteries(which_all, lambda cmd, **kw: R(dump))
    assert up == {"Wireless Controller": (55, "discharging")}
    rows = padbattery.for_pads([pad()], make_sys(tmp_path, with_batt=False), upower=up)
    assert rows[0]["text"] == "55%" and not rows[0]["low"]
    assert padbattery.upower_batteries(lambda n: None) == {}


# ------------------------------------------------------------------ Screen to TV
XRANDR = """Screen 0: minimum 320 x 200, current 1920 x 1080, maximum 16384 x 16384
eDP-1 connected primary 1920x1080+0+0 (normal left inverted right x axis y axis) 344mm x 194mm
   1920x1080     60.02*+
HDMI-1 connected (normal left inverted right x axis y axis)
   3840x2160     60.00 +  30.00
DP-1 disconnected (normal left inverted right x axis y axis)
"""


def test_xrandr_screens_and_commands():
    outs = screentv.parse_xrandr(XRANDR)
    assert [(o.name, o.connected, o.internal, o.active) for o in outs] == [("eDP-1", True, True, True), ("HDMI-1", True, False, False),
                                                                           ("DP-1", False, False, False)]
    inner, tv = screentv.pick(outs)
    assert inner.name == "eDP-1" and tv.name == "HDMI-1" and tv.kind == "HDMI"
    assert screentv.commands("mirror", inner, tv) == ["xrandr", "--output", "HDMI-1", "--auto", "--same-as", "eDP-1", "--output", "eDP-1", "--auto", "--primary"]
    assert screentv.commands("tv", inner, tv) == ["xrandr", "--output", "HDMI-1", "--auto", "--primary", "--output", "eDP-1", "--off"]
    assert screentv.commands("here", inner, tv)[-2:] == ["HDMI-1", "--off"]
    assert screentv.undo_command(outs) == ["xrandr", "--output", "eDP-1", "--auto", "--output", "HDMI-1", "--off"]
    assert screentv.commands("tv", inner, None) is None


def test_kernel_list_of_screens(tmp_path):
    drm = tmp_path / "class/drm"
    for n, st in (("card1-eDP-1", "connected"), ("card1-HDMI-A-1", "connected"), ("card1-DP-2", "disconnected"), ("card1", None)):
        (drm / n).mkdir(parents=True)
        if st:
            (drm / n / "status").write_text(st + "\n")
    outs = screentv.kernel_outputs(str(tmp_path))
    assert [(o.name, o.connected, o.internal) for o in outs] == [("DP-2", False, False), ("HDMI-A-1", True, False), ("eDP-1", True, True)]


def test_no_xrandr_on_wayland(monkeypatch):
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    assert screentv.xrandr_outputs(lambda *a, **k: R(XRANDR), which_all) is None


def test_wireless_app(tmp_path):
    assert screentv.wireless_app(lambda n: "/x" if n == "gnome-network-displays" else None) == ["gnome-network-displays"]
    (tmp_path / ".local/share/flatpak/app" / screentv.ND_FLATPAK).mkdir(parents=True)
    assert screentv.wireless_app(lambda n: "/x" if n == "flatpak" else None, tmp_path) == ["flatpak", "run", screentv.ND_FLATPAK]


# ------------------------------------------------------------------ in CodeAque
def texts(rows):
    return " | ".join(r["title"] + " " + r.get("detail", "") for r in rows)


def wait(app, cond, secs=5):
    t = time.time()
    while time.time() - t < secs:
        pump(app, 30)
        if cond():
            return True
    return False


def test_pair_page_search_and_pair(app, tmp_path, monkeypatch):
    bt = FakeBt()
    monkeypatch.setattr(bluetooth, "_run", lambda args, runner=None, timeout=20.0: (lambda p: (p.returncode, p.stdout))(bt(["bluetoothctl", *args])))
    monkeypatch.setattr(bluetooth, "available", lambda which=None: True)
    monkeypatch.setattr(bluetooth, "SCAN_SECONDS", 1)
    ui = make_ui(app, tmp_path, monkeypatch, tmp_path / "home")
    try:
        b = ui.backend
        assert b.pageActivate("controllers", "ctbt") == "page:btpair"
        assert b.pageTitle("btpair") == "PAIR A BLUETOOTH CONTROLLER"
        rows = b.pageRows("btpair")
        assert "pairing mode" in texts(rows) and "btscan" in [r.get("id") for r in rows]
        b.pageActivate("btpair", "btscan")
        assert wait(app, lambda: not b._bt_busy)
        rows = b.pageRows("btpair")
        assert "Found 1 controller" in texts(rows)
        ids = [r.get("id") for r in rows]
        assert ids.index("btdev:AA:BB:CC:DD:EE:01") < ids.index("btdev:AA:BB:CC:DD:EE:02")
        b.pageActivate("btpair", "btdev:AA:BB:CC:DD:EE:01")
        assert wait(app, lambda: not b._bt_busy)
        t = texts(b.pageRows("btpair"))
        assert "Connected. Press a button" in t and "Battery 75%" in t and "Forget Wireless Controller" in t
        b.pageActivate("btpair", "btforget:AA:BB:CC:DD:EE:01")
        assert wait(app, lambda: not b._bt_busy) and "Removed" in texts(b.pageRows("btpair"))
    finally:
        ui.close()


def items(win, name):
    out, todo = [], [win.contentItem()]
    while todo:
        it = todo.pop()
        if it.objectName() == name and it.isVisible():
            out.append(it)
        todo += it.childItems()
    return out


def test_battery_pills_in_the_top_bar_and_low_warning(app, tmp_path, monkeypatch):
    ui = make_ui(app, tmp_path, monkeypatch, tmp_path / "home")
    try:
        b = ui.backend
        toasts = []
        monkeypatch.setattr(b, "show_toast", lambda t, ms=5000: toasts.append(t))
        b.set_pad_batteries([{"name": "Wireless Controller", "text": "12%", "low": True, "charging": False, "percent": 12, "known": True},
                             {"name": "Pro Controller", "text": "Charging 40%", "low": False, "charging": True, "percent": 40, "known": True}])
        pump(app, 150)
        pills = items(ui.win, "padBattery")
        assert sorted(p.property("label") for p in pills) == ["12%", "Charging 40%"]
        assert len(toasts) == 1 and "battery low" in toasts[0] and "Wireless Controller" in toasts[0]
        b.set_pad_batteries(list(b.padBatteries))                    # still low: no second warning
        assert len(toasts) == 1
        b.set_pad_batteries([])
        pump(app, 100)
        assert not items(ui.win, "padBattery")
    finally:
        ui.close()


def test_real_battery_read_runs_in_the_background(app, tmp_path, monkeypatch):
    s = make_sys(tmp_path, cap="70")
    monkeypatch.setattr(pads, "detect", lambda path=None: [pad()])
    orig = padbattery.for_pads
    monkeypatch.setattr(padbattery, "for_pads", lambda found, sys_root="/sys", upower=None, bluez=None: orig(found, s, upower, bluez))
    monkeypatch.setattr(padbattery, "upower_batteries", lambda *a, **k: {})
    ui = make_ui(app, tmp_path, monkeypatch, tmp_path / "home")
    try:
        b = ui.backend
        b.refreshBatteries()
        assert wait(app, lambda: b.padBatteries and b.padBatteries[0]["text"] == "70%")
        assert "Battery:  Wireless Controller  -  70%" in texts(b.pageRows("controllers"))
    finally:
        ui.close()


def test_screen_to_tv_page_switches_and_undoes_itself(app, tmp_path, monkeypatch):
    ran = []
    monkeypatch.setattr(screentv, "xrandr_outputs", lambda runner=None, which=None: screentv.parse_xrandr(XRANDR))
    monkeypatch.setattr(screentv, "run", lambda cmd, runner=None: (ran.append(cmd) or True, ""))
    monkeypatch.setattr(screentv, "REVERT_SECONDS", 1)
    monkeypatch.setattr(screentv, "wireless_app", lambda which=None, home=None: None)
    ui = make_ui(app, tmp_path, monkeypatch, tmp_path / "home")
    try:
        b = ui.backend
        assert any(r.get("kind") == "screentvpage" for r in b.setupRows())
        rows = b.pageRows("screentv")
        t = texts(rows)
        assert "HDMI cable" in t and "Chromecast" in t and "flatpak install flathub org.gnome.NetworkDisplays" in t and "HDMI-1 (HDMI)" in t
        b.pageActivate("screentv", "tvonly")
        assert ran[-1][-2:] == ["eDP-1", "--off"]
        assert "Keep this" in texts(b.pageRows("screentv"))
        assert wait(app, lambda: len(ran) == 2, 4)                                        # nobody pressed Keep: put back
        assert ran[-1] == ["xrandr", "--output", "eDP-1", "--auto", "--output", "HDMI-1", "--off"]
        assert "put back" in texts(b.pageRows("screentv"))
        b.pageActivate("screentv", "tvmirror")
        b.pageActivate("screentv", "tvkeep")
        pump(app, 1500)
        assert len(ran) == 3 and "Kept" in texts(b.pageRows("screentv"))
    finally:
        ui.close()


def test_screen_to_tv_without_x11_explains(app, tmp_path, monkeypatch):
    monkeypatch.setattr(screentv, "xrandr_outputs", lambda runner=None, which=None: None)
    ui = make_ui(app, tmp_path, monkeypatch, tmp_path / "home")
    try:
        t = texts(ui.backend.pageRows("screentv"))
        assert "needs an X11 session" in t and "tvonly" not in [r.get("id") for r in ui.backend.pageRows("screentv")]
    finally:
        ui.close()


def inside_window(win, it):
    p = it.mapToScene(it.boundingRect().topLeft()) if hasattr(it, "mapToScene") else None
    from PySide6.QtCore import QPointF
    p = it.mapToItem(win.contentItem(), QPointF(0, 0))
    return 0 <= p.x() and p.x() + it.width() <= win.width() + 1 and 0 <= p.y() <= win.height()


def test_no_pad_pill_shows_on_home_and_opens_pairing(app, tmp_path, monkeypatch):
    ui = make_ui(app, tmp_path, monkeypatch, tmp_path / "home")
    try:
        b = ui.backend
        b.set_pad_batteries([])
        pump(app, 150)
        pill = items(ui.win, "noPadPill")
        assert len(pill) == 1 and inside_window(ui.win, pill[0])
        asked = []
        b.pageRequested.connect(asked.append)
        b.openControllerPill()
        assert asked == ["btpair"]
        b.set_pad_batteries([{"name": "Pad", "text": "80%", "low": False, "charging": False, "percent": 80, "known": True}])
        pump(app, 150)
        assert not items(ui.win, "noPadPill") and all(inside_window(ui.win, p) for p in items(ui.win, "padBattery"))
        b.openControllerPill()
        assert asked[-1] == "controllers"
        assert all(inside_window(ui.win, p) for p in items(ui.win, "brightnessPill"))
    finally:
        ui.close()


def test_bluez_battery_used_when_kernel_and_upower_say_nothing(tmp_path):
    (tmp_path / "class" / "power_supply").mkdir(parents=True)
    bt = pads.Pad("Xbox Wireless Controller", 5, 0x045E, 0x0B13, 0x0500, "js0", "event6")
    rows = padbattery.for_pads([bt], str(tmp_path), upower={}, bluez={"Xbox Wireless Controller": 64})
    assert rows[0]["text"].endswith("64%") and rows[0]["known"]
    # fuzzy name match with UPower
    rows = padbattery.for_pads([bt], str(tmp_path), upower={"Microsoft Xbox Wireless Controller": (30, "discharging")})
    assert "30%" in rows[0]["text"]
    # a BlueZ-connected pad the kernel list missed still gets a pill
    rows = padbattery.for_pads([], str(tmp_path), bluez={"DualSense Wireless Controller": 12})
    assert rows and rows[0]["low"] and rows[0]["name"].startswith("DualSense")
