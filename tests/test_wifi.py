"""WiFi through a MOCKED nmcli: parsing, scan, connect (incl. wrong password / hidden / saved), forget, no-adapter messages,
and the whole screen: reachable from Settings and the home screen, on-screen keyboard with controller + keyboard keys."""
import pytest

from atarilauncher import wifi

pytest.importorskip("PySide6")
from PySide6.QtCore import Q_ARG, QMetaObject, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from atarilauncher import backend as be  # noqa: E402
from tests.test_features_ui import conf  # noqa: E402
from tests.test_studio_click import click_text, texts  # noqa: E402
from tests.test_ui_keys import Ui, app, pump  # noqa: E402,F401


class FakeNm:
    """A pretend nmcli. `calls` records every command line."""

    def __init__(self, devices="wlan0:wifi:connected\neth0:ethernet:unavailable", radio="enabled", scan=None, saved=None,
                 connect_rc=0, connect_err="", up_rc=0):
        self.devices = devices
        self.radio = radio
        self.scan_out = scan if scan is not None else (
            " :Cafe Guest:42:--\n"
            "*:HomeNet:81:WPA2\n"
            " :HomeNet:55:WPA2\n"                      # weaker duplicate of the same name
            " :Neighbour\\:5G:30:WPA2 WPA3\n"          # an escaped colon in the name
            " ::60:WPA2\n")                            # a hidden network has no name
        self.saved = list(saved if saved is not None else ["HomeNet"])
        self.connect_rc, self.connect_err, self.up_rc = connect_rc, connect_err, up_rc
        self.calls: list = []
        self.rescan_fail = False

    def __call__(self, args, timeout=20):
        self.calls.append(list(args))
        a = list(args)
        if a[:3] == ["-t", "-f", "DEVICE,TYPE,STATE"]:
            return 0, self.devices + "\n", ""
        if a[:3] == ["-t", "-f", "DEVICE,TYPE,STATE,CONNECTION"]:
            out = ""
            if "wlan0:wifi:connected" in self.devices:
                out += "wlan0:wifi:connected:HomeNet\n"
            elif "wlan0" in self.devices:
                out += "wlan0:wifi:disconnected:\n"
            out += "eth0:ethernet:connected:Wired connection 1\n" if "eth0:ethernet:connected" in self.devices else "eth0:ethernet:unavailable:\n"
            return 0, out, ""
        if a[:2] == ["radio", "wifi"] and len(a) == 2:
            return 0, self.radio + "\n", ""
        if a[:3] == ["radio", "wifi", "on"]:
            self.radio = "enabled"
            return 0, "", ""
        if a[:3] == ["-t", "-f", "NAME,TYPE"]:
            return 0, "".join(f"{n}:802-11-wireless\n" for n in self.saved) + "Wired connection 1:802-3-ethernet\n", ""
        if "list" in a and "wifi" in a:
            if self.rescan_fail and "yes" in a:
                return 1, "", "Error: Scanning not allowed immediately following previous scan."
            return 0, self.scan_out, ""
        if "connect" in a and "wifi" in a:
            if self.connect_rc == 0:
                self.saved.append(a[a.index("connect") + 1])
            return self.connect_rc, "", self.connect_err
        if a[-3:-1] == ["up", "id"] or ("up" in a and "id" in a and "connection" in a):
            return self.up_rc, "", ""
        if a[:2] == ["connection", "delete"]:
            n = a[-1]
            if n in self.saved:
                self.saved.remove(n)
                return 0, "", ""
            return 10, "", "Error: unknown connection"
        return 0, "", ""


def test_terse_fields_unescape_colons_and_backslashes():
    assert wifi.split_terse("*:My\\:Net:77:WPA2") == ["*", "My:Net", "77", "WPA2"]
    assert wifi.split_terse("a\\\\b::") == ["a\\b", "", ""]


def test_scan_lists_one_row_per_name_strongest_first_connected_on_top_hidden_skipped():
    nets, err = wifi.scan(FakeNm())
    assert err == ""
    assert [n.ssid for n in nets] == ["HomeNet", "Cafe Guest", "Neighbour:5G"]
    home = nets[0]
    assert home.in_use and home.known and home.signal == 81 and home.secure and home.bars == 4
    cafe = nets[1]
    assert not cafe.secure and not cafe.known and cafe.bars == 2 and cafe.as_dict()["security"] == "Open"


def test_scan_falls_back_to_the_last_result_when_nmcli_refuses_a_fresh_scan():
    fake = FakeNm()
    fake.rescan_fail = True
    nets, err = wifi.scan(fake)
    assert nets and err == ""
    assert any("no" in c and "list" in c for c in fake.calls)


def test_adapter_states_have_plain_english_text():
    assert wifi.adapter(FakeNm()).usable
    none = wifi.adapter(FakeNm(devices="eth0:ethernet:connected"))
    assert none.state == "noadapter" and "No WiFi adapter" in none.text
    off = wifi.adapter(FakeNm(radio="disabled"))
    assert off.state == "radio_off" and "switched off" in off.text
    assert wifi.adapter(lambda a, t=0: (127, "", "")).state == "nonmcli"
    assert wifi.adapter(lambda a, t=0: (8, "", "NetworkManager is not running.")).state == "nm_off"


def test_status_and_home_screen_summary():
    assert wifi.status(FakeNm()).text == "Connected to HomeNet"
    cable = FakeNm(devices="wlan0:wifi:disconnected\neth0:ethernet:connected")
    assert wifi.status(cable).wired and wifi.status(cable).text == "Connected by cable"
    assert wifi.summary(FakeNm()) == "HomeNet"
    assert wifi.summary(cable) == "Cable"
    assert wifi.summary(FakeNm(devices="eth0:ethernet:unavailable")) == "No WiFi"
    assert wifi.summary(FakeNm(devices="wlan0:wifi:disconnected")) == "Offline"
    assert wifi.summary(FakeNm(radio="disabled", devices="wlan0:wifi:unavailable")) == "WiFi off"


def test_connect_new_secured_network_saves_it_with_the_password():
    fake = FakeNm(saved=[])
    ok, text = wifi.connect("Cafe Guest", "hunter2 !", False, fake)
    assert ok and "Connected to Cafe Guest" in text
    cmd = next(c for c in fake.calls if "connect" in c)
    assert cmd[:5] == ["--wait", "30", "device", "wifi", "connect"] and cmd[5] == "Cafe Guest"
    assert cmd[cmd.index("password") + 1] == "hunter2 !" and "hidden" not in cmd


def test_wrong_password_says_so_and_does_not_keep_the_half_made_profile():
    fake = FakeNm(saved=[], connect_rc=4, connect_err="Error: Connection activation failed: (7) Secrets were required, but not provided.")
    ok, text = wifi.connect("Cafe Guest", "nope", False, fake)
    assert not ok and "password was not accepted" in text
    assert ["connection", "delete", "id", "Cafe Guest"] in fake.calls


def test_saved_network_is_brought_up_without_asking_for_a_password():
    fake = FakeNm()
    ok, _ = wifi.connect("HomeNet", "", False, fake)
    assert ok and any(c[-3:] == ["connection", "up", "id", "HomeNet"][-3:] and "connection" in c for c in fake.calls)
    assert not any("device" in c and "connect" in c for c in fake.calls)


def test_hidden_network_adds_the_hidden_flag_and_out_of_range_is_explained():
    fake = FakeNm(saved=[])
    wifi.connect("Secret", "pw12345678", True, fake)
    cmd = next(c for c in fake.calls if "connect" in c)
    assert cmd[-2:] == ["hidden", "yes"]
    far = FakeNm(saved=[], connect_rc=10, connect_err="Error: No network with SSID 'x' found.")
    assert "not in range" in wifi.connect("x", "", False, far)[1]
    assert "Type the network name" in wifi.connect("  ", "", False, far)[1]


def test_permission_and_timeout_errors_are_plain_english():
    assert "not allowed" in wifi.friendly_error("Error: Insufficient privileges.")
    assert "did not answer" in wifi.friendly_error("Error: Timeout expired (30 seconds)")
    assert wifi.friendly_error("") == ""


def test_forget_deletes_the_profile_and_radio_on_works():
    fake = FakeNm()
    ok, text = wifi.forget("HomeNet", fake)
    assert ok and "Forgot HomeNet" in text and "HomeNet" not in fake.saved
    assert not wifi.forget("HomeNet", fake)[0]
    off = FakeNm(radio="disabled")
    assert wifi.radio_on(off)[0] and off.radio == "enabled"


# ------------------------------------------------------------------ the screen
def make(app, tmp_path, monkeypatch, fake):
    conf(tmp_path, "[steam]\nenabled = false\n")
    monkeypatch.delenv("ATARI_NO_WIFI", raising=False)
    monkeypatch.setattr(be.Backend, "_wifi_run", staticmethod(fake), raising=False)
    monkeypatch.setattr(be.Backend, "_wifi_poll", lambda self: self.wifi.updateSummary(), raising=True)
    return Ui(app, tmp_path, monkeypatch, config_exists=False)


def wait_until(app, cond, ms=3000):
    import time
    end = time.time() + ms / 1000
    while time.time() < end:
        pump(app, 30)
        if cond():
            return True
    return False


def say(ui):
    return " | ".join(t for t, _ in texts(ui))


def pad(ui, action, ms=60):
    """A controller button: CodeAque turns it into a key press WITHOUT text (unlike a real keyboard's key)."""
    ui.backend.send_action(action)
    pump(ui.app, ms)


def typing(ui, s):
    for ch in s:
        QTest.keyClick(ui.win, ch)
    pump(ui.app, 80)


def open_wifi(ui):
    """Open the screen the way a person does: press the WiFi button next to the clock."""
    assert wait_until(ui.app, lambda: ui.backend.wifi.summary != "")                  # the button shows the name once nmcli answered
    click_text(ui, ui.backend.wifi.summary)
    assert ui.mode == "wifi"


def test_home_screen_shows_the_network_and_opens_the_wifi_screen(app, tmp_path, monkeypatch):
    ui = make(app, tmp_path, monkeypatch, FakeNm())
    try:
        assert wait_until(app, lambda: ui.backend.wifi.summary == "HomeNet")
        assert "HomeNet" in say(ui)                                                    # the name beside the clock
        open_wifi(ui)
        assert wait_until(app, lambda: ui.backend.wifi.state == "ready")
        assert ui.mode == "wifi"
        shown = say(ui)
        assert "HomeNet" in shown and "Cafe Guest" in shown and "Neighbour:5G" in shown and "Connected" in shown
        assert "Join a hidden network" in shown
        ui.key(Qt.Key_Escape)
        assert ui.mode == "library"
    finally:
        ui.close()


def test_settings_has_a_wifi_row_that_opens_it_and_returns_to_settings(app, tmp_path, monkeypatch):
    ui = make(app, tmp_path, monkeypatch, FakeNm())
    try:
        rows = {r["kind"]: r for r in ui.backend.setupRows()}
        assert "wifipage" in rows and rows["wifipage"]["title"] == "WiFi"
        QMetaObject.invokeMethod(ui.win, "openSetup")
        pump(app, 200)
        idx = [r["kind"] for r in ui.backend.setupRows()].index("wifipage")
        QMetaObject.invokeMethod(ui.win, "setupActivate", Qt.DirectConnection, Q_ARG("QVariant", idx))
        assert wait_until(app, lambda: ui.mode == "wifi")
        ui.key(Qt.Key_Escape)
        assert ui.mode == "setup"
    finally:
        ui.close()


def test_controller_flow_choose_network_type_password_with_the_pad_and_connect(app, tmp_path, monkeypatch):
    monkeypatch.setenv("ATARI_TEST_INPUT", "1")
    fake = FakeNm(saved=[])
    ui = make(app, tmp_path, monkeypatch, fake)
    try:
        open_wifi(ui)
        assert wait_until(app, lambda: ui.backend.wifi.state == "ready")
        assert [n["ssid"] for n in ui.backend.wifi.networks][0] == "HomeNet"
        pad(ui, "down")
        pad(ui, "down")                                          # Neighbour:5G is secured -> A asks for the password
        pad(ui, "accept")
        assert "PASSWORD FOR Neighbour:5G" in say(ui)
        pad(ui, "accept")                                        # A on "1"
        pad(ui, "right")
        pad(ui, "accept")                                        # A on "2"
        pad(ui, "prev")                                          # L1 = delete
        field = [t for t, _ in texts(ui) if t.endswith("\u258c")][0]
        assert field == "\u2022\u258c"                           # one masked character left
        for _ in range(4):
            pad(ui, "down")                                      # to the action row
        for _ in range(5):
            pad(ui, "right")                                     # CONNECT
        pad(ui, "accept")
        assert wait_until(app, lambda: any("connect" in c and "wifi" in c for c in fake.calls))
        cmd = next(c for c in fake.calls if "connect" in c and "wifi" in c)
        assert cmd[5] == "Neighbour:5G" and cmd[cmd.index("password") + 1] == "1"
        assert wait_until(app, lambda: ui.backend.wifi.state == "ready")
        assert "Connected to Neighbour:5G" in ui.backend.wifi.message
        pad(ui, "back")
        assert ui.mode == "library"
    finally:
        ui.close()


def test_controller_can_switch_key_sets_show_the_password_and_go_back(app, tmp_path, monkeypatch):
    monkeypatch.setenv("ATARI_TEST_INPUT", "1")
    ui = make(app, tmp_path, monkeypatch, FakeNm(saved=[]))
    try:
        open_wifi(ui)
        assert wait_until(app, lambda: ui.backend.wifi.state == "ready")
        pad(ui, "down")
        pad(ui, "down")
        pad(ui, "accept")
        pad(ui, "down")                                          # row 2: qwertyuiop
        pad(ui, "next")                                          # R1: ABC
        pad(ui, "accept")
        pad(ui, "next")                                          # R1: symbols
        pad(ui, "up")
        pad(ui, "up")
        pad(ui, "accept")                                        # "!" (row 0, col 0) on the symbol set
        pad(ui, "search")                                        # "/" = show / hide
        field = [t for t, _ in texts(ui) if t.endswith("\u258c")][0]
        assert field == "Q!\u258c"
        pad(ui, "back")                                          # B = back to the list, nothing typed is kept
        assert ui.mode == "wifi" and "Join a hidden network" in say(ui)
    finally:
        ui.close()


def test_keyboard_typing_enter_connects_and_failure_shows_a_red_message(app, tmp_path, monkeypatch):
    fake = FakeNm(saved=[], connect_rc=4, connect_err="Error: Connection activation failed: (7) Secrets were required")
    ui = make(app, tmp_path, monkeypatch, fake)
    try:
        open_wifi(ui)
        assert wait_until(app, lambda: ui.backend.wifi.state == "ready")
        ui.key(Qt.Key_Down)
        ui.key(Qt.Key_Down)
        ui.key(Qt.Key_Return)                                    # password page for Neighbour:5G
        typing(ui, "Pass word1")                                  # a real keyboard: text events, capitals and a space
        ui.key(Qt.Key_Backspace)
        QTest.keyClick(ui.win, Qt.Key_Return)                    # a real Enter has text -> connect
        assert wait_until(app, lambda: any("connect" in c and "wifi" in c for c in fake.calls))
        cmd = next(c for c in fake.calls if "connect" in c and "wifi" in c)
        assert cmd[cmd.index("password") + 1] == "Pass word"
        assert wait_until(app, lambda: ui.backend.wifi.state == "ready" and not ui.backend.wifi.messageOk)
        assert "password was not accepted" in ui.backend.wifi.message
        assert ui.mode == "wifi" and "password was not accepted" in say(ui)
    finally:
        ui.close()


def test_forget_needs_a_second_press_and_removes_the_saved_network(app, tmp_path, monkeypatch):
    fake = FakeNm()
    ui = make(app, tmp_path, monkeypatch, fake)
    try:
        open_wifi(ui)
        assert wait_until(app, lambda: ui.backend.wifi.state == "ready")
        ui.key(Qt.Key_F)
        assert "HomeNet" in fake.saved and "Press again to forget" in say(ui)
        ui.key(Qt.Key_F)
        assert wait_until(app, lambda: "HomeNet" not in fake.saved)
        assert wait_until(app, lambda: "Forgot HomeNet" in ui.backend.wifi.message)
    finally:
        ui.close()


def test_hidden_network_asks_for_the_name_then_the_password(app, tmp_path, monkeypatch):
    fake = FakeNm(saved=[])
    ui = make(app, tmp_path, monkeypatch, fake)
    try:
        open_wifi(ui)
        assert wait_until(app, lambda: ui.backend.wifi.state == "ready")
        for _ in range(3):
            ui.key(Qt.Key_Down)                                  # the last row: Join a hidden network...
        ui.key(Qt.Key_Return)
        assert "NAME OF THE HIDDEN NETWORK" in say(ui)
        typing(ui, "Garage")
        QTest.keyClick(ui.win, Qt.Key_Return)
        pump(app, 100)
        assert "PASSWORD FOR Garage" in say(ui)
        typing(ui, "secret123")
        QTest.keyClick(ui.win, Qt.Key_Return)
        assert wait_until(app, lambda: any("connect" in c and "wifi" in c for c in fake.calls))
        cmd = next(c for c in fake.calls if "connect" in c and "wifi" in c)
        assert cmd[5] == "Garage" and cmd[-2:] == ["hidden", "yes"] and "secret123" in cmd
    finally:
        ui.close()


def test_no_wifi_adapter_shows_a_clear_message_and_turn_on_works_when_the_radio_is_off(app, tmp_path, monkeypatch):
    ui = make(app, tmp_path, monkeypatch, FakeNm(devices="eth0:ethernet:connected"))
    try:
        open_wifi(ui)
        assert wait_until(app, lambda: ui.backend.wifi.state == "unavailable")
        shown = say(ui)
        assert "No WiFi adapter found" in shown and "plug in a USB WiFi stick" in shown
        ui.key(Qt.Key_Escape)
        assert ui.mode == "library"
    finally:
        ui.close()
    fake = FakeNm(radio="disabled")
    ui = make(app, tmp_path, monkeypatch, fake)
    try:
        open_wifi(ui)
        assert wait_until(app, lambda: ui.backend.wifi.state == "unavailable")
        assert "WiFi is switched off" in say(ui) and "TURN WIFI ON" in say(ui)
        ui.key(Qt.Key_Return)
        assert wait_until(app, lambda: ui.backend.wifi.state == "ready" and ui.backend.wifi.adapterState == "ok")
        assert fake.radio == "enabled"
    finally:
        ui.close()


def test_the_wifi_screen_works_in_code_only_mode_no_desktop_applet_needed():
    """CodeAque-only mode = no panel / nm-applet. Everything goes through nmcli with the password stored in the connection itself."""
    import inspect
    src = inspect.getsource(wifi)
    assert "nm-applet" not in src and "pkexec" not in src and "sudo" not in src
    assert "password" in src
