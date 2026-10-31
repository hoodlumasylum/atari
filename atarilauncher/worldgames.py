"""World Games: your games from Japan, China and Korea (by the region tag in the file name, e.g. "(Japan)", "(J)", "(NTSC-J)",
"(China)", "(Korea)") and a short, hand-checked list of LEGALLY free games from each region with the official store page.
The free list only names games that their makers give away (free-to-play on Steam, checked on store.steampowered.com on
31 Oct 2026); no ROM / ISO sites, no abandonware, no art. Descriptions are CodeAque's own words. Never raises."""
from __future__ import annotations

import re
from dataclasses import dataclass

REGIONS = (("jp", "Japan"), ("cn", "China"), ("kr", "Korea"))
_TAGS = {
    "jp": re.compile(r"[\(\[](japan|jp|jpn|j|ntsc-j|ja)[\)\],]|[\(\[][^\)\]]*\bjapan\b[^\)\]]*[\)\]]", re.I),
    "cn": re.compile(r"[\(\[](china|cn|chn|ch|chinese|zh)[\)\],]|[\(\[][^\)\]]*\b(china|chinese)\b[^\)\]]*[\)\]]", re.I),
    "kr": re.compile(r"[\(\[](korea|kr|kor|k|ko)[\)\],]|[\(\[][^\)\]]*\bkorea\b[^\)\]]*[\)\]]", re.I),
}


def region_of(name: str) -> str:
    """'jp' | 'cn' | 'kr' | '' from a title or file name."""
    for rid, rx in _TAGS.items():
        if rx.search(name or ""):
            return rid
    return ""


@dataclass(frozen=True)
class FreeGame:
    region: str
    title: str
    year: int
    system: str
    about: str
    url: str
    steam_appid: str = ""
    note: str = ""


ANTICHEAT = "Uses a kernel anti-cheat - it may refuse to run on Linux."
FREE: list[FreeGame] = [
    FreeGame("jp", "Yume Nikki", 2004, "PC (Steam)", "A quiet, strange walk through a girl's dreams - no fights, just exploring and collecting "
             "odd effects. One of Japan's best-known free indie games.", "https://store.steampowered.com/app/650700/Yume_Nikki/", "650700"),
    FreeGame("cn", "NARAKA: BLADEPOINT", 2021, "PC (Steam)", "A melee battle royale with grappling hooks and martial-arts combos, from "
             "a Chinese studio. Free to play.", "https://store.steampowered.com/app/1203220/NARAKA_BLADEPOINT/", "1203220"),
    FreeGame("cn", "Marvel Rivals", 2024, "PC (Steam)", "A team hero shooter from NetEase in China. Free to play.",
             "https://store.steampowered.com/app/2767030/Marvel_Rivals/", "2767030",
             "On Linux it may need the Steam launch option SteamDeck=1 %command%."),
    FreeGame("kr", "MapleStory", 2003, "PC (Steam)", "A long-running 2D side-scrolling online RPG from Korea, with dozens of classes. "
             "Free to play.", "https://store.steampowered.com/app/216150/MapleStory/", "216150", ANTICHEAT),
    FreeGame("kr", "Lost Ark", 2019, "PC (Steam)", "A top-down action RPG from Korean studio Smilegate. Free to play.",
             "https://store.steampowered.com/app/1599340/Lost_Ark/", "1599340", ANTICHEAT),
    FreeGame("kr", "Eternal Return", 2020, "PC (Steam)", "A top-down battle royale with crafting and hunting, from Korean studio "
             "Nimble Neuron. Free to play.", "https://store.steampowered.com/app/1049590/Eternal_Return/", "1049590"),
]
SOURCES = [g.url for g in FREE]


def free_for(region: str) -> list[FreeGame]:
    return [g for g in FREE if g.region == region]
