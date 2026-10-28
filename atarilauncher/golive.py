"""Go Live: stream your gameplay with OBS Studio (free, open source), plus the web dashboards of Twitch, YouTube Live and TikTok LIVE.

What CodeAque does: installs OBS (one button), writes ONE ready-made OBS scene collection called "Code Go Live" (a full-screen capture
+ your desktop sound + microphone) if you do not have one yet, and starts OBS with it. You paste your own stream key into OBS
(Settings > Stream). CodeAque never sees, stores or sends a stream key and does not touch your accounts.

Honest limits: OBS' "Game Capture" source is Windows-only. On Linux the scene captures the whole screen (X11: "Screen Capture (XSHM)",
Wayland: "Screen Capture (PipeWire)" - a system window asks you to pick the screen the first time). TikTok's "LIVE Studio" app is
Windows / macOS only; on Linux you stream to TikTok through OBS with the server URL + stream key that TikTok shows on its web LIVE
page - and TikTok only gives those keys to accounts that qualify (its rules change; CodeAque cannot check them for you).
The scene file was written to OBS' documented format but has not been tried with every OBS version.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from . import apps, recorder

COLLECTION = "Code Go Live"
SCENE = "Game"
FLATPAK = "com.obsproject.Studio"

TIKTOK_TEXT = ("TikTok LIVE Studio is a Windows / Mac program, so it does not exist for Linux. On Linux you stream to TikTok with OBS: "
               "open TikTok's LIVE page in the browser (\"TikTok LIVE\" tile), start a LIVE as a \"Go LIVE with a streaming app\" and copy the "
               "server URL and stream key, then paste them into OBS > Settings > Stream (Service: Custom). TikTok only offers the key to "
               "accounts that qualify (age, followers and region rules - they change), so the key may not be there for a new account.")
TWITCH_TEXT = "Twitch: in the Creator Dashboard open Settings > Stream, copy the Primary Stream Key into OBS > Settings > Stream (Service: Twitch)."
YOUTUBE_TEXT = ("YouTube: open YouTube Studio > Create > Go live > Stream, copy the Stream key into OBS (Service: YouTube - RTMPS). "
                "New channels must verify their phone and wait up to 24 hours before live streaming is switched on.")
SECRET_TEXT = "Your stream key is a password: never show it on screen or send it to anyone."


def config_dirs(home: Path | None = None) -> list[Path]:
    h = home or Path.home()
    return [h / ".var/app" / FLATPAK / "config/obs-studio", h / ".config/obs-studio"]


def scenes_dir(use_flatpak: bool, home: Path | None = None) -> Path:
    return config_dirs(home)[0 if use_flatpak else 1] / "basic" / "scenes"


def capture_source(session: str) -> tuple[str, str, dict]:
    """(OBS source id, name, settings) for the screen capture that fits the session type."""
    if session == "wayland":
        return "pipewire-screen-capture-source", "Screen (PipeWire)", {"ShowCursor": True}
    return "xshm_input", "Screen (X11)", {"screen": 0, "show_cursor": True, "advanced": False}


def scene_collection(session: str = "x11") -> dict:
    """An OBS scene collection with one scene: full-screen capture. Desktop sound and microphone are OBS' global audio devices,
    which OBS turns on by itself in a new collection."""
    sid, sname, sset = capture_source(session)
    uid_scene, uid_src = "c0de0000-0000-4000-8000-000000000001", "c0de0000-0000-4000-8000-000000000002"
    return {
        "name": COLLECTION,
        "current_scene": SCENE, "current_program_scene": SCENE,
        "scene_order": [{"name": SCENE}],
        "sources": [
            {"name": SCENE, "uuid": uid_scene, "id": "scene", "versioned_id": "scene", "enabled": True, "muted": False, "volume": 1.0,
             "settings": {"id_counter": 1, "items": [
                 {"name": sname, "source_uuid": uid_src, "id": 1, "visible": True, "locked": False,
                  "pos": {"x": 0.0, "y": 0.0}, "scale": {"x": 1.0, "y": 1.0}, "bounds_type": 2, "bounds": {"x": 1920.0, "y": 1080.0},
                  "bounds_alignment": 0, "align": 5}]}},
            {"name": sname, "uuid": uid_src, "id": sid, "versioned_id": sid, "enabled": True, "muted": False, "volume": 1.0,
             "settings": sset},
        ],
        "groups": [], "quick_transitions": [], "transitions": [], "saved_projectors": [],
        "modules": {}, "preview_locked": False, "scaling_enabled": False,
    }


def find_obs(cfg, home: Path | None = None, which: Callable = shutil.which) -> tuple[list[str], str]:
    """(command, how) like apps.app_command: how is '' when OBS is not installed."""
    return apps.app_command(cfg, apps.BY_ID["obs"], home, which)


def ensure_scene(how: str, home: Path | None = None, session: str | None = None) -> tuple[Path | None, bool]:
    """Write the "Code Go Live" collection unless it exists (never overwrites). Returns (file, newly written)."""
    d = scenes_dir(how == "flatpak", home)
    f = d / (COLLECTION.replace(" ", "_") + ".json")
    if f.exists():
        return f, False
    try:
        d.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(scene_collection(session or recorder.session_type() or "x11"), indent=2), encoding="utf-8")
    except OSError:
        return None, False
    return f, True


def start_obs(cfg, home: Path | None = None, which: Callable = shutil.which, popen=subprocess.Popen,
              session: str | None = None) -> tuple[bool, str]:
    """Open OBS with the Go Live scene. Never raises."""
    cmd, how = find_obs(cfg, home, which)
    if not how:
        return False, apps.install_hint(apps.BY_ID["obs"])
    f, new = ensure_scene(how, home, session)
    args = ["--collection", COLLECTION, "--scene", SCENE, "--disable-shutdown-check"] if f is not None else []
    try:
        popen(cmd + args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        return False, f"Could not start OBS: {exc.strerror or exc}"
    msg = "Opening OBS with the \"Code Go Live\" scene (your whole screen)."
    if f is None:
        msg = "Opening OBS (CodeAque could not write its scene file, so OBS starts the normal way)."
    return True, msg + " Paste your stream key in Settings > Stream, then press Start Streaming. " + SECRET_TEXT
