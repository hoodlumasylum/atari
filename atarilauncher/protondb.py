"""Modern Games: a plain "will it run?" badge for each Steam game, from ProtonDB's public summary (protondb.com/api/v1/reports/
summaries/<appid>.json - the community rating) and the AreWeAntiCheatYet list (games whose anti-cheat refuses Linux).
Results are cached for a week in CodeAque's data folder; nothing is sent except the game's Steam number. Never raises."""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path
from typing import Callable

SUMMARY_URL = "https://www.protondb.com/api/v1/reports/summaries/{appid}.json"
ANTICHEAT_URL = "https://raw.githubusercontent.com/AreWeAntiCheatYet/AreWeAntiCheatYet/HEAD/games.json"
WEEK = 7 * 24 * 3600

GREAT, SHOULD, MAYNOT, WINDOWS = "Works great", "Should work", "May not work", "Won't run on Linux, needs Windows"
TIER = {"native": GREAT, "platinum": GREAT, "gold": GREAT, "silver": SHOULD, "bronze": MAYNOT, "borked": MAYNOT, "pending": ""}

# known kernel anti-cheat games that refuse Linux (used when the online list cannot be read)
ANTICHEAT_FALLBACK = {"578080": "PUBG: BATTLEGROUNDS", "1172470": "Apex Legends", "359550": "Rainbow Six Siege",
                      "2357570": "Overwatch", "1085660": "Destiny 2", "1938090": "Call of Duty", "230410": "Warframe?"}
ANTICHEAT_FALLBACK.pop("230410")          # Warframe runs - kept out on purpose


def badge_for(tier: str) -> str:
    return TIER.get((tier or "").lower(), "")


def _get(url: str, timeout: float = 15) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "CodeAque"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def parse_anticheat(data) -> set[str]:
    """Steam app ids whose status is Denied or Broken."""
    out = set()
    for g in data if isinstance(data, list) else []:
        st = str(g.get("status", "")).lower()
        sid = str((g.get("storeIds") or {}).get("steam", "") or "")
        if sid and st in ("denied", "broken"):
            out.add(sid)
    return out


class Badges:
    def __init__(self, cache: Path, fetch: Callable[[str], bytes] = _get, now: Callable[[], float] = time.time):
        self.cache, self.fetch, self.now = Path(cache), fetch, now
        try:
            self.data = json.loads(self.cache.read_text())
        except (OSError, ValueError):
            self.data = {}
        self.data.setdefault("tiers", {})
        self.data.setdefault("anticheat", {"ids": sorted(ANTICHEAT_FALLBACK), "at": 0})

    def save(self) -> None:
        try:
            self.cache.parent.mkdir(parents=True, exist_ok=True)
            self.cache.write_text(json.dumps(self.data))
        except OSError:
            pass

    def anticheat_ids(self) -> set[str]:
        ac = self.data["anticheat"]
        if not ac.get("at") or self.now() - ac["at"] > WEEK:
            try:
                ids = parse_anticheat(json.loads(self.fetch(ANTICHEAT_URL)))
                if ids:
                    self.data["anticheat"] = {"ids": sorted(ids | set(ANTICHEAT_FALLBACK)), "at": self.now()}
            except Exception:
                self.data["anticheat"]["at"] = self.now() - WEEK + 3600     # try again in an hour
        return set(self.data["anticheat"]["ids"])

    def tier(self, appid: str) -> str:
        t = self.data["tiers"].get(appid)
        if t and self.now() - t.get("at", 0) < WEEK:
            return t.get("tier", "")
        try:
            tier = json.loads(self.fetch(SUMMARY_URL.format(appid=appid))).get("tier", "")
        except Exception:
            return t.get("tier", "") if t else ""
        self.data["tiers"][appid] = {"tier": tier, "at": self.now()}
        return tier

    def badges(self, appids: list[str]) -> dict[str, str]:
        ac = self.anticheat_ids()
        out = {}
        for a in appids:
            out[a] = WINDOWS if a in ac else badge_for(self.tier(a))
        self.save()
        return out
