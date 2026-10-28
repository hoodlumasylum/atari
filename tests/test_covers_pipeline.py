"""The cover pipeline for hard names (Shenmue-style disc images), the optional sources and the picker - fake HTTP only."""
import json
import time
from pathlib import Path

import pytest

from atarilauncher import covers
from atarilauncher.library import Game
from tests.fakeserver import JPG, PNG, Fake

DC = "Sega - Dreamcast"


@pytest.fixture
def fake():
    f = Fake()
    yield f
    f.stop()


def http():
    return covers.Http(timeout=3, pause=0, backoff=0.01)


def rom(system, name, tmp_path):
    g = Game(gid=f"{system}:{name}", title=Path(name).stem, platform=system, platform_name=system)
    g.rom_path = str(tmp_path / name)
    return g


def dl(fake, tmp_path, **kw):
    return covers.CoverDownloader(fake.url, fake.url, cache_dir=tmp_path / "cache", http=http(),
                                  wiki_url=fake.url + "/w/api.php", sgdb_url=fake.url + "/sgdb", **kw)


NAMES = ["Shenmue (USA).png", "Shenmue II (USA).png", "Shenmue II (Europe).png"]


def test_shenmue_style_names_find_the_box_art(fake, tmp_path):
    fake.listing(DC, NAMES)
    root = tmp_path / "covers"
    games = [rom("dreamcast", "Shenmue (USA) (Disc 1).cdi", tmp_path), rom("dreamcast", "shenmue_disc1.gdi", tmp_path),
             rom("dreamcast", "Shenmue 2 (Disc 2).gdi", tmp_path)]
    rep = dl(fake, tmp_path).run(covers.jobs_for_games(games, root))
    assert rep.got == 3 and rep.missing == 0
    assert (root / "dreamcast" / "Shenmue (USA) (Disc 1).png").read_bytes() == PNG
    assert (root / "dreamcast" / "shenmue_disc1.png").is_file()
    assert any("Shenmue%20II" in h or "Shenmue II" in h for h in fake.hits)


def test_the_flip_roman_numerals_and_disc_numbers_in_matching():
    idx = covers.Index(["Legend of Zelda, The (USA)", "Final Fantasy VII (USA)", "Final Fantasy VII (USA) (Disc 1)"])
    assert idx.match("The Legend of Zelda") == "Legend of Zelda, The (USA)"
    assert idx.match("Final Fantasy 7 (USA) (Disc 2)") == "Final Fantasy VII (USA)"
    assert idx.match("Final Fantasy VII (USA) (Disc 1)") == "Final Fantasy VII (USA) (Disc 1)"
    assert covers.disc_number("Shenmue (USA) (Disc 2)") == 2 and covers.disc_number("shenmue_disc1") == 1


def test_title_screen_is_the_fallback_when_there_is_no_box_art(fake, tmp_path):
    fake.listing(DC, ["Other Game (USA).png"])
    fake.listing(DC, ["Shenmue (USA).png"], kind="Named_Titles", body=JPG)
    g = rom("dreamcast", "shenmue_disc1.gdi", tmp_path)
    rep = dl(fake, tmp_path).run(covers.jobs_for_games([g], tmp_path / "c"))
    assert rep.got == 1
    assert (tmp_path / "c" / "dreamcast" / "shenmue_disc1.png").read_bytes() == JPG


def wiki_json(fake, title="Shenmue (video game)", thumb=None):
    thumb = thumb or fake.url + "/img/shenmue.jpg"
    fake.files["/img/shenmue.jpg"] = JPG
    pages = {"1": {"index": 1, "title": title, "thumbnail": {"source": thumb}},
             "2": {"index": 2, "title": "Shenmue Town (film)", "thumbnail": {"source": fake.url + "/img/no.jpg"}}}
    fake.dynamic["/w/api.php"] = lambda path, q: json.dumps({"query": {"pages": pages}}).encode()


def test_wikipedia_picture_is_used_with_a_proper_user_agent(fake, tmp_path):
    wiki_json(fake)
    g = rom("dreamcast", "Shenmue (USA) (Disc 1).cdi", tmp_path)
    rep = dl(fake, tmp_path, wikipedia=True).run(covers.jobs_for_games([g], tmp_path / "c"))
    assert rep.got == 1
    assert (tmp_path / "c" / "dreamcast" / "Shenmue (USA) (Disc 1).png").read_bytes() == JPG
    assert fake.ua_seen and all("Code" in u and "/" in u for u in fake.ua_seen)


def test_wikipedia_is_off_unless_switched_on_and_wrong_pages_are_ignored(fake, tmp_path):
    wiki_json(fake)
    g = rom("dreamcast", "Shenmue (USA).cdi", tmp_path)
    rep = dl(fake, tmp_path).run(covers.jobs_for_games([g], tmp_path / "c"))
    assert rep.got == 0 and not any(h.startswith("/w/api.php") for h in fake.hits)
    wiki_json(fake, title="Totally Different Game")
    got = dl(fake, tmp_path / "x", wikipedia=True).wikipedia_images("Shenmue", "dreamcast")
    assert got == []


def sgdb(fake):
    fake.files["/img/grid.png"] = PNG
    fake.dynamic["/sgdb/search/autocomplete/"] = lambda p, q: json.dumps({"data": [{"id": 77, "name": "Shenmue"}]}).encode()
    fake.dynamic["/sgdb/grids/game/77"] = lambda p, q: json.dumps({"data": [{"url": fake.url + "/img/grid.png"}]}).encode()


def test_steamgriddb_is_used_only_with_the_users_key(fake, tmp_path):
    sgdb(fake)
    g = rom("dreamcast", "Shenmue (USA).cdi", tmp_path)
    assert dl(fake, tmp_path / "a").run(covers.jobs_for_games([g], tmp_path / "c1")).got == 0
    assert not fake.auth_seen
    rep = dl(fake, tmp_path / "b", sgdb_key="my-key").run(covers.jobs_for_games([g], tmp_path / "c2"))
    assert rep.got == 1 and fake.auth_seen and set(fake.auth_seen) == {"Bearer my-key"}


def test_misses_are_remembered_listed_and_retried_later(fake, tmp_path):
    g = rom("dreamcast", "Nothing Known Here.gdi", tmp_path)
    cache = tmp_path / "cache"
    d1 = dl(fake, tmp_path)
    assert d1.run(covers.jobs_for_games([g], tmp_path / "c")).missing == 1
    nf = covers.not_found_list(cache)
    assert [n["title"] for n in nf] == ["Nothing Known Here"] and nf[0]["system"] == "dreamcast"
    n = len(fake.hits)
    d2 = dl(fake, tmp_path)
    assert d2.run(covers.jobs_for_games([g], tmp_path / "c")).missing == 1 and len(fake.hits) == n      # remembered
    fake.listing(DC, ["Nothing Known Here (USA).png"])
    later = dl(fake, tmp_path, now=lambda: time.time() + 30 * 86400)                                      # retried after the wait
    assert later.run(covers.jobs_for_games([g], tmp_path / "c")).got == 1
    assert covers.not_found_list(cache) == []
    covers.forget_not_found(cache_dir=cache)


def test_picker_offers_about_eight_candidates_from_several_sources(fake, tmp_path):
    fake.listing(DC, NAMES + ["Shenmue (Japan).png", "Shenmue (Europe).png"])
    fake.listing(DC, ["Shenmue (USA).png"], kind="Named_Titles")
    fake.listing(DC, ["Shenmue (USA).png"], kind="Named_Snaps")
    sgdb(fake)
    wiki_json(fake)
    c = dl(fake, tmp_path, sgdb_key="k", wikipedia=True).candidates("dreamcast", "shenmue_disc1", "shenmue_disc1", limit=8)
    assert 5 <= len(c) <= 8
    assert {"libretro", "web"} <= {x["source"] for x in c}
    assert len({x["url"] for x in c}) == len(c)
    assert any(x["label"].startswith("Box art") for x in c) and any(x["label"].startswith("Title screen") for x in c)


def test_pick_from_disk_file_becomes_the_cover(tmp_path):
    # user-chosen files go through the same dest path the downloader uses
    g = rom("dreamcast", "shenmue_disc1.gdi", tmp_path)
    dest = covers.dest_for_game(g, tmp_path / "c")
    assert dest is not None and dest.parent.name == "dreamcast" and dest.suffix == ".png"
