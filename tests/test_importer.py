"""USB import: drive detection, scanning (read-only), copying with duplicates / cancel."""
import os
import threading

from atarilauncher import importer
from atarilauncher.config import default_config


def make_stick(root):
    files = {
        "Super Game (USA).sfc": 300, "Nested/Deep/Plumber.nes": 100, "gba/Tiny Tactics.gba": 50,
        "snes/Cloud Racers.zip": 40, "random/stuff.zip": 10, "PS1/Dino Dash.cue": 0, "PS1/Dino Dash.bin": 700,
        "PS1/Dino Dash (Track 2).bin": 200, "Atari 2600/Breakout.bin": 4, "readme.txt": 1,
        ".hidden/secret.nes": 5, "._Super Game (USA).sfc": 1, "System Volume Information/x.nes": 3,
        "Dreamcast/Orbit/Orbit.gdi": 0, "Dreamcast/Orbit/track01.bin": 60, "Dreamcast/Orbit/track03.raw": 80,
        "PS3/Cool Game [BLUS30001]/PS3_GAME/USRDIR/EBOOT.BIN": 70, "PS3/Cool Game [BLUS30001]/PS3_GAME/PARAM.SFO": 5,
        "PS3/Cool Game [BLUS30001]/PS3_GAME/USRDIR/data.bin": 30, "PS3/Disc Game.iso": 120, "PS3/Store Game.pkg": 20,
        "Xbox/Halo-ish.xiso": 90, "Xbox Classic/Other Game.iso": 95, "PSP/Handheld.iso": 33, "GameCube/Cube.iso": 44,
        "roms/lynx/Maze.lnx": 8, "Jag/Pit.j64": 9, "GG/Sonic-ish.gg": 6,
    }
    for rel, size in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * size)
    (root / "PS1/Dino Dash.cue").write_text('FILE "Dino Dash.bin" BINARY\n  TRACK 01 MODE2/2352\nFILE "Dino Dash (Track 2).bin" BINARY\n')
    (root / "Dreamcast/Orbit/Orbit.gdi").write_text('3\n1 0 4 2352 "track01.bin" 0\n3 45000 4 2352 "track03.raw" 0\n')


def snapshot(root):
    return sorted((str(p.relative_to(root)), p.stat().st_size) for p in root.rglob("*") if p.is_file())


def test_detect_drives_fake_mounts(tmp_path):
    media = tmp_path / "media" / "hazel"
    (media / "USBSTICK").mkdir(parents=True)
    (media / "Empty Card").mkdir()
    (media / ".hidden").mkdir()
    (media / "notadir").write_text("x")
    mounts = tmp_path / "mounts"
    mounts.write_text(f"/dev/sdb1 {media}/USBSTICK exfat rw 0 0\n/dev/sda1 / ext4 rw 0 0\n")
    drives = importer.detect_drives(user="hazel", roots=[str(media)], mounts_file=str(mounts), use_lsblk=False,
                                    require_mount=True)
    assert [d.label for d in drives] == ["USBSTICK"]  # "Empty Card" is not a mounted drive
    assert drives[0].fs_name == "exFAT"
    drives = importer.detect_drives(user="hazel", roots=[str(media)], mounts_file=str(mounts), use_lsblk=False,
                                    require_mount=False)
    assert {d.label for d in drives} == {"USBSTICK", "Empty Card"}
    assert importer.detect_drives(user="x", roots=[str(tmp_path / "nothing")], use_lsblk=False) == []


def test_scan_maps_systems_and_never_modifies_stick(tmp_path):
    stick = tmp_path / "stick"
    make_stick(stick)
    before = snapshot(stick)
    res = importer.scan_for_roms(stick, default_config())
    by_name = {it.name: it for it in res.items}
    assert by_name["Super Game (USA).sfc"].system == "snes"
    assert by_name["Plumber.nes"].system == "nes"
    assert by_name["Tiny Tactics.gba"].system == "gba"
    assert by_name["Cloud Racers.zip"].system == "snes"      # zip: folder name decides
    assert "stuff.zip" not in by_name and res.unclear == 1     # zip in an unnamed folder is skipped
    assert by_name["Dino Dash.cue"].system == "ps1"
    assert by_name["Dino Dash.cue"].size == 900 + (stick / "PS1/Dino Dash.cue").stat().st_size  # + its tracks
    assert "Dino Dash.bin" not in by_name and "Dino Dash (Track 2).bin" not in by_name
    assert by_name["Breakout.bin"].system == "atari2600"
    assert by_name["Orbit.gdi"].system == "dreamcast" and len(by_name["Orbit.gdi"].companions) == 2
    assert by_name["Maze.lnx"].system == "atarilynx" and by_name["Pit.j64"].system == "atarijaguar"
    assert by_name["Sonic-ish.gg"].system == "gamegear"
    assert "secret.nes" not in by_name and "x.nes" not in by_name and "readme.txt" not in by_name
    assert not any(n.startswith("._") for n in by_name)
    # PlayStation 3 / Xbox
    ps3 = by_name["Cool Game [BLUS30001]"]
    assert ps3.system == "ps3" and ps3.is_dir and ps3.size == 105 and len(ps3.companions) == 3
    assert "EBOOT.BIN" not in by_name and "data.bin" not in by_name  # not listed separately
    assert by_name["Disc Game.iso"].system == "ps3" and by_name["Store Game.pkg"].system == "ps3"
    assert by_name["Halo-ish.xiso"].system == "xbox" and by_name["Other Game.iso"].system == "xbox"
    assert by_name["Handheld.iso"].system == "psp" and by_name["Cube.iso"].system == "gamecube"
    assert snapshot(stick) == before


def test_folder_named_after_system_is_hint(tmp_path):
    snes = tmp_path / "SNES"
    snes.mkdir()
    (snes / "a.zip").write_bytes(b"1")
    res = importer.scan_for_roms(snes, default_config())
    assert [(i.name, i.system) for i in res.items] == [("a.zip", "snes")]


def test_copy_with_progress_duplicates_and_readonly_stick(tmp_path):
    stick = tmp_path / "stick"
    make_stick(stick)
    before = snapshot(stick)
    cfg = default_config()
    items = importer.scan_for_roms(stick, cfg).items
    games = tmp_path / "Games" / "Atari"
    custom = tmp_path / "myroms"
    cfg.systems["gba"].roms = [str(custom)]
    ticks = []
    r = importer.copy_items(items, cfg, lambda d, t, n, f: ticks.append((d, t)), games_root=games)
    assert r.copied == len(items) and not r.failed and not r.cancelled and r.error == ""
    assert (games / "snes" / "Super Game (USA).sfc").stat().st_size == 300
    assert (custom / "Tiny Tactics.gba").is_file()                      # configured folder wins
    assert (games / "ps1" / "Dino Dash" / "Dino Dash.cue").is_file()
    assert (games / "ps1" / "Dino Dash" / "Dino Dash (Track 2).bin").stat().st_size == 200
    assert (games / "dreamcast" / "Orbit" / "track03.raw").is_file()
    assert (games / "ps3" / "Cool Game [BLUS30001]" / "PS3_GAME" / "USRDIR" / "EBOOT.BIN").stat().st_size == 70
    assert (games / "ps3" / "Disc Game.iso").is_file() and (games / "xbox" / "Halo-ish.xiso").is_file()
    from atarilauncher import roms
    found = roms.scan_system([str(games / "ps3")], cfg.systems["ps3"].extensions, "ps3")
    assert sorted(r.path.name for r in found) == ["Disc Game.iso", "EBOOT.BIN", "Store Game.pkg"]
    assert "Cool Game" in [r.title for r in found if r.path.name == "EBOOT.BIN"][0]
    assert ticks and ticks[-1][0] == ticks[-1][1]
    assert not list(games.rglob("*.part"))
    assert snapshot(stick) == before
    # again: everything is a duplicate
    r2 = importer.copy_items(items, cfg, games_root=games)
    assert r2.copied == 0 and r2.skipped_duplicates == len(items)
    # same name, different size is kept as a second copy
    (stick / "Nested/Deep/Plumber.nes").write_bytes(b"y" * 123)
    items = [i for i in importer.scan_for_roms(stick, cfg).items if i.name == "Plumber.nes"]
    r3 = importer.copy_items(items, cfg, games_root=games)
    assert r3.copied == 1 and (games / "nes" / "Plumber (2).nes").stat().st_size == 123


def test_cancel_removes_partial_file(tmp_path):
    stick = tmp_path / "stick"
    stick.mkdir()
    (stick / "big.sfc").write_bytes(b"z" * (5 * importer.CHUNK))
    (stick / "small.sfc").write_bytes(b"z" * 10)
    cfg = default_config()
    items = importer.scan_for_roms(stick, cfg).items
    cancel = threading.Event()
    games = tmp_path / "g"

    def prog(done, total, name, files):
        if done >= importer.CHUNK:
            cancel.set()

    r = importer.copy_items(items, cfg, prog, cancel, games_root=games)
    assert r.cancelled
    assert not list(games.rglob("*.part"))
    assert not (games / "snes" / "big.sfc").exists()


def test_unreadable_source_is_reported_not_fatal(tmp_path):
    stick = tmp_path / "stick"
    stick.mkdir()
    (stick / "a.nes").write_bytes(b"1")
    cfg = default_config()
    items = importer.scan_for_roms(stick, cfg).items
    (stick / "a.nes").unlink()  # "unplugged"
    r = importer.copy_items(items, cfg, games_root=tmp_path / "g")
    assert r.copied == 0 and len(r.failed) == 1


def test_human_size():
    assert importer.human_size(0) == "0 B"
    assert importer.human_size(1536) == "1.5 KB"
    assert importer.human_size(5 * 1024 ** 3) == "5.0 GB"
