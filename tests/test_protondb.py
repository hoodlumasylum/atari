import json

from atarilauncher import protondb


def test_badges_tiers_anticheat_and_cache(tmp_path):
    calls = []
    t = [1000.0]

    def fetch(url):
        calls.append(url)
        if "AreWeAntiCheatYet" in url:
            return json.dumps([{"name": "X", "status": "Denied", "storeIds": {"steam": "111"}},
                               {"name": "Y", "status": "Running", "storeIds": {"steam": "222"}}]).encode()
        appid = url.rsplit("/", 1)[1].split(".")[0]
        return json.dumps({"tier": {"222": "platinum", "333": "silver", "444": "borked"}.get(appid, "pending")}).encode()
    b = protondb.Badges(tmp_path / "c.json", fetch, lambda: t[0])
    out = b.badges(["111", "222", "333", "444", "555"])
    assert out == {"111": protondb.WINDOWS, "222": "Works great", "333": "Should work", "444": "May not work", "555": ""}
    n = len(calls)
    b2 = protondb.Badges(tmp_path / "c.json", fetch, lambda: t[0] + 60)
    assert b2.badges(["222"]) == {"222": "Works great"} and len(calls) == n     # cached
    off = protondb.Badges(tmp_path / "d.json", lambda u: (_ for _ in ()).throw(OSError("offline")), lambda: t[0])
    assert off.badges(["578080", "222"]) == {"578080": protondb.WINDOWS, "222": ""}
