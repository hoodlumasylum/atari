from atarilauncher import inifile, picture, xemuconfig


def test_pcsx2_fill_wide_original(tmp_path):
    p = picture.files("pcsx2", "native", tmp_path)[0]
    p.parent.mkdir(parents=True)
    p.write_text("[EmuCore/GS]\nAspectRatio = Auto 4:3/3:2\nupscale_multiplier = 2\n")
    assert picture.apply("pcsx2", "fill", "native", tmp_path) == [str(p)]
    t = p.read_text()
    assert inifile.get_value(t, "EmuCore/GS", "AspectRatio") == "Stretch" and inifile.get_value(t, "EmuCore/GS", "upscale_multiplier") == "2"
    picture.apply("pcsx2", "wide", "native", tmp_path)
    t = p.read_text()
    assert inifile.get_value(t, "EmuCore/GS", "AspectRatio") == "16:9" and inifile.get_value(t, "EmuCore", "EnableWideScreenPatches") == "true"
    picture.apply("pcsx2", "original", "native", tmp_path)
    assert inifile.get_value(p.read_text(), "EmuCore/GS", "AspectRatio") == "Auto 4:3/3:2"


def test_other_emulators(tmp_path, monkeypatch):
    picture.apply("duckstation", "fill", "", tmp_path)
    t = picture.files("duckstation", "", tmp_path)[0].read_text()
    assert inifile.get_value(t, "Display", "AspectRatio") == "Stretch To Fill"
    picture.apply("dolphin", "fill", "flatpak", tmp_path)
    assert inifile.get_value(picture.files("dolphin", "flatpak", tmp_path)[0].read_text(), "Settings", "AspectRatio") == "3"
    picture.apply("ppsspp", "fill", "native", tmp_path)
    assert "DisplayStretch = True" in picture.files("ppsspp", "native", tmp_path)[0].read_text()
    picture.apply("retroarch", "fill", "native", tmp_path)
    assert 'aspect_ratio_index = "24"' in picture.files("retroarch", "native", tmp_path)[0].read_text()
    x = tmp_path / "xemu.toml"
    x.write_text("[sys.files]\nhdd_path = 'a'\n")
    monkeypatch.setattr(xemuconfig, "config_files", lambda h=None, w=None: [x])
    picture.apply("xemu", "fill", "native", tmp_path)
    t = x.read_text()
    assert "[display.ui]" in t and "fit = 'stretch'" in t.replace('"', "'") and "hdd_path" in t
