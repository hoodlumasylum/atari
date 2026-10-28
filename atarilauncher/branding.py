"""Keeps the places outside the app folder in step with the name "CodeAque" after an in-app update (install.sh does the same on a fresh install).

Only things CodeAque made itself are touched: the `codeaque` command (a link to this copy's run.sh, added only when the `atari` link already
points to it), the menu entry / autostart entry whose Exec line is this copy's run.sh (its Name= line only), and the icon files under the
name atari-launcher. Everything is idempotent; nothing is ever removed; the old names (`atari`, `code`, `code-launcher`, atari.desktop,
~/.config/atari ...) keep working."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

NAME = "CodeAque"
LOGO = "codeaque-logo.png"
ICON = "codeaque-icon.png"
TAGLINE = "a console-style game launcher for your living-room PC"


def app_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def logo_file() -> Path:
    return Path(__file__).resolve().parent / "assets" / LOGO


def _points_to(link: Path, target: Path) -> bool:
    try:
        return link.is_symlink() and os.path.realpath(link) == os.path.realpath(target)
    except OSError:
        return False


def refresh(home: Path | None = None, root: Path | None = None) -> list[str]:
    """Returns what was changed (plain words). Never raises."""
    done: list[str] = []
    try:
        home = Path(home) if home is not None else Path.home()
        root = Path(root) if root is not None else app_dir()
        run = root / "run.sh"
        if not run.is_file():
            return done
        data_home = Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share")
        bin_dir = home / ".local" / "bin"
        atari, cmd = bin_dir / "atari", bin_dir / "codeaque"
        if _points_to(atari, run) and not cmd.exists() and not cmd.is_symlink():
            cmd.symlink_to(run)
            done.append("the codeaque command")
        for entry in (data_home / "applications" / "atari.desktop", home / ".config" / "autostart" / "atari.desktop"):
            if not entry.is_file():
                continue
            text = entry.read_text(encoding="utf-8")
            if f"Exec={run}" not in text and f"Exec=\"{run}\"" not in text:
                continue                                     # somebody else's entry (or another copy): leave it
            lines = text.splitlines(keepends=True)
            new = [("Name=" + NAME + "\n") if ln.rstrip("\n") == "Name=Code" else ln for ln in lines]
            if new != lines:
                entry.write_text("".join(new), encoding="utf-8")
                done.append(entry.name)
        pk = root / "packaging"
        pairs = [(pk / "atari-launcher.svg", data_home / "icons" / "hicolor" / "scalable" / "apps" / "atari-launcher.svg")]
        pairs += [(pk / "icons" / f"code-{n}.png", data_home / "icons" / "hicolor" / f"{n}x{n}" / "apps" / "atari-launcher.png")
                  for n in (512, 256, 128, 64)]
        for src, dst in pairs:
            if src.is_file() and dst.is_file() and dst.read_bytes() != src.read_bytes():     # only icons that are already there (ours)
                shutil.copyfile(src, dst)
                done.append("icon " + dst.parent.parent.name)
    except Exception as exc:  # pragma: no cover - a cosmetic refresh must never stop the app
        print(f"[atari] branding refresh failed: {exc}")
    return done
