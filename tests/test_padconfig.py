from pathlib import Path

from atarilauncher import bluetooth, inifile, padconfig, pads

DS4 = pads.Pad("Wireless Controller", 5, 0x054C, 0x09CC, 0x8100, "js0", "event6")


def one():
    return [DS4]


def test_pcsx2_ds4_on_port1_and_keeps_other_settings(tmp_path):
    p = padconfig.paths("pcsx2", "native", tmp_path)[0]
    p.parent.mkdir(parents=True)
    p.write_text("[EmuCore]\nSpeed = 1\n\n[Pad1]\nType = DualShock2\nCross = Keyboard/Z\nCircle = SDL-1/B\n")
    files, note = padconfig.apply("pcsx2", "native", tmp_path, one)
    t = p.read_text()
    assert files == [str(p)] and "Wireless Controller" in note
    assert inifile.get_value(t, "InputSources", "SDL") == "true" and inifile.get_value(t, "EmuCore", "Speed") == "1"
    assert inifile.get_value(t, "Pad1", "Cross") == "SDL-0/A" and inifile.get_value(t, "Pad1", "LUp") == "SDL-0/-LeftY"
    assert inifile.get_value(t, "Pad1", "Circle") == "SDL-1/B"          # set by hand to another pad: kept
    assert (p.parent / "PCSX2.ini.codeaque.bak").exists()
    assert padconfig.apply("pcsx2", "native", tmp_path, one)[0] == []   # nothing changes the second time


def test_duckstation_dolphin_retroarch_xemu(tmp_path, monkeypatch):
    padconfig.apply("duckstation", "appimage", tmp_path, one)
    t = padconfig.paths("duckstation", "", tmp_path)[0].read_text()
    assert inifile.get_value(t, "Pad1", "Type") == "AnalogController" and inifile.get_value(t, "Pad1", "Start") == "SDL-0/Start"
    padconfig.apply("dolphin", "flatpak", tmp_path, one)
    d = padconfig.paths("dolphin", "flatpak", tmp_path)[0]
    assert ".var/app/org.DolphinEmu" in str(d)
    assert inifile.get_value(d.read_text(), "GCPad1", "Device") == "SDL/0/Wireless Controller"
    r = padconfig.paths("retroarch", "native", tmp_path)[0]
    r.parent.mkdir(parents=True)
    r.write_text('input_joypad_driver = "udev"\nvideo_fullscreen = "true"\n')
    padconfig.apply("retroarch", "native", tmp_path, one)
    assert 'input_joypad_driver = "sdl2"' in r.read_text() and 'video_fullscreen = "true"' in r.read_text()
    got = []
    from atarilauncher import xemuconfig
    monkeypatch.setattr(xemuconfig, "set_pad", lambda guid, home=None: (got.append(guid) or (True, ["x.toml"], "")))
    assert padconfig.apply("xemu", "native", tmp_path, one)[0] == ["x.toml"] and got == [DS4.guid]
    assert padconfig.apply("pcsx2", "native", tmp_path / "none", lambda: [])[1] == "no pad connected"
    assert "by itself" in padconfig.apply("ppsspp", "native", tmp_path, one)[1]


def test_bluetooth_reconnect_conf():
    m, i = bluetooth.reconnect_conf("[General]\nName=x\n\n[Policy]\n#AutoEnable=false\n", "[General]\n#ClassicBondedOnly=true\n")
    assert bluetooth.reconnect_ok(m, i) and "Name=x" in m
    assert not bluetooth.reconnect_ok("", "")
    s = bluetooth.reconnect_script(m, i, "/x/main.conf", "/x/input.conf", "true")
    assert "main.conf.codeaque.bak" in s and s.strip().endswith("true")


def test_trust_paired_pads(monkeypatch):
    calls = []
    monkeypatch.setattr(bluetooth, "devices", lambda runner=None: [bluetooth.Device("AA:BB:CC:DD:EE:01", "Wireless Controller", paired=True),
                                                                   bluetooth.Device("AA:BB:CC:DD:EE:02", "Wireless Controller", paired=True, trusted=True)])
    monkeypatch.setattr(bluetooth, "_run", lambda a, r=None, t=20: (calls.append(a) or 0, ""))
    assert bluetooth.trust_paired_pads() == ["Wireless Controller"] and calls == [["trust", "AA:BB:CC:DD:EE:01"]]


def test_controller_check_report():
    info = "Name: Wireless Controller\nIcon: input-gaming\nPaired: yes\nBonded: no\nTrusted: yes\nConnected: no\n"
    d = bluetooth.parse_info("AA:BB:CC:DD:EE:01", "Wireless Controller", info)
    assert d.bonded is False
    lines = bluetooth.check_report([d], "", "", dual_boot=True)
    t = " ".join(lines)
    assert "bonded NO" in t and "Forget it and pair it again" in t and "Fix controller reconnect" in t and "Windows" in t
    m, i = bluetooth.reconnect_conf("", "")
    ok = bluetooth.check_report([bluetooth.parse_info("AA:BB:CC:DD:EE:01", "Wireless Controller", info.replace("Bonded: no", "Bonded: yes"))], m, i, False)
    assert "bonded yes" in ok[0] and "press Fix controller" not in " ".join(ok) and any("FastConnectable=true" in l for l in ok)
    assert bluetooth.parse_info("AA:BB:CC:DD:EE:01", "x", "Paired: yes\n").bonded is None
