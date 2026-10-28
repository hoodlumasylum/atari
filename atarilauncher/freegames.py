"""Free Games: a small hand-checked list of free-to-play games that really run on Linux.

Each entry opens through Steam (steam://install/<id> or steam://rungameid/<id>) or, for open-source games, through a Flatpak.
CodeAque downloads nothing by itself; Steam / Flatpak do it after you press Play.

"Works on Linux" badges (checked on 2026-10-28):
  Verified - runs well: a native Linux build, or ProtonDB tier gold/platinum with hundreds of reports.
  Playable - runs, but may need tweaks (ProtonDB silver/bronze).
  Unknown  - not checked.
Games whose anti-cheat blocks Linux (Fortnite, Call of Duty / Warzone, Apex Legends, Destiny 2, Rainbow Six Siege, PUBG ...)
are NOT listed as games. Two plain "does not work on Linux" notes explain it instead.
"""
from __future__ import annotations

from dataclasses import dataclass

FREE = "free"
FREE_NAME = "Free Games"
CHECKED = "2026-10-28"
VERIFIED, PLAYABLE, UNKNOWN, BLOCKED = "Verified", "Playable", "Unknown", "Does not work"


@dataclass(frozen=True)
class FreeGame:
    id: str
    title: str
    kind: str             # steam | flatpak | info
    ref: str              # Steam app id | Flatpak id | ""
    works: str            # Verified | Playable | Unknown | Does not work
    why: str              # the evidence, in one line
    genre: str = ""

    @property
    def gid(self) -> str:
        return f"free:{self.id}"

    @property
    def badge(self) -> str:
        return f"Works on Linux: {self.works}" if self.works != BLOCKED else "Does NOT work on Linux"


def _pdb(tier: str, n: int, native: bool = False) -> str:
    return (("Native Linux build; " if native else "Runs with Proton; ") + f"ProtonDB: {tier} ({n} reports, checked {CHECKED}).")


GAMES: list[FreeGame] = [
    FreeGame("cs2", "Counter-Strike 2", "steam", "730", VERIFIED, _pdb("gold", 2067, True), "Shooter"),
    FreeGame("dota2", "Dota 2", "steam", "570", VERIFIED, _pdb("gold", 359, True), "Strategy"),
    FreeGame("tf2", "Team Fortress 2", "steam", "440", VERIFIED, _pdb("gold", 700, True), "Shooter"),
    FreeGame("poe", "Path of Exile", "steam", "238960", VERIFIED, _pdb("gold", 1201), "Action RPG"),
    FreeGame("warframe", "Warframe", "steam", "230410", VERIFIED, _pdb("gold", 1648), "Action"),
    FreeGame("rivals", "Marvel Rivals", "steam", "2767030", VERIFIED, _pdb("gold", 1651), "Shooter"),
    FreeGame("finals", "THE FINALS", "steam", "2073850", VERIFIED, _pdb("gold", 1696), "Shooter"),
    FreeGame("brawlhalla", "Brawlhalla", "steam", "291550", VERIFIED, _pdb("gold", 653), "Fighting"),
    FreeGame("supertuxkart", "SuperTuxKart", "flatpak", "net.supertuxkart.SuperTuxKart", VERIFIED,
             "Open-source kart racer, native Linux (Flathub).", "Racing"),
    FreeGame("0ad", "0 A.D.", "flatpak", "com.play0ad.zeroad", VERIFIED,
             "Open-source ancient-warfare strategy, native Linux (Flathub).", "Strategy"),
    FreeGame("xonotic", "Xonotic", "flatpak", "org.xonotic.Xonotic", VERIFIED,
             "Open-source arena shooter, native Linux (Flathub).", "Shooter"),
    FreeGame("openarena", "OpenArena", "flatpak", "io.github.ec_.Quake3e.OpenArena", VERIFIED,
             "Open-source arena shooter, native Linux (Flathub).", "Shooter"),
    FreeGame("luanti", "Luanti (Minetest)", "flatpak", "org.luanti.luanti", VERIFIED,
             "Open-source block-building sandbox, native Linux (Flathub).", "Sandbox"),
    FreeGame("wesnoth", "Battle for Wesnoth", "flatpak", "org.wesnoth.Wesnoth", VERIFIED,
             "Open-source turn-based strategy, native Linux (Flathub).", "Strategy"),
    FreeGame("wz2100", "Warzone 2100", "flatpak", "net.wz2100.wz2100", VERIFIED,
             "Open-source real-time strategy, native Linux (Flathub).", "Strategy"),
    FreeGame("openttd", "OpenTTD", "flatpak", "org.openttd.OpenTTD", VERIFIED,
             "Open-source transport tycoon (needs no original files since 2021), native Linux (Flathub).", "Simulation"),
    FreeGame("armagetron", "Armagetron Advanced", "flatpak", "org.armagetronad.ArmagetronAdvanced", VERIFIED,
             "Open-source light-cycle arena game, native Linux (Flathub).", "Arcade"),
    FreeGame("fortnite", "Fortnite - does not work on Linux", "info", "", BLOCKED,
             "Epic's anti-cheat (Easy Anti-Cheat) blocks Linux and Epic does not support it. Nothing here can change that."),
    FreeGame("cod", "Call of Duty / Warzone - does not work on Linux", "info", "", BLOCKED,
             "Activision's anti-cheat (Ricochet) blocks Linux and Activision does not support it. Nothing here can change that."),
]
BY_ID = {g.id: g for g in GAMES}

# Other free-to-play games that were looked at and left out on purpose (anti-cheat or ProtonDB "borked"/weak on 2026-10-28):
LEFT_OUT = ("Apex Legends (silver, Easy Anti-Cheat blocks Linux), Destiny 2 (borked), Rainbow Six Siege (borked), PUBG (borked), "
            "Rocket League (no longer on Steam; the Epic version was not verified)")
MINECRAFT_NOTE = ("Minecraft (Java) works through Prism Launcher in PC Apps - you need your own Minecraft licence. "
                  "CodeAque does not include or download Minecraft.")


def steam_command_for(game: FreeGame, installed: bool) -> str:
    """The steam:// link: play if it is installed, otherwise open Steam's install dialog."""
    return ("steam://rungameid/" if installed else "steam://install/") + game.ref
