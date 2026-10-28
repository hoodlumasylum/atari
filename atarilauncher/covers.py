"""Automatic cover art: box art for ROM games from the public libretro thumbnails server, and Steam's own
library images (local Steam cache first, then Steam's public CDN) for Steam games.

Pure Python + urllib (no Qt, no API key). Runs in a background thread; every network call has a timeout,
retries a few times and waits politely between requests. Nothing here ever raises into the UI: the worst
case is "Offline" or "no cover found".

Pictures are cached in ~/.local/share/atari/covers/ :
    <system id>/<rom file name without extension>.png     (ROM games - the same place you can put your own art)
    steam/<appid>_cover.jpg  and  steam/<appid>_header.jpg   (Steam games)
Your own pictures always win: a game that already has a cover is never touched.
"""
from __future__ import annotations

import difflib
import html
import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import paths

THUMBS_URL = "https://thumbnails.libretro.com"
STEAM_URL = "https://cdn.cloudflare.steamstatic.com/steam/apps"
USER_AGENT = "Atari-Launcher/0.3.0 (+https://github.com/hoodlumasylum/atari; personal game launcher)"
MISS_DAYS = 14          # a game with no cover is not asked for again for this long ("Download covers" forces it)
INDEX_DAYS = 14         # how long a downloaded directory listing of a system is reused
MAX_IMAGE_BYTES = 12 * 1024 * 1024

# --------------------------------------------------------------------------- libretro naming
# Folder names on https://thumbnails.libretro.com/ for each Atari system id (first entry is tried first).
LIBRETRO_SYSTEMS: dict[str, tuple] = {
    "atari2600": ("Atari - 2600",), "atari5200": ("Atari - 5200",), "atari7800": ("Atari - 7800",),
    "atarilynx": ("Atari - Lynx",), "atarijaguar": ("Atari - Jaguar",),
    "nes": ("Nintendo - Nintendo Entertainment System", "Nintendo - Family Computer Disk System"),
    "snes": ("Nintendo - Super Nintendo Entertainment System",),
    "n64": ("Nintendo - Nintendo 64",),
    "gb": ("Nintendo - Game Boy", "Nintendo - Game Boy Color"),
    "gba": ("Nintendo - Game Boy Advance",),
    "nds": ("Nintendo - Nintendo DS", "Nintendo - Nintendo DSi"),
    "n3ds": ("Nintendo - Nintendo 3DS",),
    "gamecube": ("Nintendo - GameCube",), "wii": ("Nintendo - Wii",), "wiiu": ("Nintendo - Wii U",),
    "genesis": ("Sega - Mega Drive - Genesis", "Sega - 32X"),
    "mastersystem": ("Sega - Master System - Mark III",), "gamegear": ("Sega - Game Gear",),
    "segacd": ("Sega - Mega-CD - Sega CD",), "saturn": ("Sega - Saturn",), "dreamcast": ("Sega - Dreamcast",),
    "pce": ("NEC - PC Engine - TurboGrafx 16", "NEC - PC Engine CD - TurboGrafx-CD", "NEC - PC Engine SuperGrafx"),
    "neogeo": ("SNK - Neo Geo", "SNK - Neo Geo CD"),
    "arcade": ("MAME", "FBNeo - Arcade Games"),
    "ps1": ("Sony - PlayStation",), "ps2": ("Sony - PlayStation 2",), "ps3": ("Sony - PlayStation 3",),
    "psp": ("Sony - PlayStation Portable",), "xbox": ("Microsoft - Xbox",),
    "dos": ("DOS",), "scummvm": ("ScummVM",), "amiga": ("Commodore - Amiga", "Commodore - CD32"),
    "c64": ("Commodore - 64",), "msx": ("Microsoft - MSX", "Microsoft - MSX2"),
    "zxspectrum": ("Sinclair - ZX Spectrum",), "amstradcpc": ("Amstrad - CPC",),
    "wonderswan": ("Bandai - WonderSwan", "Bandai - WonderSwan Color"),
    "ngp": ("SNK - Neo Geo Pocket", "SNK - Neo Geo Pocket Color"),
    "vb": ("Nintendo - Virtual Boy",), "3do": ("The 3DO Company - 3DO",),
}

_ILLEGAL = re.compile(r"[&*/:`<>?\\|]")
_TAG = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]")
_REGION_WORDS = ("usa", "europe", "japan", "world", "australia", "korea", "china", "germany", "france", "spain",
                 "italy", "brazil", "asia", "canada", "sweden", "netherlands", "russia", "taiwan", "hong kong")
_BAD_TAGS = ("beta", "proto", "demo", "sample", "unl", "pirate", "hack", "bootleg", "alt", "kiosk", "promo",
             "translated", "aftermarket", "program", "debug", "possible", "test")


def sanitize(name: str) -> str:
    """libretro file names: the characters  & * / : ` < > ? \\ |  become an underscore."""
    return _ILLEGAL.sub("_", name)


def base_title(stem: str) -> str:
    """'Super_Game, The (USA) (Rev 1) [!]' -> 'Super Game, The'  (all (...) and [...] tags removed)."""
    s = stem.replace("_", " ")
    s = _TAG.sub("", s)
    s = re.sub(r"\s+", " ", s).strip(" -")
    return s or stem


def _the_flip(title: str) -> str:
    """'Legend of Zelda, The' <-> 'The Legend of Zelda'."""
    m = re.match(r"^(.*?),\s*(The|A|An)$", title, flags=re.I)
    if m:
        return f"{m.group(2)} {m.group(1)}"
    m = re.match(r"^(The|A|An)\s+(.*)$", title, flags=re.I)
    if m:
        return f"{m.group(2)}, {m.group(1)}"
    return title


def normalize(title: str) -> str:
    """Key used to compare names: lower case letters and digits only, ', The' moved to the front, '&' = 'and'."""
    t = base_title(title).lower().replace("&", " and ")
    m = re.match(r"^(.*?),\s*(the|a|an)$", t)
    if m:
        t = f"{m.group(2)} {m.group(1)}"
    return re.sub(r"[^a-z0-9]", "", t)


def regions_in(stem: str) -> list[str]:
    tags = re.findall(r"[\(\[]([^\)\]]*)[\)\]]", stem)
    out = []
    for t in tags:
        for part in re.split(r"[,/]", t):
            p = part.strip().lower()
            if p in _REGION_WORDS:
                out.append(p)
    return out


def name_variants(stem: str, guess_regions: bool = True) -> list[str]:
    """File names (without .png) worth trying directly, best guess first. All are already sanitised."""
    stem = stem.strip()
    base = base_title(stem)
    cands = [stem, stem.replace("_", " "), base]
    for flip in {_the_flip(base)}:
        cands.append(flip)
    regs = regions_in(stem)
    order = []
    if not guess_regions:
        regs = []
    for r in regs + ["usa", "europe", "world", "japan"]:
        if r not in order:
            order.append(r)
    for r in (order[:4] if guess_regions else []):
        label = {"usa": "USA", "europe": "Europe", "japan": "Japan", "world": "World"}.get(r, r.title())
        cands.append(f"{base} ({label})")
    if " - " in base:
        cands.append(base.replace(" - ", ": ").strip())
    out: list[str] = []
    for c in cands:
        c = sanitize(c.strip())
        if c and c not in out:
            out.append(c)
    return out


def _score(candidate: str, rom_stem: str) -> tuple:
    """Lower = better when several libretro names match the same game."""
    cl = candidate.lower()
    want = regions_in(rom_stem)
    cand_regs = regions_in(candidate)
    region_rank = 9
    for i, r in enumerate(want + ["usa", "world", "europe", "japan"]):
        if r in cand_regs:
            region_rank = i if r in want else 10 + i
            break
    bad = sum(1 for t in _BAD_TAGS if f"({t}" in cl or f"[{t}" in cl)
    exact = 0 if candidate.lower() == sanitize(rom_stem).lower() else 1
    return (exact, bad, region_rank, len(candidate))


class Index:
    """The list of picture names of one libretro system folder, with matching."""

    def __init__(self, names: list[str]):
        self.names = names
        self.by_exact = {n.lower(): n for n in names}
        self.by_key: dict[str, list[str]] = {}
        for n in names:
            self.by_key.setdefault(normalize(n), []).append(n)
        self._keys = None

    def match(self, rom_stem: str) -> str:
        """Best matching libretro name (no .png) for a ROM file name, '' if none."""
        for v in name_variants(rom_stem, guess_regions=False):
            hit = self.by_exact.get(v.lower())
            if hit:
                return hit
        key = normalize(rom_stem)
        hits = self.by_key.get(key)
        if not hits:
            base = base_title(rom_stem)
            for alt in (base.split(" - ")[0], base.split(": ")[0]):
                if alt and alt != base and len(alt) > 6:
                    hits = self.by_key.get(normalize(alt))
                    if hits:
                        break
        if not hits and len(key) >= 8:
            if self._keys is None:
                self._keys = list(self.by_key)
            close = difflib.get_close_matches(key, self._keys, n=1, cutoff=0.93)
            if close:
                hits = self.by_key[close[0]]
        if not hits:
            return ""
        return sorted(hits, key=lambda n: _score(n, rom_stem))[0]


def parse_listing(page: str) -> list[str]:
    """Names (without .png) from an Apache 'Index of ...' page."""
    out = []
    for href in re.findall(r'href="([^"?]+\.png)"', page, flags=re.I):
        name = html.unescape(urllib.parse.unquote(href))
        if "/" in name:
            continue
        out.append(name[:-4])
    return out


# --------------------------------------------------------------------------- network
class Offline(Exception):
    """The internet (or the server) could not be reached."""


class Cancelled(Exception):
    pass


class Http:
    """Tiny polite HTTP client: timeout, retries with back-off, a pause between requests, cancel."""

    def __init__(self, timeout: float = 15.0, retries: int = 3, pause: float = 0.25, backoff: float = 1.0,
                 cancel: threading.Event | None = None, user_agent: str = USER_AGENT):
        self.timeout, self.retries, self.pause, self.backoff = timeout, retries, pause, backoff
        self.cancel = cancel or threading.Event()
        self.ua = user_agent
        self._last = 0.0
        self.requests = 0

    def _wait(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self.cancel.is_set():
                raise Cancelled()
            time.sleep(min(0.05, max(0.0, end - time.monotonic())))

    def get(self, url: str, max_bytes: int = MAX_IMAGE_BYTES, timeout: float | None = None) -> bytes | None:
        """The body of url; None for 404/403/410 (not there); Offline if it cannot be reached after retries."""
        last_err: Exception | None = None
        for attempt in range(self.retries):
            if self.cancel.is_set():
                raise Cancelled()
            gap = self.pause - (time.monotonic() - self._last)
            if gap > 0:
                self._wait(gap)
            self._last = time.monotonic()
            self.requests += 1
            req = urllib.request.Request(url, headers={"User-Agent": self.ua, "Accept": "*/*"})
            retry_after = 0.0
            try:
                with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                    chunks, size = [], 0
                    while True:
                        buf = resp.read(64 * 1024)
                        if not buf:
                            break
                        size += len(buf)
                        if size > max_bytes:
                            return None
                        chunks.append(buf)
                        if self.cancel.is_set():
                            raise Cancelled()
                    return b"".join(chunks)
            except urllib.error.HTTPError as exc:
                if exc.code in (404, 403, 410):
                    return None
                last_err = exc
                if exc.code in (429, 503):
                    try:
                        retry_after = min(10.0, float(exc.headers.get("Retry-After", "0") or 0))
                    except ValueError:
                        retry_after = 0.0
            except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as exc:
                last_err = exc
            except ValueError as exc:  # bad URL
                raise Offline(str(exc))
            if attempt + 1 < self.retries:
                self._wait(max(retry_after, self.backoff * (2 ** attempt)))
        raise Offline(f"{url}: {last_err}")


def looks_like_image(data: bytes) -> bool:
    return data[:8] == b"\x89PNG\r\n\x1a\n" or data[:3] == b"\xff\xd8\xff" or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, path)


# --------------------------------------------------------------------------- jobs
@dataclass
class Job:
    gid: str
    kind: str            # "rom" | "steam-cover" | "steam-header"
    system: str          # system id or "steam"
    title: str
    stem: str            # rom file name without extension, or the Steam appid
    dest: Path = None    # where the picture goes

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.system}:{self.stem}"


def steam_art_path(appid: str, kind: str = "cover", root: Path | None = None) -> Path:
    return (root or paths.user_covers_dir()) / "steam" / f"{appid}_{kind}.jpg"


def find_downloaded_steam_art(appid: str, kind: str = "cover", root: Path | None = None) -> str:
    p = steam_art_path(appid, kind, root)
    return str(p) if p.is_file() else ""


def jobs_for_games(games, covers_root: Path | None = None) -> list[Job]:
    """What is still missing: ROM games without a cover, Steam games without a cover / header."""
    root = covers_root or paths.user_covers_dir()
    out: list[Job] = []
    for g in games:
        if g.platform == "steam" or (g.platform == "free" and g.steam_appid):
            if not g.steam_appid:
                continue
            if not g.cover:
                out.append(Job(g.gid, "steam-cover", "steam", g.title, g.steam_appid,
                               steam_art_path(g.steam_appid, "cover", root)))
            if not g.header:
                out.append(Job(g.gid, "steam-header", "steam", g.title, g.steam_appid,
                               steam_art_path(g.steam_appid, "header", root)))
        elif g.rom_path and not g.cover and g.platform in LIBRETRO_SYSTEMS:
            stem = Path(g.rom_path).stem
            if g.platform == "ps3" or not stem:
                stem = g.title or stem
            safe = re.sub(r'[\\/:*?"<>|]', "_", stem)
            out.append(Job(g.gid, "rom", g.platform, g.title, stem, root / g.platform / f"{safe}.png"))
    return out


@dataclass
class Report:
    total: int = 0
    done: int = 0
    got: int = 0
    missing: int = 0
    failed: int = 0
    offline: bool = False
    cancelled: bool = False

    def text(self) -> str:
        if self.offline:
            extra = f" Got {self.got} before the connection dropped." if self.got else ""
            return "Offline - covers will be tried again next time." + extra
        if self.cancelled:
            return f"Stopped. Downloaded {self.got} cover{'s' if self.got != 1 else ''}."
        if self.total == 0:
            return "All games already have a cover."
        bits = [f"Downloaded {self.got} cover{'s' if self.got != 1 else ''}"]
        if self.missing:
            bits.append(f"{self.missing} not found online")
        if self.failed:
            bits.append(f"{self.failed} failed (will retry)")
        return ", ".join(bits) + "."


class CoverDownloader:
    """Downloads missing covers. Create one per run; call run() from a background thread."""

    def __init__(self, thumbs_url: str = THUMBS_URL, steam_url: str = STEAM_URL, cache_dir: Path | None = None,
                 http: Http | None = None, force: bool = False, now: Callable[[], float] = time.time):
        self.thumbs = thumbs_url.rstrip("/")
        self.steam = steam_url.rstrip("/")
        self.cache = cache_dir or (paths.user_covers_dir() / ".cache")
        self.http = http or Http()
        self.force = force
        self.now = now
        self._misses = self._load_json(self.cache / "misses.json")
        self._indexes: dict[str, Index | None] = {}

    # -- small json caches
    @staticmethod
    def _load_json(path: Path) -> dict:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_misses(self) -> None:
        try:
            self.cache.mkdir(parents=True, exist_ok=True)
            tmp = self.cache / "misses.json.tmp"
            tmp.write_text(json.dumps(self._misses), encoding="utf-8")
            os.replace(tmp, self.cache / "misses.json")
        except OSError:
            pass

    def _recent_miss(self, key: str) -> bool:
        if self.force:
            return False
        ts = self._misses.get(key)
        return isinstance(ts, (int, float)) and self.now() - ts < MISS_DAYS * 86400

    # -- libretro directory listing (one request per system, cached on disk)
    def index_for(self, folder: str) -> Index | None:
        if folder in self._indexes:
            return self._indexes[folder]
        slug = re.sub(r"[^A-Za-z0-9]+", "_", folder).strip("_")
        cache_file = self.cache / "index" / f"{slug}.json"
        data = self._load_json(cache_file)
        names = data.get("names") if isinstance(data.get("names"), list) else None
        fresh = names is not None and self.now() - float(data.get("fetched", 0) or 0) < INDEX_DAYS * 86400
        if not fresh:
            url = f"{self.thumbs}/{urllib.parse.quote(folder)}/Named_Boxarts/"
            body = self.http.get(url, max_bytes=40 * 1024 * 1024, timeout=60)
            if body is not None:
                got = parse_listing(body.decode("utf-8", "replace"))
                if got:
                    names = got
                    try:
                        cache_file.parent.mkdir(parents=True, exist_ok=True)
                        cache_file.write_text(json.dumps({"fetched": self.now(), "names": got}), encoding="utf-8")
                    except OSError:
                        pass
        idx = Index(names) if names else None
        self._indexes[folder] = idx
        return idx

    def _thumb_url(self, folder: str, name: str) -> str:
        return (f"{self.thumbs}/{urllib.parse.quote(folder)}/Named_Boxarts/"
                f"{urllib.parse.quote(sanitize(name) + '.png', safe='()!' + chr(39))}")

    # -- one job
    def _fetch_rom(self, job: Job) -> bool:
        folders = LIBRETRO_SYSTEMS.get(job.system, ())
        stems = [job.stem] + ([job.title] if job.title and job.title != job.stem else [])
        for folder in folders:
            idx = None
            try:
                idx = self.index_for(folder)
            except Offline:
                raise
            if idx is not None:
                for stem in stems:
                    hit = idx.match(stem)
                    if hit:
                        data = self.http.get(self._thumb_url(folder, hit))
                        if data and looks_like_image(data):
                            _write_atomic(job.dest, data)
                            return True
            else:  # no listing available: guess the names directly (a few tries only)
                tried = 0
                for stem in stems:
                    for variant in name_variants(stem):
                        if tried >= 6:
                            break
                        tried += 1
                        data = self.http.get(self._thumb_url(folder, variant))
                        if data and looks_like_image(data):
                            _write_atomic(job.dest, data)
                            return True
        return False

    def _fetch_steam(self, job: Job) -> bool:
        appid = job.stem
        if job.kind == "steam-cover":
            names = ("library_600x900.jpg", "header.jpg")   # tall art first, the wide header as a fallback
        else:
            names = ("header.jpg",)
        for name in names:
            data = self.http.get(f"{self.steam}/{appid}/{name}")
            if data and looks_like_image(data):
                _write_atomic(job.dest, data)
                return True
        return False

    def run(self, jobs: list[Job], progress: Callable[[int, int, int], None] | None = None,
            on_cover: Callable[[Job], None] | None = None, cancel: threading.Event | None = None) -> Report:
        """progress(done, total, got); on_cover(job) after each new picture is on disk."""
        if cancel is not None:
            self.http.cancel = cancel
        rep = Report(total=len(jobs))
        todo = []
        for j in jobs:
            if j.dest is not None and j.dest.is_file():  # arrived meanwhile
                rep.done += 1
                continue
            todo.append(j)
        net_fail = 0
        if progress:
            progress(rep.done, rep.total, rep.got)
        for job in todo:
            if self.http.cancel.is_set():
                rep.cancelled = True
                break
            if self._recent_miss(job.key):
                rep.done += 1
                rep.missing += 1
                continue
            try:
                ok = self._fetch_steam(job) if job.kind.startswith("steam") else self._fetch_rom(job)
                net_fail = 0
            except Cancelled:
                rep.cancelled = True
                break
            except Offline:
                net_fail += 1
                rep.failed += 1
                rep.done += 1
                if net_fail >= 2:
                    rep.offline = True
                    break
                continue
            except OSError:
                rep.failed += 1
                rep.done += 1
                continue
            rep.done += 1
            if ok:
                rep.got += 1
                self._misses.pop(job.key, None)
                if on_cover:
                    on_cover(job)
            else:
                rep.missing += 1
                self._misses[job.key] = self.now()
            if progress:
                progress(rep.done, rep.total, rep.got)
        self._save_misses()
        return rep
