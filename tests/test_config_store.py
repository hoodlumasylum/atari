from atarilauncher import config, store


def test_defaults_have_all_main_systems():
    cfg = config.default_config()
    for sid in ("nes", "snes", "genesis", "atari2600", "atari7800", "gba", "n64", "ps1"):
        assert sid in cfg.systems
        assert "{rom}" in cfg.systems[sid].command and cfg.systems[sid].core.endswith("_libretro")


def test_missing_file_means_first_run(tmp_path):
    cfg = config.load_config(tmp_path / "config.toml")
    assert cfg.first_run and cfg.steam_enabled


def test_roundtrip(tmp_path):
    p = tmp_path / "c" / "config.toml"
    cfg = config.default_config()
    cfg.fullscreen = False
    cfg.steam_extra_libraries = ["/mnt/x y/Lib"]
    cfg.systems["nes"].roms = ["/home/me/ROMs/nes", '/weird "quoted" path']
    cfg.systems["gba"].command = "mgba-qt -f {rom}"
    config.save_config(cfg, p)
    back = config.load_config(p)
    assert not back.first_run and not back.fullscreen
    assert back.steam_extra_libraries == ["/mnt/x y/Lib"]
    assert back.systems["nes"].roms == ["/home/me/ROMs/nes", '/weird "quoted" path']
    assert back.systems["gba"].command == "mgba-qt -f {rom}"
    assert back.systems["snes"].core == "snes9x_libretro"


def test_user_can_add_custom_system(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[systems.dreamcast]\nname = "Dreamcast"\nroms = ["~/dc"]\nextensions = [".CDI", "gdi"]\n'
                 'command = "flycast {rom}"\n')
    cfg = config.load_config(p)
    dc = cfg.systems["dreamcast"]
    assert dc.extensions == ["cdi", "gdi"] and dc.command == "flycast {rom}"
    assert "nes" in cfg.systems  # defaults still there
    assert "[systems.dreamcast]" in config.dump_config(cfg)


def test_broken_toml_falls_back_to_defaults(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("this is [not valid toml")
    cfg = config.load_config(p)
    assert "nes" in cfg.systems


def test_store_favorites_playtime_recent(tmp_path):
    p = tmp_path / "s" / "state.json"
    s = store.Store(p)
    assert not s.is_favorite("a")
    assert s.toggle_favorite("a") is True and s.toggle_favorite("a") is False
    s.mark_launched("a", 100)
    s.mark_launched("b", 200)
    s.mark_launched("a", 300)
    s.add_playtime("a", 125)
    s.add_playtime("a", 60)
    s.add_playtime("a", -5)
    assert s.recent_ids() == ["a", "b"]
    again = store.Store(p)  # persisted
    assert again.playtime("a") == 185 and again.get("a")["launches"] == 2


def test_store_survives_corrupt_file(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{nope")
    assert store.Store(p).games == {}


def test_formatting():
    assert store.format_playtime(0) == "Not played yet"
    assert store.format_playtime(30) == "Under a minute"
    assert store.format_playtime(45 * 60) == "45 min"
    assert store.format_playtime(3600 * 5 + 40 * 60) == "5 h 40 min"
    assert store.format_last_played(0) == "Never"
    assert store.format_last_played(1000, now=1000 + 3600) == "Today"
    assert store.format_last_played(1000, now=1000 + 86400 * 3) == "3 days ago"
