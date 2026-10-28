from pathlib import Path

from atarilauncher import steam, vdf
from atarilauncher.library import build_library, steam_status_text
from atarilauncher.config import default_config

from .conftest import FIX


def test_find_root_follows_symlink(fake_system):
    root = steam.find_steam_root(fake_system["home"])
    assert root == fake_system["steam"].resolve()


def test_flatpak_root_detected(tmp_path):
    root = tmp_path / ".var/app/com.valvesoftware.Steam/.local/share/Steam"
    (root / "steamapps").mkdir(parents=True)
    found = steam.find_steam_root(tmp_path)
    assert found and steam.is_flatpak_root(found)


def test_no_steam_is_not_an_error(tmp_path):
    scan = steam.scan_steam(tmp_path)
    assert not scan.found and scan.games == [] and scan.libraries == []
    assert "not found" in steam_status_text(scan)


def test_parse_libraryfolders_new_format(fake_system):
    paths = steam.parse_libraryfolders(fake_system["steam"] / "steamapps/libraryfolders.vdf")
    assert len(paths) == 3 and paths[0].endswith(".local/share/Steam")


def test_parse_libraryfolders_old_format():
    assert steam.parse_libraryfolders(FIX / "libraryfolders_old.vdf") == ["/mnt/games/SteamLibrary", "/mnt/other"]


def test_scan_all_libraries(fake_system):
    scan = steam.scan_steam(fake_system["home"], mounts_file=fake_system["mounts"])
    names = {g.appid: g for g in scan.games}
    # installed games from BOTH libraries; tools, half-installed and broken manifests skipped
    assert set(names) == {"620", "400"}
    assert names["620"].name == "Portal 2"
    assert names["400"].name == 'Portal "Test" Edition'
    assert names["620"].has_compatdata and not names["400"].has_compatdata
    assert names["620"].size_on_disk == 12345678


def test_ntfs_library_flagged_and_missing_reported(fake_system):
    scan = steam.scan_steam(fake_system["home"], mounts_file=fake_system["mounts"])
    by_path = {str(l.path): l for l in scan.libraries}
    ntfs = by_path[str(fake_system["ntfs_lib"])]
    assert ntfs.on_ntfs and ntfs.fstype == "ntfs3" and ntfs.game_count == 1
    assert not by_path[str(fake_system["steam"])].on_ntfs
    assert len(scan.missing_libraries) == 1
    status = steam_status_text(scan)
    assert "NOT MOUNTED" in status and "NTFS" in status
    assert {g.appid: g.on_ntfs for g in scan.games} == {"620": False, "400": True}


def test_mount_parsing_handles_escaped_spaces(fake_system):
    mounts = steam.read_mounts(fake_system["mounts"])
    assert any(mp.endswith("with space") for mp, _ in mounts)
    d = fake_system["mnt"] / "with space"
    d.mkdir()
    assert steam.filesystem_of(d / "x", mounts) == "fuseblk"


def test_extra_library_from_config(fake_system, tmp_path):
    extra = tmp_path / "extra"
    (extra / "steamapps").mkdir(parents=True)
    (extra / "steamapps/appmanifest_620.acf").write_text((FIX / "appmanifest_620.acf").read_text())
    scan = steam.scan_steam(fake_system["home"], extra_libraries=[str(extra)], mounts_file=fake_system["mounts"])
    assert [g.appid for g in scan.games].count("620") == 1  # de-duplicated


def test_art_old_and_new_cache_layout(tmp_path):
    cache = tmp_path / "appcache/librarycache"
    (cache / "999/abcdef").mkdir(parents=True)
    (cache / "999/abcdef/library_600x900.jpg").write_bytes(b"x")
    (cache / "111_library_600x900.jpg").write_bytes(b"x")
    (cache / "222_header.jpg").write_bytes(b"x")
    assert steam.find_art(tmp_path, "999").endswith("999/abcdef/library_600x900.jpg")
    assert steam.find_art(tmp_path, "111").endswith("111_library_600x900.jpg")
    assert steam.find_art(tmp_path, "222").endswith("222_header.jpg")
    assert steam.find_art(tmp_path, "333") == ""
    assert steam.find_art(None, "1") == ""


def test_library_builds_steam_games_with_art_and_notes(fake_system):
    cache = fake_system["steam"] / "appcache/librarycache"
    cache.mkdir(parents=True)
    (cache / "620_library_600x900.jpg").write_bytes(b"x")
    res = build_library(default_config(), home=fake_system["home"], mounts_file=fake_system["mounts"])
    games = {g.steam_appid: g for g in res.games}
    assert games["620"].cover.endswith("620_library_600x900.jpg") and games["620"].note == ""
    assert "NTFS" in games["400"].note and games["400"].cover == ""
    assert games["620"].gid == "steam:620"
