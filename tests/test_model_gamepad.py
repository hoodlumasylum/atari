from atarilauncher import gamepad_helper as gp
from atarilauncher.library import Game
from atarilauncher.model import filter_games
from atarilauncher.store import Store


def games():
    return [Game("steam:1", "Zelda-ish", "steam", "Steam"), Game("rom:nes:a", "Alpha Quest", "nes", "Nintendo NES"),
            Game("rom:nes:b", "Beta Blaster", "nes", "Nintendo NES"), Game("rom:snes:c", "Gamma Run", "snes", "Super Nintendo")]


def test_filters_and_search(tmp_path):
    s = Store(tmp_path / "s.json")
    g = games()
    assert [x.title for x in filter_games(g, s, "all", "")] == ["Alpha Quest", "Beta Blaster", "Gamma Run", "Zelda-ish"]
    assert [x.title for x in filter_games(g, s, "nes", "")] == ["Alpha Quest", "Beta Blaster"]
    assert filter_games(g, s, "favorites", "") == [] and filter_games(g, s, "recent", "") == []
    s.toggle_favorite("rom:snes:c")
    s.mark_launched("rom:nes:b", 5)
    s.mark_launched("steam:1", 9)
    assert [x.title for x in filter_games(g, s, "favorites", "")] == ["Gamma Run"]
    assert [x.title for x in filter_games(g, s, "recent", "")] == ["Zelda-ish", "Beta Blaster"]
    assert [x.title for x in filter_games(g, s, "all", "quest")] == ["Alpha Quest"]
    assert [x.title for x in filter_games(g, s, "nes", "a")] == ["Alpha Quest", "Beta Blaster"]
    assert [x.title for x in filter_games(g, s, "snes", "alpha")] == []
    assert [x.title for x in filter_games(g, s, "all", "super nin")] == ["Gamma Run"]  # matches platform name


def test_sort_orders(tmp_path):
    s = Store(tmp_path / "s.json")
    g = games()
    g[0].added, g[1].added, g[2].added, g[3].added = 10, 40, 30, 20
    titles = lambda sort: [x.title for x in filter_games(g, s, "all", "", sort)]  # noqa: E731
    assert titles("az") == ["Alpha Quest", "Beta Blaster", "Gamma Run", "Zelda-ish"]
    assert titles("za") == ["Zelda-ish", "Gamma Run", "Beta Blaster", "Alpha Quest"]
    assert titles("added") == ["Alpha Quest", "Beta Blaster", "Gamma Run", "Zelda-ish"]
    g[3].added = 99
    assert titles("added")[0] == "Gamma Run"
    s.mark_launched("rom:snes:c", 100)
    s.mark_launched("steam:1", 200)
    assert titles("played") == ["Zelda-ish", "Gamma Run", "Alpha Quest", "Beta Blaster"]


def test_prefs_persist_and_old_state_files_load(tmp_path):
    p = tmp_path / "s.json"
    p.write_text('{"version": 1, "games": {"steam:1": {"favorite": true, "last_played": 5}}}')  # a 0.1.0 file
    s = Store(p)
    assert s.is_favorite("steam:1") and s.get_pref("sort", "az") == "az"
    s.set_pref("sort", "za")
    assert Store(p).get_pref("sort") == "za" and Store(p).is_favorite("steam:1")


def test_stick_direction():
    assert gp.stick_direction(0.1, 0.2) is None
    assert gp.stick_direction(0.9, 0.1) == "right" and gp.stick_direction(-0.9, 0.1) == "left"
    assert gp.stick_direction(0.1, -0.9) == "up" and gp.stick_direction(0.1, 0.9) == "down"


def test_repeater_repeats_after_delay_and_stops_on_release():
    r = gp.Repeater(delay=0.3, rate=0.1)
    assert r.press("down", 0.0) == ["down"]
    assert r.tick(0.2) == []
    assert r.tick(0.31) == ["down"]
    assert r.tick(0.35) == []
    assert r.tick(0.42) == ["down"]
    r.release("down")
    assert r.tick(5) == []


def test_button_map_covers_every_action():
    assert set(gp.BUTTON_MAP.values()) >= {"accept", "back", "search", "favorite", "options", "system", "prev", "next",
                                           "up", "down", "left", "right"}
    # the mockup's hints: A Select, B Back, X Favourite, Y Options, Menu change system, LB/RB previous/next
    assert [gp.BUTTON_MAP[b] for b in ("a", "b", "x", "y", "start", "leftshoulder", "rightshoulder")] == \
        ["accept", "back", "favorite", "options", "system", "prev", "next"]


def test_every_gamepad_action_has_a_key():
    from atarilauncher.backend import ACTION_KEYS
    assert set(gp.BUTTON_MAP.values()) <= set(ACTION_KEYS)
