from atarilauncher import bluetooth as b


def test_agent_says_yes_only_to_known_pads():
    a = b.Agent(allowed=lambda: {"AA:BB:CC:DD:EE:01"})
    assert a.handle("[agent] Authorize service 0x1124 (AA:BB:CC:DD:EE:01) (yes/no):") == "yes"
    assert a.handle("[agent] Confirm passkey 1234 (11:22:33:44:55:66) (yes/no):") == "no"
    a.extra.add("11:22:33:44:55:66")
    assert a.handle("[agent] Confirm passkey 1234 (11:22:33:44:55:66) (yes/no):") == "yes"
    assert a.handle("[CHG] Device AA:BB:CC:DD:EE:01 Connected: yes") is None


def test_boot_status_lines_and_fix_script(tmp_path):
    st = {"enabled": False, "active": True, "helper": False, "blueman": False}
    assert not b.boot_ok(st) and "press Fix controller reconnect" in " ".join(b.boot_lines(st))
    assert b.boot_ok({"enabled": True, "active": True, "helper": True, "blueman": False})
    m, i = b.reconnect_conf("", "")
    sc = b.reconnect_script(m, i)
    assert "systemctl enable bluetooth.service" in sc and "codeaque-bluetooth-on.service" in sc and "blueman" in sc
    assert "JustWorksRepairing=always" in m
    ran = lambda a, **k: type("P", (), {"stdout": {"is-enabled": "enabled\n", "is-active": "active\n"}[a[1]]})()
    st = b.boot_status(runner=ran, which=lambda n: None, unit=str(tmp_path / "x.service"))
    assert st == {"enabled": True, "active": True, "helper": False, "blueman": False}


def test_agent_uses_last_seen_address_and_wakes_quick_connect():
    seen = []
    a = b.Agent(allowed=lambda: {"AA:BB:CC:DD:EE:01"})
    a.on_seen = seen.append
    assert a.handle("[CHG] Device AA:BB:CC:DD:EE:01 Connected: yes") is None and seen == ["AA:BB:CC:DD:EE:01"]
    assert a.handle("[agent] Authorize service 00001124-0000-1000-8000-00805f9b34fb (yes/no):") == "yes"
    a.handle("[NEW] Device 11:22:33:44:55:66 Stranger")
    assert a.handle("[agent] Authorize service 00001124-0000-1000-8000-00805f9b34fb (yes/no):") == "no"


def test_diagnostics_and_quick_connect():
    info = "Name: Wireless Controller\nPaired: yes\nBonded: yes\nTrusted: yes\nConnected: no\n"
    calls = []

    def run(args, r=None, t=20):
        calls.append(args)
        if args == ["devices"]:
            return 0, "Device AA:BB:CC:DD:EE:01 Wireless Controller\n"
        if args[0] == "info":
            return 0, info
        if args == ["show"]:
            return 0, "Controller 00:11:22:33:44:55 (public)\n\tPowered: yes\n\tPairable: yes\n"
        if args[0] == "connect":
            return 0, "Connection successful" if len([c for c in calls if c[0] == "connect"]) >= 3 else "Failed to connect"
        return 0, ""
    import atarilauncher.bluetooth as bt
    orig = bt._run
    bt._run = run
    try:
        lines = bt.diagnostics("AA:BB:CC:DD:EE:01", journal=lambda: "l1 hid\nl2 input\n", modules={"bluetooth", "hidp"})
        t = "\n".join(lines)
        assert "trusted yes, bonded yes, connected NO" in t and "Powered: yes" in t and "uhid NO" in t and "  l2 input" in t
        assert bt.quick_connect("AA:BB:CC:DD:EE:01", 10, sleep=lambda s: None)
    finally:
        bt._run = orig


def test_link_key_check_script(tmp_path):
    import subprocess
    d = tmp_path / "00:11:22:33:44:55" / "AA:BB:CC:DD:EE:01"
    d.mkdir(parents=True)
    (d / "info").write_text("[General]\nName=x\n\n[LinkKey]\nKey=ABCDEF\nType=4\n")
    out = subprocess.run(["sh", "-c", b.link_key_script("aa:bb:cc:dd:ee:01", str(tmp_path))], capture_output=True, text=True).stdout
    i = b.parse_link_key(out)
    assert i["saved"] and len(i["fingerprint"]) == 8 and "ABCDEF" not in out
    assert "CHANGED" in " ".join(b.link_key_lines(i, "00000000"))
    (d / "info").write_text("[General]\nName=x\n")
    out = subprocess.run(["sh", "-c", b.link_key_script("AA:BB:CC:DD:EE:01", str(tmp_path))], capture_output=True, text=True).stdout
    assert b.parse_link_key(out)["saved"] is False


def test_journal_filter_drops_audio_spam():
    log = "\n".join(["Endpoint registered: sender=:1.50 path=/MediaEndpoint/A2DPSink/sbc"] * 30 +
                     ["profiles/input/server.c:connect_event_cb() Refusing input device connect: Operation already in progress (114)",
                      "src/device.c:device_bonding_complete() status 0x00"])
    got = b.journal_filter(log, "7A:1D:8E:D4:33:D5")
    assert len(got) == 2 and "Refusing input" in got[0]


def test_agent_accepts_hid_authorize_without_address():
    a = b.Agent(allowed=lambda: {"7A:1D:8E:D4:33:D5"})
    assert a.handle("[agent] Authorize service 00001124-0000-1000-8000-00805f9b34fb (yes/no):") == "yes"
    assert b.Agent(allowed=lambda: set()).handle("[agent] Authorize service 00001124-0000 (yes/no):") == "no"


def test_mgmt_summary():
    t = "hci0:\tPrimary controller\n\taddr CC:15:31:8B:78:69 version 10\n\tcurrent settings: powered bondable ssp br/edr le secure-conn\n"
    out = b.mgmt_summary(t)
    assert "CC:15:31:8B:78:69" in out[0] and "NOT connectable" in out[1]
    assert len(b.mgmt_summary(t.replace("powered", "powered connectable"))) == 1
    assert "Restart=always" in b.BOOT_UNIT_TEXT and "btmgmt connectable on" in b.BOOT_UNIT_TEXT
