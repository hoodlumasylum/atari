"""0.3.2: original-Xbox .iso games (sniffing, "Which system is this?", skipped-file reasons, default.xbe folders),
the Steam controller-permissions fix, and Steam in Big Picture with Esc / Guide+B back to CodeAque."""
import os
import struct
import threading
import time

import pytest

from atarilauncher import config, exitwatch, importer, inputfix, launcher, library, roms, steam, xbox
from atarilauncher.config import default_config
from tests.test_exitwatch import X, tap, xvfb  # noqa: F401  (real Xvfb fixture)

XBOX_MAGIC = b"MICROSOFT*XBOX*MEDIA"


# ------------------------------------------------------------------ helpers: tiny disc images
def dir_record(name: bytes, lba: int, size: int, is_dir=False) -> bytes:
    n = len(name)
    rec = bytearray(33 + n + (0 if n % 2 else 1))
    rec[0] = len(rec)
    rec[2:6] = struct.pack("<I", lba)
    rec[6:10] = struct.pack(">I", lba)
    rec[10:14] = struct.pack("<I", size)
    rec[14:18] = struct.pack(">I", size)
    rec[25] = 2 if is_dir else 0
    rec[32] = n
    rec[33:33 + n] = name
    return bytes(rec)


def make_iso9660(path, files=None, dirs=()):
    """A minimal ISO 9660 image: root folder with the given files and (empty) folders."""
    files = files or {}
    root_lba, data_lba = 20, 30
    recs = [dir_record(b"\x00", root_lba, 2048, True), dir_record(b"\x01", root_lba, 2048, True)]
    blobs = {}
    for name, data in files.items():
        recs.append(dir_record(name.encode() + b";1", data_lba, len(data)))
        blobs[data_lba] = data
        data_lba += 1
    for d in dirs:
        recs.append(dir_record(d.encode(), data_lba, 2048, True))
        data_lba += 1
    root = b"".join(recs).ljust(2048, b"\0")
    img = bytearray(2048 * (data_lba + 1))
    pvd = bytearray(2048)
    pvd[0] = 1
    pvd[1:6] = b"CD001"
    pvd[156:156 + 34] = dir_record(b"\x00", root_lba, 2048, True)[:34]
    img[0x8000:0x8000 + 2048] = pvd
    img[root_lba * 2048:root_lba * 2048 + 2048] = root
    for lba, data in blobs.items():
        img[lba * 2048:lba * 2048 + len(data)] = data
    path.write_bytes(bytes(img))
    return path


def make_xbox_iso(path, offset=0):
    with open(path, "wb") as fh:
        fh.seek(offset + 0x10000)
        fh.write(XBOX_MAGIC)
        fh.write(b"\0" * 4096)
    return path


def shenmue_layout(tmp_path, magic=True):
    """~/Downloads/Shenmue II (USA)/Shenmue II (USA).iso + readme.txt - the exact layout from the bug report."""
    folder = tmp_path / "home" / "Downloads" / "Shenmue II (USA)"
    folder.mkdir(parents=True)
    iso = folder / "Shenmue II (USA).iso"
    if magic:
        make_xbox_iso(iso)
    else:
        iso.write_bytes(b"\0" * 4096)
    (folder / "readme.txt").write_text("hello")
    return folder, iso


# ------------------------------------------------------------------ looking inside disc images
def test_xbox_iso_is_recognised_by_its_xdvdfs_signature_at_every_known_offset(tmp_path):
    for off in importer.XBOX_OFFSETS:
        p = tmp_path / f"x{off}.iso"
        make_xbox_iso(p, off)
        assert importer.sniff_disc(p) == "xbox", hex(off)


def test_other_discs_are_told_apart(tmp_path):
    gc = tmp_path / "gc.iso"
    gc.write_bytes(b"GALE01" + b"\0" * 22 + bytes.fromhex("C2339F3D") + b"\0" * 100)
    wii = tmp_path / "wii.iso"
    wii.write_bytes(b"RSPE01" + b"\0" * 18 + bytes.fromhex("5D1C9EA3") + b"\0" * 100)
    ps2 = make_iso9660(tmp_path / "ps2.iso", {"SYSTEM.CNF": b"BOOT2 = cdrom0:\\SLUS_123.45;1\r\nVER = 1.00\r\n"})
    ps1 = make_iso9660(tmp_path / "ps1.iso", {"SYSTEM.CNF": b"BOOT = cdrom:\\SLUS_012.34;1\r\nTCB = 4\r\n"})
    psp = make_iso9660(tmp_path / "psp.iso", dirs=["PSP_GAME"])
    plain = make_iso9660(tmp_path / "plain.iso", {"README.TXT": b"hi"})
    assert [importer.sniff_disc(p) for p in (gc, wii, ps2, ps1, psp, plain)] == \
        ["gamecube", "wii", "ps2", "ps1", "psp", ""]
    assert importer.sniff_disc(tmp_path / "missing.iso") == ""


# ------------------------------------------------------------------ the bug report, exactly
def test_shenmue_2_iso_in_its_folder_is_found_as_xbox(tmp_path):
    folder, iso = shenmue_layout(tmp_path)
    res = importer.scan_for_roms(folder, default_config())
    assert [(i.name, i.system) for i in res.items] == [("Shenmue II (USA).iso", "xbox")]
    assert res.skipped == [] and res.files_seen == 2
    # picking the parent (Downloads) works the same way
    res2 = importer.scan_for_roms(folder.parent, default_config())
    assert [(i.name, i.system, i.rel) for i in res2.items] == [("Shenmue II (USA).iso", "xbox",
                                                                "Shenmue II (USA)/Shenmue II (USA).iso")]


def test_unknown_iso_is_never_silently_skipped(tmp_path):
    folder, iso = shenmue_layout(tmp_path, magic=False)
    res = importer.scan_for_roms(folder, default_config())
    assert res.items == [] and res.unclear == 1
    [k] = res.skipped
    assert k.name == "Shenmue II (USA).iso" and "which console" in k.reason
    for sid in ("xbox", "ps2", "gamecube", "wii", "psp", "ps1"):
        assert sid in k.candidates                                   # the "Which system is this?" choices
    assert "1 .iso" in res.seen_text() and "1 .txt" in res.seen_text()   # what was seen is listed too
    assert k.to_item("xbox").system == "xbox" and k.to_item("xbox").size == 4096


def test_a_folder_named_xbox_still_decides_without_a_signature(tmp_path):
    (tmp_path / "Xbox").mkdir()
    (tmp_path / "Xbox" / "g.iso").write_bytes(b"\0" * 100)
    res = importer.scan_for_roms(tmp_path, default_config())
    assert [(i.name, i.system) for i in res.items] == [("g.iso", "xbox")] and not res.skipped


def test_the_signature_beats_a_wrong_folder_name(tmp_path):
    (tmp_path / "PS2").mkdir()
    make_xbox_iso(tmp_path / "PS2" / "oops.iso")
    res = importer.scan_for_roms(tmp_path, default_config())
    assert [(i.name, i.system) for i in res.items] == [("oops.iso", "xbox")]


def test_xiso_extension_is_xbox_and_uppercase_iso_works(tmp_path):
    (tmp_path / "a.xiso").write_bytes(b"x")
    make_xbox_iso(tmp_path / "B.ISO")
    res = importer.scan_for_roms(tmp_path, default_config())
    assert sorted((i.name, i.system) for i in res.items) == [("B.ISO", "xbox"), ("a.xiso", "xbox")]


def test_unpacked_xbox_game_folder_with_default_xbe(tmp_path):
    g = tmp_path / "stick" / "Halo Ish (USA)"
    (g / "Media").mkdir(parents=True)
    (g / "default.xbe").write_bytes(b"XBEH" + b"\0" * 100)
    (g / "Media" / "a.bin").write_bytes(b"1" * 50)
    cfg = default_config()
    res = importer.scan_for_roms(tmp_path / "stick", cfg)
    [it] = res.items
    assert it.system == "xbox" and it.is_dir and it.name == "Halo Ish (USA)" and len(it.companions) == 2
    games = tmp_path / "Games"
    r = importer.copy_items(res.items, cfg, games_root=games)
    assert r.copied == 1 and (games / "xbox" / "Halo Ish (USA)" / "default.xbe").is_file()
    found = roms.scan_system([str(games / "xbox")], cfg.systems["xbox"].extensions, "xbox")
    assert [(r.title, r.path.name) for r in found] == [("Halo Ish", "default.xbe")]


def test_xbox_folder_games_become_a_disc_image_for_xemu(tmp_path, monkeypatch):
    game = tmp_path / "G" / "default.xbe"
    game.parent.mkdir()
    game.write_bytes(b"x")
    assert xbox.disc_image_for("/x/y.iso") == "/x/y.iso"                       # normal discs pass through
    monkeypatch.setattr(xbox, "find_extract_xiso", lambda: "")
    with pytest.raises(RuntimeError) as e:
        xbox.disc_image_for(str(game), cache_dir=tmp_path / "c")
    assert ".iso" in str(e.value) and "extract-xiso" in str(e.value)
    monkeypatch.setattr(xbox, "find_extract_xiso", lambda: "/usr/bin/extract-xiso")
    calls = []

    def fake(cmd, **kw):
        calls.append(cmd)
        open(cmd[-1], "wb").write(b"iso")
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
    out = xbox.disc_image_for(str(game), runner=fake, cache_dir=tmp_path / "c")
    assert out.endswith("G.xiso") and calls == [["/usr/bin/extract-xiso", "-c", str(game.parent), out]]
    assert xbox.disc_image_for(str(game), runner=fake, cache_dir=tmp_path / "c") == out and len(calls) == 1  # cached


def test_xemu_launch_command_for_an_iso():
    cfg = default_config()
    cfg.systems["xbox"].command = ""
    cfg.emulator_commands["xemu"] = "xemu"
    cmd = launcher.build_rom_command(cfg, cfg.systems["xbox"], "/g/Shenmue II (USA).iso")
    assert cmd == ["xemu", "-full-screen", "-dvd_path", "/g/Shenmue II (USA).iso"]
    assert set(cfg.systems["xbox"].extensions) >= {"iso", "xiso"}


# ------------------------------------------------------------------ the wizard: "Which system is this?"
from PySide6.QtCore import Qt  # noqa: E402

from tests.test_features_ui import conf, wait_for  # noqa: E402
from tests.test_studio_click import click_text, texts  # noqa: E402
from tests.test_ui_keys import Ui, app, pump  # noqa: E402,F401


def shown(ui):
    return [t for t, _ in texts(ui)]


def test_unknown_iso_asks_which_system_with_big_buttons_and_imports_it(app, tmp_path, monkeypatch):
    folder, iso = shenmue_layout(tmp_path, magic=False)
    games = tmp_path / "Games" / "Atari" / "xbox"
    conf(tmp_path, f'[steam]\nenabled = false\n[systems.xbox]\nroms = ["{games}"]\n')
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        ui.backend.openImportKind("games")
        ui.win.setProperty("mode", "import")
        ui.backend.startImportScan(str(folder))
        assert wait_for(app, lambda: ui.backend.importState == "choose"), ui.backend.importState
        ui.win.setProperty("mode", "import")
        pump(app)
        s = shown(ui)
        assert "Which system is this?" in s and "Shenmue II (USA).iso" in s
        for label in ("Xbox Classic", "PlayStation 2", "GameCube", "Not now - skip these files"):
            assert label in s, s
        click_text(ui, "Xbox Classic")                                   # a big button, clicked with the mouse
        assert wait_for(app, lambda: ui.backend.importState == "list")
        assert ui.backend.importItems.rowCount() == 1 and ui.backend.importPendingCount == 0
        ui.backend.startImportCopy()
        assert wait_for(app, lambda: ui.backend.importState == "done", 15)
        assert ui.backend.importMessage.startswith("Done - 1 game added")
        assert (games / "Shenmue II (USA).iso").is_file()
        found = roms.scan_system([str(games)], default_config().systems["xbox"].extensions, "xbox")
        assert [r.title for r in found] == ["Shenmue II"]
    finally:
        ui.close()


def test_skipping_lists_the_file_with_its_reason_and_choose_system_button_comes_back(app, tmp_path, monkeypatch):
    folder, iso = shenmue_layout(tmp_path, magic=False)
    conf(tmp_path, '[steam]\nenabled = false\n')
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        ui.backend.openImportKind("games")
        ui.backend.startImportScan(str(folder))
        assert wait_for(app, lambda: ui.backend.importState == "choose")
        ui.backend.chooseImportSystem("")                                # "Not now"
        assert ui.backend.importState == "list" and ui.backend.importPendingCount == 1
        msg = ui.backend.importMessage
        assert "No games added yet" in msg and "1 .iso" in msg and "1 .txt" in msg           # what was seen
        assert "Shenmue II (USA).iso" in msg and "which console" in msg                      # skipped + reason
        assert "CHOOSE SYSTEM" in msg
        ui.backend.askImportSystems()                                    # the CHOOSE SYSTEM button
        assert ui.backend.importState == "choose"
        rows = ui.backend.importChoiceRows()
        assert rows[0]["kind"] == "system" and rows[-1]["kind"] == "skip"
        ui.backend.chooseImportSystem("ps2")
        assert ui.backend.importItems.rowCount() == 1 and ui.backend.importItems.selected_items()[0].system == "ps2"
    finally:
        ui.close()


def test_nothing_found_says_what_was_in_the_folder(app, tmp_path, monkeypatch):
    d = tmp_path / "empty"
    d.mkdir()
    (d / "notes.txt").write_text("x")
    conf(tmp_path, '[steam]\nenabled = false\n')
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        ui.backend.openImportKind("games")
        ui.backend.startImportScan(str(d))
        assert wait_for(app, lambda: ui.backend.importState == "list")
        m = ui.backend.importMessage
        assert m.startswith("No games found") and "1 .txt" in m and "default.xbe" in m
    finally:
        ui.close()


def test_keyboard_can_answer_which_system(app, tmp_path, monkeypatch):
    folder, iso = shenmue_layout(tmp_path, magic=False)
    conf(tmp_path, '[steam]\nenabled = false\n')
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        ui.backend.openImportKind("games")
        ui.win.setProperty("mode", "import")
        ui.backend.startImportScan(str(folder))
        assert wait_for(app, lambda: ui.backend.importState == "choose")
        ui.key(Qt.Key_Escape)                                            # Esc / B = skip, never a dead end
        assert ui.backend.importState == "list" and ui.backend.importPendingCount == 1
    finally:
        ui.close()


# ------------------------------------------------------------------ Steam controller / gamepad permissions
def test_input_fix_status_and_apt_path(tmp_path, monkeypatch):
    empty = tmp_path / "rules"
    empty.mkdir()
    ok, text = inputfix.status((str(empty),), str(tmp_path / "nouinput"))
    assert not ok and "steam-devices" in text and "password" in text
    (empty / "60-steam-input.rules").write_text("x")
    uin = tmp_path / "uinput"
    uin.write_text("")
    assert inputfix.status((str(empty),), str(uin))[0]
    monkeypatch.setattr(inputfix, "rules_installed", lambda dirs=None: True)
    calls, lines = [], []

    def run(cmd, out, cancel):
        calls.append(cmd)
        return 0
    ok, text = inputfix.fix(lines.append, run=run, which=lambda n: "/usr/bin/" + n)
    assert ok and "Unplug your controller" in text
    assert calls[0][:3] == ["pkexec", "sh", "-c"] and "apt-get install -y steam-devices" in calls[0][3]
    assert "udevadm control --reload-rules" in calls[0][3] and "udevadm trigger" in calls[0][3]


def test_input_fix_falls_back_to_valves_rules_file(tmp_path, monkeypatch):
    monkeypatch.setattr(inputfix, "rules_installed", lambda dirs=None: False)
    calls = []
    got = []

    def run(cmd, out, cancel):
        calls.append(cmd)
        return 100 if "apt-get" in cmd[3] else 0

    def download(dest):
        got.append(dest)
        open(dest, "w").write("# 28de")
        return True
    ok, text = inputfix.fix(lambda s: None, run=run, which=lambda n: "/x/" + n, download=download)
    assert ok and len(calls) == 2 and got
    assert f"install -m 0644 {got[0]} /etc/udev/rules.d/60-steam-input.rules" in calls[1][3]
    ok, text = inputfix.fix(lambda s: None, run=run, which=lambda n: "/x/" + n, download=lambda d: False)
    assert not ok and "online" in text and "sudo apt install steam-devices" in text


def test_input_fix_without_pkexec_or_when_the_password_window_is_closed(monkeypatch):
    ok, text = inputfix.fix(lambda s: None, run=lambda *a: 0, which=lambda n: None)
    assert not ok and "sudo apt install steam-devices" in text
    monkeypatch.setattr(inputfix, "rules_installed", lambda dirs=None: False)
    ok, text = inputfix.fix(lambda s: None, run=lambda *a: 126, which=lambda n: "/x/" + n, download=lambda d: open(d, "w").write("28de") and True)
    assert not ok and "closed" in text


def test_download_rejects_a_page_that_is_not_a_rules_file(tmp_path, monkeypatch):
    from tests.fakeserver import Fake
    f = Fake()
    f.files["/good"] = b'SUBSYSTEMS=="usb", ATTRS{idVendor}=="28de", MODE="0660", TAG+="uaccess"\n'
    f.files["/bad"] = b"<html>404</html>"
    try:
        assert inputfix.download_rules(str(tmp_path / "a"), f.url + "/good") and (tmp_path / "a").read_bytes().startswith(b"SUBSYS")
        assert not inputfix.download_rules(str(tmp_path / "b"), f.url + "/bad")
    finally:
        f.stop()


def test_troubleshoot_has_the_one_click_fix_and_it_runs_in_the_background(app, tmp_path, monkeypatch):
    conf(tmp_path, '[steam]\nenabled = false\n')
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        b = ui.backend
        for page_name in ("help", "steam"):
            ids = [r.get("id") for r in b.pageRows(page_name)]
            assert "inputfix" in ids, page_name
        titles = " ".join(r.get("title", "") for r in b.pageRows("help"))
        assert "Missing permissions for input devices" in titles
        called = []
        monkeypatch.setattr(inputfix, "fix", lambda out, **kw: (called.append(1) or (True, "Done. Unplug your controller")))
        assert b.pageActivate("help", "inputfix") == ""
        assert wait_for(app, lambda: b.toast.startswith("Done. Unplug"), 5), b.toast
        assert called == [1]
    finally:
        ui.close()


# ------------------------------------------------------------------ Steam in Big Picture
def test_big_picture_is_on_by_default_and_saved(tmp_path):
    cfg = config.default_config()
    assert cfg.steam_bigpicture is True
    f = tmp_path / "config.toml"
    cfg.steam_bigpicture = False
    config.save_config(cfg, f)
    assert "steam_bigpicture = false" in f.read_text()
    assert config.load_config(f).steam_bigpicture is False
    f.write_text("[ui]\nvolume = 0.5\n")                      # an old config without the setting: ON
    assert config.load_config(f).steam_bigpicture is True


def test_big_picture_commands():
    base = ["steam"]
    assert launcher.bigpicture_command(None, base, running=False) == ["steam", "-gamepadui"]
    assert launcher.bigpicture_command(None, base, running=True) == ["steam", "steam://open/bigpicture"]
    fp = ["flatpak", "run", "com.valvesoftware.Steam"]
    assert launcher.bigpicture_command(None, fp, False) == ["flatpak", "run", "com.valvesoftware.Steam", "-gamepadui"]


def test_steam_process_detection_in_a_fake_proc(tmp_path):
    def proc(pid, *args):
        d = tmp_path / str(pid)
        d.mkdir()
        (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in args) + b"\0")
    proc(1, "python3", "-m", "atarilauncher")
    assert not steam.steam_running(str(tmp_path)) and not steam.steam_game_running(str(tmp_path))
    proc(2, "/bin/bash", "/usr/games/steam", "-gamepadui")
    assert steam.steam_running(str(tmp_path))
    proc(3, "/home/u/.steam/ubuntu12_32/reaper", "SteamLaunch", "AppId=620", "--", "game")
    assert steam.steam_game_running(str(tmp_path))


def test_hint_and_settings_toggle(app, tmp_path, monkeypatch):
    from atarilauncher.library import Game
    cfg = config.default_config()
    g = Game(gid="app:steam", title="Steam", platform="apps", platform_name="PC / Apps")
    assert "Esc twice" in launcher.controls_hint(cfg, g)
    cfg.steam_bigpicture = False
    assert launcher.controls_hint(cfg, g) == ""
    conf(tmp_path, '[steam]\nenabled = false\n')
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        b = ui.backend
        rows = [r for r in b.setupRows() if r.get("kind") == "bigpicture"]
        assert rows and rows[0]["title"] == "Open Steam in Big Picture (full screen)" and rows[0]["value"] == "ON"
        b.toggleSteamBigPicture()
        assert b.cfg.steam_bigpicture is False
        assert [r for r in b.setupRows() if r.get("kind") == "bigpicture"][0]["value"] == "OFF"
    finally:
        ui.close()


@pytest.fixture
def fake_steam(tmp_path, monkeypatch):
    """A pretend `steam` command: logs its arguments; 'alive' while a flag file exists; steam://close/bigpicture ends it."""
    log, alive = tmp_path / "steam.log", tmp_path / "alive"
    script = tmp_path / "steam"
    script.write_text(f'#!/bin/sh\necho "$@" >> {log}\ncase "$1" in steam://close/bigpicture) rm -f {alive};; '
                      f'*) touch {alive};; esac\n')
    script.chmod(0o755)
    monkeypatch.setenv("ATARI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("ATARI_HINT_DELAY", "0")
    monkeypatch.setenv("ATARI_STEAM_WAIT", "5")
    monkeypatch.setattr(steam, "steam_running", lambda root="/proc": alive.exists())
    state = {"game": False}
    monkeypatch.setattr(steam, "steam_game_running", lambda root="/proc": state["game"])
    cfg = config.default_config()
    cfg.emulator_commands["steam"] = str(script)
    game = [g for g in library.build_library(cfg, home=tmp_path).games if g.gid == "app:steam"][0]
    return cfg, game, log, alive, state


def lines(log):
    return log.read_text().split("\n")[:-1] if log.exists() else []


@X
def test_steam_tile_opens_big_picture_and_esc_twice_comes_back(xvfb, fake_steam):
    cfg, game, log, alive, _ = fake_steam

    def press():
        time.sleep(1.2)
        tap()
        time.sleep(0.12)
        tap()
    th = threading.Thread(target=press, daemon=True)
    th.start()
    started = []
    t0 = time.time()
    secs, err = launcher.run_game(cfg, game, on_started=lambda: started.append(1))
    th.join(10)
    assert err == "" and started == [1] and time.time() - t0 < 20
    assert lines(log) == ["-gamepadui", "steam://close/bigpicture"]


@X
def test_a_single_esc_and_esc_inside_a_game_do_not_close_steam(xvfb, fake_steam):
    cfg, game, log, alive, state = fake_steam
    state["game"] = True                                    # a Steam game is running in front

    def press():
        time.sleep(1.2)
        tap()
        time.sleep(0.12)
        tap()                                               # Esc twice - but the game owns Esc
        time.sleep(1.5)
        assert alive.exists() and lines(log) == ["-gamepadui"]
        exitwatch.request_quit("gamepad")                   # Guide + B still returns
    th = threading.Thread(target=press, daemon=True)
    th.start()
    secs, err = launcher.run_game(cfg, game, on_started=lambda: None)
    th.join(10)
    assert err == "" and lines(log) == ["-gamepadui", "steam://close/bigpicture"]


def test_guide_b_leaves_big_picture_without_a_keyboard_watcher(fake_steam, monkeypatch):
    cfg, game, log, alive, _ = fake_steam
    monkeypatch.delenv("DISPLAY", raising=False)             # no X11: the gamepad chord is the way back

    def chord():
        for _ in range(100):
            time.sleep(0.1)
            if exitwatch.request_quit("gamepad"):
                return
    th = threading.Thread(target=chord, daemon=True)
    th.start()
    secs, err = launcher.run_game(cfg, game, on_started=lambda: None)
    th.join(10)
    assert err == "" and lines(log) == ["-gamepadui", "steam://close/bigpicture"]


def test_already_running_steam_is_switched_with_the_open_link_and_toggle_off_keeps_the_old_behaviour(fake_steam, monkeypatch):
    cfg, game, log, alive, _ = fake_steam
    alive.write_text("")
    monkeypatch.delenv("DISPLAY", raising=False)
    threading.Timer(1.0, lambda: exitwatch.request_quit("gamepad")).start()
    secs, err = launcher.run_game(cfg, game, on_started=lambda: None)
    assert err == "" and lines(log)[0] == "steam://open/bigpicture"
    log.unlink()
    cfg.steam_bigpicture = False                             # normal window: start Steam and come straight back
    secs, err = launcher.run_game(cfg, game, on_started=lambda: None)
    assert secs == 0.0 and "Steam is starting" in err
    time.sleep(0.3)
    assert "-gamepadui" not in lines(log) and "" in lines(log)      # started plainly (a late close from the first part is not ours)
