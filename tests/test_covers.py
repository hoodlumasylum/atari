import threading
from pathlib import Path

import pytest

from atarilauncher import covers
from atarilauncher.library import Game
from tests.fakeserver import JPG, PNG, Fake


@pytest.fixture
def fake():
    f = Fake()
    yield f
    f.stop()


def fast_http(**kw):
    return covers.Http(timeout=3, pause=0, backoff=0.01, **kw)


def rom_game(system, name, tmp_path):
    g = Game(gid=f"{system}:{name}", title=Path(name).stem, platform=system, platform_name=system)
    g.rom_path = str(tmp_path / name)
    return g


def steam_game(appid, title="Portal"):
    g = Game(gid=f"steam:{appid}", title=title, platform="steam", platform_name="Steam")
    g.steam_appid = appid
    return g


# ------------------------------------------------------------------ naming
def test_sanitize_and_variants():
    assert covers.sanitize("AC/DC: Live & Loud?") == "AC_DC_ Live _ Loud_"
    assert covers.sanitize("a`b*c|d") == "a_b_c_d"
    v = covers.name_variants("Super Mario Bros. (USA) (Rev 1) [!]")
    assert v[0] == "Super Mario Bros. (USA) (Rev 1) [!]"
    assert "Super Mario Bros. (USA)" in v and "Super Mario Bros." in v
    assert covers.base_title("Sonic The Hedgehog (Europe) [!]") == "Sonic The Hedgehog"


def test_index_matching_prefers_exact_then_loose_and_region():
    idx = covers.Index(["Sonic The Hedgehog (USA, Europe)", "Sonic The Hedgehog (Japan)",
                        "Zelda II - The Adventure of Link (USA)"])
    assert idx.match("Sonic The Hedgehog (Japan)") == "Sonic The Hedgehog (Japan)"
    assert idx.match("Sonic The Hedgehog (USA) (Rev 1) [!]").startswith("Sonic The Hedgehog (USA")
    assert idx.match("Zelda II - The Adventure of Link") == "Zelda II - The Adventure of Link (USA)"
    assert idx.match("Totally Unknown Game") == ""


def test_parse_listing():
    page = '<a href="../">..</a><a href="Foo%20Bar%20%28USA%29.png">x</a><a href="notes.txt">n</a>'
    assert covers.parse_listing(page) == ["Foo Bar (USA)"]


# ------------------------------------------------------------------ downloads against a fake server
def test_rom_cover_via_listing_and_user_cover_untouched(fake, tmp_path):
    fake.listing("Nintendo - Nintendo Entertainment System", ["Brick Bash (USA).png", "Other (Europe).png"])
    root = tmp_path / "covers"
    g1 = rom_game("nes", "Brick Bash (USA) (Rev 1).nes", tmp_path)
    g2 = rom_game("nes", "Nothing Like It.nes", tmp_path)
    g3 = rom_game("nes", "Has Own.nes", tmp_path)
    g3.cover = str(tmp_path / "mine.png")        # a game that already has a cover is not even a job
    jobs = covers.jobs_for_games([g1, g2, g3], root)
    assert [j.gid for j in jobs] == [g1.gid, g2.gid]
    got = []
    seen = []
    dl = covers.CoverDownloader(fake.url, fake.url, cache_dir=root / ".cache", http=fast_http())
    rep = dl.run(jobs, progress=lambda d, t, n: seen.append((d, t, n)), on_cover=lambda j: got.append(j.gid))
    assert rep.got == 1 and rep.missing == 1 and not rep.offline
    assert got == [g1.gid]
    assert (root / "nes" / "Brick Bash (USA) (Rev 1).png").read_bytes() == PNG
    assert seen[-1] == (2, 2, 1)
    assert not list(root.rglob("*.part"))
    # the listing was fetched once only and the miss is remembered
    n = len(fake.hits)
    dl2 = covers.CoverDownloader(fake.url, fake.url, cache_dir=root / ".cache", http=fast_http())
    rep2 = dl2.run(covers.jobs_for_games([g1, g2], root))
    assert rep2.got == 0 and len(fake.hits) == n
    # "Download covers" (force) tries the missing one again
    fake.listing("Nintendo - Nintendo Entertainment System", ["Nothing Like It (USA).png"])
    dl3 = covers.CoverDownloader(fake.url, fake.url, cache_dir=root / ".cache", http=fast_http(), force=True,
                                 now=lambda: __import__("time").time() + 15 * 86400)
    rep3 = dl3.run(covers.jobs_for_games([g2], root))
    assert rep3.got == 1


def test_rom_without_listing_tries_direct_names(fake, tmp_path):
    fake.files["/Sega - Mega Drive - Genesis/Named_Boxarts/Sonic (USA).png"] = PNG   # no directory listing at all
    root = tmp_path / "c"
    g = rom_game("genesis", "Sonic (USA) [!].md", tmp_path)
    rep = covers.CoverDownloader(fake.url, fake.url, cache_dir=root / ".cache", http=fast_http()).run(
        covers.jobs_for_games([g], root))
    assert rep.got == 1 and (root / "genesis" / "Sonic (USA) [!].png").is_file()


def test_retry_after_503_then_ok(fake, tmp_path):
    fake.listing("Sega - Mega Drive - Genesis", ["Sonic (USA).png"])
    fake.flaky["/Sega - Mega Drive - Genesis/Named_Boxarts/Sonic (USA).png"] = 2
    root = tmp_path / "c"
    g = rom_game("genesis", "Sonic (USA).md", tmp_path)
    rep = covers.CoverDownloader(fake.url, fake.url, cache_dir=root / ".cache", http=fast_http()).run(
        covers.jobs_for_games([g], root))
    assert rep.got == 1


def test_offline_is_reported_and_nothing_crashes(tmp_path):
    root = tmp_path / "c"
    games = [rom_game("nes", f"G{i}.nes", tmp_path) for i in range(5)]
    http = covers.Http(timeout=0.5, retries=2, pause=0, backoff=0.01)
    rep = covers.CoverDownloader("http://127.0.0.1:9", "http://127.0.0.1:9", cache_dir=root / ".cache", http=http).run(
        covers.jobs_for_games(games, root))
    assert rep.offline and rep.got == 0
    assert rep.text().startswith("Offline")


def test_cancel_stops_quickly(fake, tmp_path):
    fake.listing("Nintendo - Nintendo Entertainment System", [f"G{i} (USA).png" for i in range(20)])
    root = tmp_path / "c"
    games = [rom_game("nes", f"G{i} (USA).nes", tmp_path) for i in range(20)]
    cancel = threading.Event()
    got = []

    def on_cover(j):
        got.append(j)
        if len(got) == 3:
            cancel.set()

    rep = covers.CoverDownloader(fake.url, fake.url, cache_dir=root / ".cache", http=fast_http()).run(
        covers.jobs_for_games(games, root), on_cover=on_cover, cancel=cancel)
    assert rep.cancelled and 3 <= rep.got < 20


def test_steam_local_first_cdn_second_header_fallback(fake, tmp_path):
    root = tmp_path / "c"
    fake.files["/620/library_600x900.jpg"] = JPG
    fake.files["/620/header.jpg"] = JPG
    fake.files["/999/header.jpg"] = JPG                  # no tall art for this one: the wide header serves as cover
    g1, g2, g3 = steam_game("620"), steam_game("999", "Other"), steam_game("5", "Nope")
    g3.cover, g3.header = "/x/c.jpg", "/x/h.jpg"          # already has art: no job
    jobs = covers.jobs_for_games([g1, g2, g3], root)
    assert {(j.gid, j.kind) for j in jobs} == {(g1.gid, "steam-cover"), (g1.gid, "steam-header"),
                                               (g2.gid, "steam-cover"), (g2.gid, "steam-header")}
    rep = covers.CoverDownloader(fake.url, fake.url, cache_dir=root / ".cache", http=fast_http()).run(jobs)
    assert rep.got == 4
    assert covers.find_downloaded_steam_art("620", "cover", root).endswith("620_cover.jpg")
    assert covers.find_downloaded_steam_art("999", "cover", root)
    assert "/999/library_600x900.jpg" in fake.hits       # tried tall art first
    # nothing is asked for again once the files are on disk
    assert covers.jobs_for_games([g1], root) != [] and all(j.dest.is_file() for j in covers.jobs_for_games([g1], root))


def test_html_error_page_is_not_saved_as_cover(fake, tmp_path):
    root = tmp_path / "c"
    fake.files["/620/library_600x900.jpg"] = b"<html>captive portal</html>"
    fake.files["/620/header.jpg"] = b"<html>captive portal</html>"
    jobs = covers.jobs_for_games([steam_game("620")], root)
    rep = covers.CoverDownloader(fake.url, fake.url, cache_dir=root / ".cache", http=fast_http()).run(jobs)
    assert rep.got == 0 and not list(root.rglob("*.jpg"))


def test_library_uses_downloaded_steam_art(fake_system, tmp_path, monkeypatch):
    from atarilauncher import config, library
    monkeypatch.setenv("HOME", str(fake_system["home"]))
    monkeypatch.setenv("ATARI_DATA_DIR", str(tmp_path / "data"))
    root = tmp_path / "covroot"
    (root / "steam").mkdir(parents=True)
    (root / "steam" / "620_cover.jpg").write_bytes(JPG)
    assert covers.find_downloaded_steam_art("620", "cover", root).endswith("620_cover.jpg")
