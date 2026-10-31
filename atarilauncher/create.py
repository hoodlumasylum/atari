"""Create: game-making tools. Nothing here is bundled or downloaded by itself.

* Unreal Engine - Epic publishes Linux builds on its own site; they need a free Epic account login there, so CodeAque only links to the
  official page, finds an UnrealEditor you unpacked (common folders, or one you pick) and starts it.
* Roblox Studio - Roblox has no Linux version. CodeAque says so and, only when this computer also has Windows in its boot menu, offers
  "Reboot into Windows" (once, after you confirm: grub-reboot picks Windows for the next start only).
* Godot - free and open source (MIT), runs natively on Linux; installed from Flathub only when you press Install. Never raises."""
from __future__ import annotations

import os
import re
from pathlib import Path

from .apps import AppDef

UNREAL_URL = "https://www.unrealengine.com/en-US/linux"
UNREAL_PREF = "unreal_editor"
UNREAL_NOTE = ("Unreal Engine is big and heavy: about 40 GB or more on disk, 16 GB of RAM or more (32 GB is better) and a strong "
               "graphics card. It is best on the new RTX laptop; on an older computer it may be very slow or not start.")
UNREAL_STEPS = [
    "1. On the Unreal Engine Linux page, sign in with your free Epic Games account (Epic asks for it; CodeAque never sees it).",
    "2. Download the Linux build (a .zip) and unpack it, for example to ~/UnrealEngine or ~/Games/UnrealEngine.",
    "3. Come back here and press Look again (or Choose UnrealEditor... if you put it somewhere else).",
]
ROBLOX_STUDIO_NOTE = ("Roblox Studio has no Linux version - Roblox makes it only for Windows and Mac. To use it, start the computer in "
                      "Windows (if it has Windows) or use a Windows or Mac computer. Playing Roblox works here through the Roblox tile.")
GODOT = AppDef("godot", "Godot Engine (free game maker)", "org.godotengine.Godot", ("godot", "godot4"),
               "Free and open source (MIT licence), made for Linux too. Make 2D and 3D games.", group="create")
APPS = [GODOT]

_EDITOR_REL = ("Engine/Binaries/Linux/UnrealEditor", "Engine/Binaries/Linux/UE4Editor")


def unreal_roots(home: Path | None = None) -> list[Path]:
    home = home or Path.home()
    return [home / "UnrealEngine", home / "Unreal", home / "Games/UnrealEngine", home / "Applications", home / "Downloads",
            home / "opt", Path("/opt"), home / "Epic Games", home]


def find_unreal(home: Path | None = None, custom: str = "", roots: list[Path] | None = None) -> str:
    """Path of an UnrealEditor program, or ''. A file you chose wins if it still exists."""
    if custom and os.path.isfile(custom) and os.access(custom, os.X_OK):
        return custom
    for root in roots or unreal_roots(home):
        if not root.is_dir():
            continue
        cands = [root] + [c for c in _children(root)] + [g for c in _children(root) for g in _children(c)]
        for c in cands:
            for rel in _EDITOR_REL:
                f = c / rel
                if f.is_file():
                    return str(f)
    return ""


def _children(p: Path) -> list[Path]:
    try:
        return [c for c in sorted(p.iterdir()) if c.is_dir() and not c.name.startswith(".")][:60]
    except OSError:
        return []


# ------------------------------------------------------------------ Windows in the boot menu
GRUB_CFGS = ("/boot/grub/grub.cfg", "/boot/grub2/grub.cfg")


def windows_entry(paths=GRUB_CFGS) -> str:
    """The title of the Windows entry in GRUB's menu ('Windows Boot Manager (on /dev/nvme0n1p1)'), or ''."""
    for p in paths:
        try:
            text = Path(p).read_text(errors="replace")
        except OSError:
            continue
        for m in re.finditer(r"^\s*menuentry\s+(['\"])(.*?)\1", text, re.M):
            if "windows" in m.group(2).lower():
                return m.group(2)
    return ""


def reboot_commands(entry: str) -> list[list[str]]:
    """Start Windows once on the next start (grub-reboot), then restart. Run with the administrator password."""
    return [["grub-reboot", entry], ["systemctl", "reboot"]]
