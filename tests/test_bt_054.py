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
