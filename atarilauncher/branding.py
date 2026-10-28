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


def desktop_folder(home: Path, env: dict | None = None, run=None) -> Path:
    """The user's Desktop folder (xdg-user-dir DESKTOP, else ~/Desktop)."""
    import subprocess
    run = run or subprocess.run
    try:
        r = run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, timeout=5, env=dict(env if env is not None else os.environ, HOME=str(home)))
        out = (r.stdout or "").strip()
        if r.returncode == 0 and out and Path(out).is_absolute() and Path(out) != home:
            return Path(out)
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return home / "Desktop"


def _entry_text(root: Path) -> str | None:
    tpl = root / "packaging" / "atari.desktop.in"
    try:
        return tpl.read_text(encoding="utf-8").replace("@RUN@", str(root / "run.sh"))
    except OSError:
        return None


def _ours(path: Path, root: Path) -> bool:
    try:
        return f"Exec={root / 'run.sh'}" in path.read_text(encoding="utf-8")
    except OSError:
        return False


def ensure_launchers(home: Path | None = None, root: Path | None = None, desktop: bool = True,
                     env: dict | None = None, run=None) -> list[str]:
    """Makes sure CodeAque is on the Mint application menu (~/.local/share/applications/atari.desktop) and, when asked, as an icon on the
    desktop (~/Desktop/CodeAque.desktop, marked executable and trusted so Cinnamon's file manager starts it with a double click).
    A file that belongs to something else (another Exec line) is never overwritten. Returns what was written. Never raises."""
    import subprocess
    done: list[str] = []
    try:
        home = Path(home) if home is not None else Path.home()
        root = Path(root) if root is not None else app_dir()
        text = _entry_text(root)
        if text is None or not (root / "run.sh").is_file():
            return done
        env = env if env is not None else os.environ
        run = run or subprocess.run
        data_home = Path(env.get("XDG_DATA_HOME") or home / ".local" / "share")
        targets = [("the Mint menu", data_home / "applications" / "atari.desktop")]
        if desktop:
            targets.append(("the desktop", desktop_folder(home, env, run) / "CodeAque.desktop"))
        for what, f in targets:
            if f.exists() and not _ours(f, root):
                continue                                           # somebody else's file: leave it
            if not f.exists() or f.read_text(encoding="utf-8") != text:
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(text, encoding="utf-8")
                done.append(what)
            f.chmod(0o755)
            if what == "the desktop":
                try:
                    run(["gio", "set", str(f), "metadata::trusted", "true"], capture_output=True, timeout=10)
                except (OSError, subprocess.SubprocessError):
                    pass
        if "the Mint menu" in done:
            try:
                run(["update-desktop-database", str(data_home / "applications")], capture_output=True, timeout=10)
            except (OSError, subprocess.SubprocessError):
                pass
    except Exception as exc:  # pragma: no cover
        print(f"[atari] could not add the launchers: {exc}")
    return done


def launchers_present(home: Path | None = None, root: Path | None = None, env: dict | None = None, run=None) -> dict:
    """{'menu': bool, 'desktop': bool}: read back whether the two launchers exist and are CodeAque's."""
    home = Path(home) if home is not None else Path.home()
    root = Path(root) if root is not None else app_dir()
    env = env if env is not None else os.environ
    data_home = Path(env.get("XDG_DATA_HOME") or home / ".local" / "share")
    menu = data_home / "applications" / "atari.desktop"
    desk = desktop_folder(home, env, run) / "CodeAque.desktop"
    return {"menu": menu.is_file() and _ours(menu, root), "desktop": desk.is_file() and _ours(desk, root)}


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
