"""0.3.1 installer pieces: DuckStation AppImage with a checksum, essentials vs everything, EOL noise, Steam helpers."""
import hashlib
import json
import stat

import pytest

from atarilauncher import appinstall, covers, emulators, installer, steam
from atarilauncher.emulators import EMUS
from tests.fakeserver import Fake


@pytest.fixture
def fake():
    f = Fake()
    yield f
    f.stop()


def release(fake, body: bytes, digest=None, name="DuckStation-x64.AppImage"):
    d = "sha256:" + hashlib.sha256(body).hexdigest() if digest is None else digest
    fake.files["/stenzek/x"] = body
    fake.files["/repos/stenzek/duckstation/releases/tags/latest"] = json.dumps({"assets": [
        {"name": name, "size": len(body), "digest": d, "browser_download_url": fake.url + "/stenzek/x"}]}).encode()


def http():
    return covers.Http(timeout=3, pause=0, backoff=0.01)


def test_duckstation_has_no_flatpak_and_installs_the_appimage_with_a_verified_checksum(fake, tmp_path, monkeypatch):
    monkeypatch.setenv("ATARI_GITHUB_API", fake.url)
    e = EMUS["duckstation"]
    assert not e.flatpak and e.appimage.startswith("stenzek/duckstation|")
    release(fake, b"\x7fELF" + b"A" * 4096)
    out = []
    o = installer.install_appimage(e, out.append, tmp_path, http())
    assert o.status == "installed"
    p = emulators.appimage_path(e, tmp_path)
    assert p.startswith(str(tmp_path / ".local/share/atari/emulators")) and (tmp_path / ".local/share/atari/emulators/DuckStation-x64.AppImage").stat().st_mode & stat.S_IXUSR
    assert installer.install_appimage(e, out.append, tmp_path, http()).status == "already"


def test_a_wrong_checksum_or_missing_digest_installs_nothing(fake, tmp_path, monkeypatch):
    monkeypatch.setenv("ATARI_GITHUB_API", fake.url)
    e = EMUS["duckstation"]
    release(fake, b"data" * 500, digest="sha256:" + "0" * 64)
    o = installer.install_appimage(e, lambda s: None, tmp_path, http())
    assert o.status == "failed" and "checksum" in o.detail and not emulators.appimage_path(e, tmp_path)
    release(fake, b"data" * 500, digest="")
    o = installer.install_appimage(e, lambda s: None, tmp_path, http())
    assert o.status == "failed" and "no checksum" in o.detail.lower() and not emulators.appimage_path(e, tmp_path)


def test_the_app_installer_plans_the_appimage_for_duckstation(tmp_path):
    t = appinstall.target_for("duckstation")
    assert appinstall.plan(t, flatpak=True, pkexec=True, apt=True) == ["appimage"]


def test_essentials_are_the_seven_big_emulators_and_everything_is_larger():
    ess = [e.id for e in installer.essential_selection()]
    assert ess == [i for i in installer.ESSENTIAL_IDS if i in ess] and {"retroarch", "pcsx2", "dolphin", "ppsspp", "melonds", "mgba", "flycast"} <= set(ess)
    assert len(installer.default_selection()) > len(ess) + 5


def test_eol_chatter_is_hidden_but_real_lines_are_not():
    assert installer.is_noise("Warning: org.duckstation.DuckStation is end-of-life, with reason:")
    assert installer.is_noise("Applications using this runtime: foo")
    assert not installer.is_noise("Installing org.mgba.mGBA")


def test_no_flatpak_id_is_known_end_of_life():
    ids = {e.flatpak for e in EMUS.values() if e.flatpak}
    assert "org.duckstation.DuckStation" not in ids
    from atarilauncher import apps, freegames
    assert "org.duckstation.DuckStation" not in {a.flatpak for a in apps.APP_DEFS}
    assert "net.openarena.OpenArena" not in {g.ref for g in freegames.GAMES}


def test_steam_drive_advice_recommends_ext4_and_warns_about_ntfs(tmp_path):
    mounts = [("/", "ext4"), ("/media/me/WIN", "ntfs"), ("/media/me/STICK", "exfat"), ("/mnt/data", "btrfs"), ("/proc", "proc")]
    adv = steam.drive_advice(mounts, tmp_path)
    by = {a["path"]: a for a in adv}
    assert by["/"]["ok"] and "good for Steam games" in by["/"]["text"]
    assert not by["/media/me/WIN"]["ok"] and "avoid" in by["/media/me/WIN"]["text"] and "NTFS" in by["/media/me/WIN"]["text"]
    assert not by["/media/me/STICK"]["ok"] and by["/mnt/data"]["ok"]
    assert "/proc" not in by and adv[0]["ok"]


def test_steam_is_an_app_tile_that_offers_install_when_missing(tmp_path, monkeypatch):
    from atarilauncher import config, library
    monkeypatch.setenv("PATH", "/nonexistent")
    cfg = config.default_config()
    cfg.steam_enabled = False
    games = {g.gid: g for g in library.build_library(cfg, home=tmp_path, metadata={}).games}
    assert games["app:steam"].missing == "steam"
    assert games["free:cs2"].missing == "steam"                 # "Install a Steam game" first asks for Steam itself
    t = appinstall.target_for("steam")
    assert t.flatpak == "com.valvesoftware.Steam" and t.apt == "steam-installer"
