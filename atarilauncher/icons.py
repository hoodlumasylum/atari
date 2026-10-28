"""Icons for app tiles (Streaming & Social, PC Apps, Free Games), fetched at run time - nothing third-party is bundled.

Where a tile's picture comes from, best first:
  1. the app's own installed icon (Flatpak export or the .desktop file's Icon=), already on this computer;
  2. the copy Code downloaded earlier into ~/.local/share/atari/icons/ (one file per tile);
  3. a download, once, when online:
       web apps  -> the site's own icon (apple-touch-icon / <link rel=icon>, then /favicon.ico),
       apps      -> the Flathub store icon of the Flatpak, else the app's website icon,
       free games-> Steam's own art for the game id (Steam CDN), or the Flathub icon of the Flatpak;
  4. nothing found / offline: the tile keeps Code's own original coloured tile with the app's initials (drawn in QML).
Failed lookups are remembered for a few days, then tried again. Downloads use the same polite HTTP client as the covers."""
from __future__ import annotations

import configparser
import json
import os
import re
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import covers, paths

FLATHUB_ICONS = "https://dl.flathub.org/repo/appstream/x86_64/icons/128x128"
MISS_DAYS = 3
# Websites for apps that have no Flatpak icon on Flathub (the icon is the site's own favicon, downloaded on the user's PC)
APP_SITES = {"wine": "https://www.winehq.org", "ffmpeg": "https://ffmpeg.org", "7zip": "https://www.7-zip.org", "unrar": "https://www.rarlab.com",
             "umu": "https://github.com/Open-Wine-Components/umu-launcher", "steam": "https://store.steampowered.com",
             "roblox": "https://www.roblox.com", "chrome": "https://www.google.com/chrome", "kodi": "https://kodi.tv"}
STEAM_FILES = ("library_600x900.jpg", "header.jpg", "capsule_616x353.jpg")
SIZES = ("512x512", "256x256", "192x192", "128x128", "96x96", "64x64", "scalable")
EXTS = ("png", "svg", "jpg", "webp", "ico")


@dataclass(frozen=True)
class Spec:
    gid: str
    title: str
    flatpak: str = ""
    exes: tuple = ()
    site: str = ""
    steam_appid: str = ""
    kind: str = "app"          # web | app | free


def icons_dir(root: Path | None = None) -> Path:
    return root or (paths.data_dir() / "icons")


def spec_for(gid: str) -> Spec | None:
    """The icon recipe for one tile (None for tiles that are not apps: ROMs, Studio, Tools ...)."""
    from . import apps, freegames, webapps
    kind, _, ident = gid.partition(":")
    if kind == "web" and ident in webapps.BY_ID:
        w = webapps.BY_ID[ident]
        return Spec(gid, w.title, site=w.url, kind="web")
    if kind == "app" and ident in apps.BY_ID:
        a = apps.BY_ID[ident]
        return Spec(gid, a.title, flatpak=a.flatpak, exes=tuple(a.exes), site=APP_SITES.get(ident, ""), kind="app")
    if kind == "free":
        fg = freegames.BY_ID.get(ident)
        if fg is not None and fg.kind == "steam":
            return Spec(gid, fg.title, steam_appid=fg.ref, kind="free")
        if fg is not None and fg.kind == "flatpak":
            return Spec(gid, fg.title, flatpak=fg.ref, kind="free")
    return None


# ---------------------------------------------------------------------------------------------- already on this computer
def _hicolor_dirs(home: Path | None) -> list[Path]:
    h = home or Path.home()
    dirs = [h / ".local/share/flatpak/exports/share/icons/hicolor", h / ".local/share/icons/hicolor"]
    if home is None:
        dirs += [Path("/var/lib/flatpak/exports/share/icons/hicolor"), Path("/usr/share/icons/hicolor")]
    return dirs


def _find_theme_icon(name: str, home: Path | None) -> str:
    if name.startswith("/"):
        return name if Path(name).is_file() else ""
    for base in _hicolor_dirs(home):
        for size in SIZES:
            for ext in ("png", "svg"):
                p = base / size / "apps" / f"{name}.{ext}"
                if p.is_file():
                    return str(p)
    if home is None:
        for ext in ("png", "svg", "xpm"):
            p = Path("/usr/share/pixmaps") / f"{name}.{ext}"
            if p.is_file() and ext != "xpm":
                return str(p)
    return ""


def _desktop_dirs(home: Path | None) -> list[Path]:
    h = home or Path.home()
    dirs = [h / ".local/share/applications", h / ".local/share/flatpak/exports/share/applications"]
    if home is None:
        dirs += [Path("/var/lib/flatpak/exports/share/applications"), Path("/usr/share/applications")]
    return dirs


def local_icon(spec: Spec, home: Path | None = None) -> str:
    """Path of the app's own icon if it is installed here ('' if not). Flatpak exports first, then .desktop files."""
    if spec.flatpak:
        got = _find_theme_icon(spec.flatpak, home)
        if got:
            return got
    if spec.exes:
        wanted = {e.lower() for e in spec.exes}
        for d in _desktop_dirs(home):
            try:
                files = sorted(d.glob("*.desktop"))
            except OSError:
                continue
            for f in files:
                stem = f.stem.lower().split(".")[-1]
                try:
                    cp = configparser.ConfigParser(interpolation=None, strict=False)
                    cp.read(f, encoding="utf-8")
                    ent = cp["Desktop Entry"]
                except (configparser.Error, OSError, KeyError, UnicodeDecodeError):
                    continue
                exec_names = {Path(tok).name.lower() for tok in re.split(r"\s+", ent.get("Exec", "")) if tok and not tok.startswith("%")}
                if stem in wanted or wanted & exec_names:
                    got = _find_theme_icon(ent.get("Icon", "").strip(), home) if ent.get("Icon") else ""
                    if got:
                        return got
    return ""


# ---------------------------------------------------------------------------------------------- the download cache
def _safe(gid: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", gid)


def cached(gid: str, root: Path | None = None) -> str:
    base = icons_dir(root)
    for ext in EXTS:
        p = base / f"{_safe(gid)}.{ext}"
        if p.is_file() and p.stat().st_size > 100:
            return str(p)
    return ""


def resolve(spec: Spec, home: Path | None = None, root: Path | None = None) -> tuple[str, bool]:
    """(picture path or '', True when it is an icon that should be shown whole on a coloured tile)."""
    got = local_icon(spec, home)
    if got:
        return got, True
    got = cached(spec.gid, root)
    return got, spec.kind != "free" or not spec.steam_appid


def sniff_ext(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:4] == b"\x00\x00\x01\x00":
        return "ico"
    head = data[:400].lstrip().lower()
    if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in data[:2000].lower()):
        return "svg"
    return ""


def ico_to_png(data: bytes) -> bytes:
    """Qt can turn a .ico into a PNG (if its image plugin is there); otherwise the .ico is kept as it is."""
    try:
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        from PySide6.QtGui import QImage
        img = QImage.fromData(data)
        if img.isNull():
            return b""
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        img.save(buf, "PNG")
        return bytes(ba.data())
    except Exception:
        return b""


_LINK = re.compile(r"<link\b([^>]*)>", re.I | re.S)
_ATTR = re.compile(r'([a-zA-Z-]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\')')


def page_icons(html: str, base: str) -> list[str]:
    """Icon URLs a web page announces, best first (big apple-touch-icons, then big PNGs, svg, small ones)."""
    found: list[tuple[int, str]] = []
    for m in _LINK.finditer(html[:400_000]):
        attrs = {k.lower(): (a or b) for k, a, b in _ATTR.findall(m.group(1))}
        rel = attrs.get("rel", "").lower()
        href = attrs.get("href", "").strip()
        if not href or "icon" not in rel or "mask" in rel:
            continue
        sizes = [int(x) for x in re.findall(r"(\d+)x\d+", attrs.get("sizes", ""))] or [0]
        score = max(sizes) + (1000 if "apple-touch" in rel else 0) + (200 if href.split("?")[0].endswith(".png") else 0)
        if attrs.get("sizes", "").lower() == "any" or href.split("?")[0].endswith(".svg"):
            score += 150
        found.append((score, urllib.parse.urljoin(base, href)))
    found.sort(key=lambda t: -t[0])
    out: list[str] = []
    for _s, u in found:
        if u not in out:
            out.append(u)
    return out


def default_icon_urls(site: str) -> list[str]:
    root = urllib.parse.urljoin(site, "/")
    return [root + "apple-touch-icon.png", root + "apple-touch-icon-precomposed.png", root + "favicon.png", root + "favicon.ico"]


class IconFetcher:
    """Downloads the missing icons (call run() from a background thread)."""

    def __init__(self, http: covers.Http | None = None, root: Path | None = None, flathub_url: str = FLATHUB_ICONS,
                 steam_url: str = covers.STEAM_URL, force: bool = False, now: Callable[[], float] = time.time):
        self.http = http or covers.Http()
        self.root = icons_dir(root)
        self.flathub, self.steam = flathub_url.rstrip("/"), steam_url.rstrip("/")
        self.force, self.now = force, now
        self._misses = self._load()

    def _load(self) -> dict:
        try:
            d = json.loads((self.root / "misses.json").read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            tmp = self.root / "misses.json.tmp"
            tmp.write_text(json.dumps(self._misses), encoding="utf-8")
            os.replace(tmp, self.root / "misses.json")
        except OSError:
            pass

    def missing_misses(self) -> dict:
        return dict(self._misses)

    def _urls(self, spec: Spec):
        """Candidate picture URLs in order; the page lookup is lazy so a Flathub hit costs one request only."""
        if spec.steam_appid:
            for f in STEAM_FILES:
                yield f"{self.steam}/{spec.steam_appid}/{f}"
        if spec.flatpak:
            yield f"{self.flathub}/{urllib.parse.quote(spec.flatpak)}.png"
        if spec.site:
            html = self.http.get(spec.site, max_bytes=1_500_000)
            if html:
                yield from page_icons(html.decode("utf-8", "replace"), spec.site)
            yield from default_icon_urls(spec.site)

    def fetch_one(self, spec: Spec) -> str:
        """Path of the saved icon, or '' (nothing found). May raise covers.Offline / covers.Cancelled.
        A tiny first hit (a 16 px favicon) is replaced by a bigger one if one of the next few candidates is."""
        best: tuple[bytes, str] | None = None
        tries = 0
        for url in self._urls(spec):
            data = self.http.get(url, max_bytes=2_000_000)
            ext = sniff_ext(data) if data else ""
            if not ext or len(data) < 200:
                continue
            if ext == "ico":
                png = ico_to_png(data)
                if png:
                    data, ext = png, "png"
            if best is None or len(data) > len(best[0]):
                best = (data, ext)
            tries += 1
            if len(best[0]) >= 1500 or tries >= 4:
                break
        if best is None:
            return ""
        data, ext = best
        self.root.mkdir(parents=True, exist_ok=True)
        dest = self.root / f"{_safe(spec.gid)}.{ext}"
        for old in self.root.glob(f"{_safe(spec.gid)}.*"):
            if old != dest:
                try:
                    old.unlink()
                except OSError:
                    pass
        covers._write_atomic(dest, data)
        return str(dest)

    def run(self, specs: list[Spec], on_icon: Callable[[Spec, str], None] | None = None, cancel=None,
            home: Path | None = None) -> dict:
        rep = {"got": 0, "missing": 0, "skipped": 0, "offline": False}
        if cancel is not None:
            self.http.cancel = cancel
        net_fail = 0
        for spec in specs:
            if self.http.cancel.is_set():
                break
            if not self.force and (local_icon(spec, home) or cached(spec.gid, self.root)):
                rep["skipped"] += 1
                continue
            ts = self._misses.get(spec.gid)
            if not self.force and isinstance(ts, (int, float)) and self.now() - ts < MISS_DAYS * 86400:
                rep["missing"] += 1
                continue
            try:
                path = self.fetch_one(spec)
                net_fail = 0
            except covers.Cancelled:
                break
            except covers.Offline:
                net_fail += 1
                if net_fail >= 2:
                    rep["offline"] = True
                    break
                continue
            except OSError:
                continue
            if path:
                rep["got"] += 1
                self._misses.pop(spec.gid, None)
                if on_icon:
                    on_icon(spec, path)
            else:
                rep["missing"] += 1
                self._misses[spec.gid] = self.now()
        self._save()
        return rep
