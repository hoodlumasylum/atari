from atarilauncher import roms


def test_clean_title():
    assert roms.clean_title("Super_Game (USA) [!].nes") == "Super Game"
    assert roms.clean_title("Sonic The Hedgehog (Europe) (Rev A).md") == "Sonic The Hedgehog"
    assert roms.clean_title("(weird).nes") == "(weird)"


def make(tmp_path):
    root = tmp_path / "ROMs/nes"
    (root / "sub/deeper").mkdir(parents=True)
    (root / ".hidden").mkdir()
    for f in ["a game.nes", "B_GAME.NES", "readme.txt", "sub/c (USA).nes", "sub/deeper/d.zip",
              ".hidden/e.nes", ".dot.nes", "noext"]:
        (root / f).write_bytes(b"0")
    return root


def test_scan_by_extension_recursive_case_insensitive(tmp_path):
    root = make(tmp_path)
    found = roms.scan_system([root], ["nes", "zip"], "nes")
    assert [r.title for r in found] == ["a game", "B GAME", "c", "d"]
    assert all(r.system == "nes" for r in found)


def test_extension_filter(tmp_path):
    root = make(tmp_path)
    assert [r.title for r in roms.scan_system([root], [".zip"], "x")] == ["d"]


def test_missing_and_empty_folders(tmp_path):
    assert roms.scan_system([tmp_path / "nope"], ["nes"], "nes") == []
    (tmp_path / "empty").mkdir()
    assert roms.scan_system([tmp_path / "empty"], ["nes"], "nes") == []
    assert roms.scan_system([], ["nes"], "nes") == []


def test_duplicate_folders_not_double_counted(tmp_path):
    root = make(tmp_path)
    assert len(roms.scan_system([root, root, root / "."], ["nes"], "nes")) == 3


def test_suggest_dir(tmp_path):
    assert roms.suggest_rom_dir(tmp_path, "snes") == ""
    d = tmp_path / "ROMs/SNES"
    d.mkdir(parents=True)
    assert roms.suggest_rom_dir(tmp_path, "snes") == ""  # empty folder is not suggested
    (d / "x.sfc").write_bytes(b"0")
    assert roms.suggest_rom_dir(tmp_path, "snes") == str(d)
