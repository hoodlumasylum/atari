"""Streaming & Social: web apps (YouTube, Netflix, Instagram, ...) shown as tiles and started in a full-screen "app" window
of a browser on this PC, each with its own private profile folder so you sign in once per app.

Code uses no company logos: the tiles are plain text/colour tiles. Nothing is downloaded or bundled here.
Order of browsers: Google Chrome, Chromium, Brave, ungoogled-Chromium (as `--app=URL --start-fullscreen`), then Firefox
(`--kiosk`). Netflix, Prime Video and Disney+ need Widevine DRM: Google Chrome has it built in, Firefox downloads it after you
accept its prompt; on Linux those services stream at about 720p (Widevine "L3"), never 4K/HDR.
"""
from __future__ import annotations

import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import emulators, paths

STREAMING = "streaming"
STREAMING_NAME = "Streaming & Social"


@dataclass(frozen=True)
class WebApp:
    id: str
    title: str
    url: str
    drm: bool = False
    note: str = ""
    background: bool = False    # keeps running behind Code (music): Esc twice brings Code back and leaves it playing
    browse: bool = False        # a normal browser window (address bar, back / forward) instead of a full-screen app window
    mic: bool = False           # records with the microphone: the browser is told to allow it (no pop-up a controller cannot answer)
    studio: bool = False        # listed in the Studio area (next to the built-in Studio) instead of Streaming & Social

    @property
    def gid(self) -> str:
        return f"web:{self.id}"


DRM_NOTE = ("Needs Widevine DRM (Google Chrome has it; in Firefox accept its \"Play DRM content\" prompt). "
            "On Linux this streams at about 720p, not 4K.")
WEBAPPS: list[WebApp] = [
    WebApp("browser", "Web Browser", "https://duckduckgo.com/", browse=True,
           note="A normal browser window with an address bar and back / forward buttons, starting at a neutral search engine. "
                "Press Esc twice (or hold Guide + B on a controller) to return to Code. Files you download land in ~/Downloads - "
                "Options > Downloads moves them into your games. Code does not recommend or link any download site."),
    WebApp("twitchlive", "Twitch (go live)", "https://dashboard.twitch.tv/stream-manager", browse=True,
           note="Twitch's Creator Dashboard in a browser window: your stream key is under Settings > Stream. Pair it with OBS (Options > Go Live)."),
    WebApp("tiktoklive", "TikTok LIVE (go live)", "https://www.tiktok.com/live", browse=True,
           note="TikTok's web LIVE page in a browser window. TikTok LIVE Studio is Windows-only, so on Linux you stream with OBS and "
                "the server URL + stream key TikTok shows here (only for accounts that qualify)."),
    WebApp("youtubelive", "YouTube Live (go live)", "https://studio.youtube.com", browse=True,
           note="YouTube Studio in a browser window: Create > Go live > Stream shows your stream key. Pair it with OBS (Options > Go Live)."),
    WebApp("spotify", "Spotify (web player)", "https://open.spotify.com", True, background=True,
           note="Spotify's web player in its own window (sign in once; needs a Spotify account). Music needs Widevine: Google Chrome has it "
                "built in. It keeps playing behind Code - press Esc twice (or Guide + B) to come back and use the music buttons in the "
                "top bar (they need playerctl)."),
    WebApp("bandlab", "BandLab (music studio)", "https://www.bandlab.com/studio", mic=True, studio=True,
           note="BandLab is a free music studio in the browser (record, loops, mixing; no Linux app). It opens in its own window and "
                "remembers your login. The microphone is allowed for recording: pick it in BandLab's own audio settings. Sign in once; "
                "a mouse helps. Press Esc twice (or Guide + B) to come back to Code."),
    WebApp("youtube", "YouTube", "https://www.youtube.com/tv",
           note="The TV layout of YouTube - big buttons, works with arrow keys and Enter. Sign in once."),
    WebApp("netflix", "Netflix", "https://www.netflix.com", True, DRM_NOTE),
    WebApp("disney", "Disney+", "https://www.disneyplus.com", True, DRM_NOTE),
    WebApp("prime", "Prime Video", "https://www.primevideo.com", True, DRM_NOTE),
    WebApp("twitch", "Twitch", "https://www.twitch.tv", note="Live streams. A mouse or touch screen helps."),
    WebApp("instagram", "Instagram", "https://www.instagram.com", note="Made for phones: a mouse or touch screen helps."),
    WebApp("facebook", "Facebook", "https://www.facebook.com", note="A mouse or touch screen helps."),
    WebApp("tiktok", "TikTok", "https://www.tiktok.com", note="A mouse or touch screen helps."),
]
BY_ID = {w.id: w for w in WEBAPPS}


@dataclass(frozen=True)
class Browser:
    id: str
    name: str
    exes: tuple
    flatpak: str
    kind: str             # chromium | firefox
    drm: bool             # plays Netflix & co. without extra steps


BROWSERS: list[Browser] = [
    Browser("chrome", "Google Chrome", ("google-chrome-stable", "google-chrome"), "com.google.Chrome", "chromium", True),
    Browser("chromium", "Chromium", ("chromium", "chromium-browser"), "org.chromium.Chromium", "chromium", False),
    Browser("brave", "Brave", ("brave-browser", "brave"), "com.brave.Browser", "chromium", True),
    Browser("ungoogled", "ungoogled-Chromium", (), "io.github.ungoogled_software.ungoogled_chromium", "chromium", False),
    Browser("firefox", "Firefox", ("firefox",), "org.mozilla.firefox", "firefox", True),
]
HELP_TEXT = ("Streaming apps open in a web browser window. Install one with Settings > Emulators > Install emulators and apps "
             "(it adds Google Chrome), or install Chrome / Chromium / Firefox yourself.")


def profile_root() -> Path:
    return paths.data_dir() / "webapps"


def find_browser(cfg=None, home: Path | None = None, which: Callable = shutil.which,
                 drm: bool = False) -> tuple[Browser | None, str]:
    """(browser, how) with how = 'native' | 'flatpak'. Browsers that handle DRM come first for DRM apps."""
    order = sorted(BROWSERS, key=lambda b: (not b.drm,) if drm else (0,))   # stable: keeps the table order otherwise
    for b in order:
        for exe in b.exes:
            if which(exe):
                return b, "native"
        if emulators.flatpak_installed(b.flatpak, home):
            return b, "flatpak"
    return None, ""


def build_command(cfg, app: WebApp, home: Path | None = None, which: Callable = shutil.which,
                  root: Path | None = None) -> tuple[list[str], str]:
    """(command, browser name). A command in config ([emulators] browser = "...") replaces the browser:
    Code adds --app=<url> --start-fullscreen --user-data-dir=<profile> to it. Returns ([], '') when no browser exists."""
    root = root or profile_root()
    prof = root / app.id
    custom = (cfg.emulator_commands.get("browser") or "").strip() if cfg is not None else ""
    if custom:
        return shlex.split(custom) + (browse_flags(app, prof) if app.browse else chromium_flags(app, prof)), "your browser"
    b, how = find_browser(cfg, home, which, app.drm)
    if b is None:
        return [], ""
    if how == "flatpak":
        base = ["flatpak", "run", f"--filesystem={root}", b.flatpak]
    else:
        base = [next(e for e in b.exes if which(e))]
    if app.browse:
        flags = (browse_flags(app, prof) if b.kind == "chromium" else ["--no-remote", "--profile", str(prof), app.url])
    else:
        flags = chromium_flags(app, prof) if b.kind == "chromium" else [
            "--no-remote", "--profile", str(prof), "--kiosk", app.url]
    return base + flags, b.name


def browse_flags(app: WebApp, prof: Path) -> list[str]:
    """A normal window (toolbar visible), maximised, with its own profile so it never touches your everyday browser."""
    return ["--new-window", "--start-maximized", f"--user-data-dir={prof}", "--no-first-run", "--no-default-browser-check", app.url]


MIC_FLAG = "--use-fake-ui-for-media-stream"       # Chromium: allow microphone / camera requests without the pop-up
FIREFOX_MIC_PREFS = 'user_pref("media.navigator.permission.disabled", true);\n'


def chromium_flags(app: WebApp, prof: Path) -> list[str]:
    return [f"--app={app.url}", "--start-fullscreen", f"--user-data-dir={prof}", "--no-first-run",
            "--no-default-browser-check"] + ([MIC_FLAG] if app.mic else [])


def prepare_profile(app: WebApp, prof: Path) -> None:
    """Firefox reads user.js from the profile: allow the microphone for apps that record. (Chromium gets a flag instead.)"""
    if not app.mic:
        return
    try:
        prof.mkdir(parents=True, exist_ok=True)
        f = prof / "user.js"
        if not f.exists() or FIREFOX_MIC_PREFS not in f.read_text(errors="replace"):
            with open(f, "a", encoding="utf-8") as fh:
                fh.write(FIREFOX_MIC_PREFS)
    except OSError:
        pass


def status(cfg, app: WebApp, home: Path | None = None, which: Callable = shutil.which) -> tuple[bool, str]:
    cmd, name = build_command(cfg, app, home, which)
    if not cmd:
        return False, HELP_TEXT
    b, _ = find_browser(cfg, home, which, app.drm)
    extra = ""
    if app.drm and b is not None and not b.drm:
        extra = f" {b.name} may not play DRM video (Netflix etc.) - Google Chrome does."
    return True, f"Opens in {name}." + extra
