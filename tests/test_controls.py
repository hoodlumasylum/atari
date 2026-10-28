from atarilauncher import controls, launcher
from atarilauncher.config import default_config


def test_flycast_mapping_text_has_the_expected_format():
    t = controls.flycast_mapping_text()
    assert t.startswith("[digital]") and "[emulator]" in t and "version = 4" in t
    assert "bind0 = 82:btn_dpad1_up" in t      # SDL scancode 82 = Up arrow
    assert "29:btn_a" in t and "40:btn_start" in t and "20:btn_trigger_left" in t


def test_flycast_keyboard_written_once_and_never_overwritten(tmp_path):
    p = controls.ensure_flycast_keyboard("native", tmp_path)
    assert p and p.parent == tmp_path / ".config/flycast/mappings" and p.read_text().startswith("[")
    p.write_text("# my own keys\n")
    assert controls.ensure_flycast_keyboard("native", tmp_path) is None
    assert p.read_text() == "# my own keys\n"


def test_flycast_flatpak_path_and_existing_instance_file_respected(tmp_path):
    d = tmp_path / ".var/app/org.flycast.Flycast/config/flycast/mappings"
    d.mkdir(parents=True)
    (d / "SDL_Keyboard-sdl_keyboard.cfg").write_text("# made by Flycast\n")
    assert controls.ensure_keyboard_defaults("flycast", "flatpak", tmp_path) == []
    assert [x.name for x in d.iterdir()] == ["SDL_Keyboard-sdl_keyboard.cfg"]
    assert controls.ensure_keyboard_defaults("flycast", "flatpak", tmp_path / "other")
    assert controls.ensure_keyboard_defaults("pcsx2", "native", tmp_path) == []      # others: nothing written


def test_cheat_sheet_and_hint():
    rows = controls.cheat_rows()
    kinds = [r["kind"] for r in rows]
    assert kinds[-1] == "back" and "ctl" in kinds
    assert any("Flycast" in r["title"] and "Z" in r["detail"] for r in rows)
    assert controls.hint_for("flycast").startswith("Flycast keys")
    assert controls.hint_for("nonexistent") == ""
    cfg = default_config()
    from atarilauncher.library import Game
    assert launcher.controls_hint(cfg, Game("steam:1", "x", "steam", "Steam")) == ""
