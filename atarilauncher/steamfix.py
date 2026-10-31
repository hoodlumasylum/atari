"""Steam in CodeAque-only mode: always Big Picture, and Steam Play (Proton) for every game by default.

Four layers, because Steam can be started in many ways and Valve gives no single switch:
  1. Steam's own setting: Registry > HKCU > Software > Valve > Steam > StartupMode = 1 in ~/.steam/registry.vdf ("Start Steam in
     Big Picture Mode"). Only written while Steam is NOT running (Steam rewrites the file when it quits), after a one-time backup.
  2. A `steam` wrapper in CodeAque's own PATH (shims folder): a plain `steam` started by anything CodeAque launched gets -gamepadui, or
     steam://open/bigpicture when Steam is already open. Entries that point at /usr/games/steam by full path bypass it (layer 3).
  3. A watcher in CodeAque (CodeAque-only mode): when a Steam client appears that CodeAque did not start itself, it is told once to open
     Big Picture (steam://open/bigpicture - harmless when Big Picture is already open), once more a little later.
  4. The Steam tile always uses -gamepadui in CodeAque-only mode (the "Open Steam in Big Picture" setting cannot turn it off there).
Steam Play: config/config.vdf > InstallConfigStore > Software > Valve > Steam > CompatToolMapping > "0" (the default for every game)
is set to proton-experimental when nobody chose a tool yet. Same rules: Steam closed, backup first, never overwrites a choice.
Both edits are best effort: Valve's files are undocumented and can change; every failure is reported and logged, never raised."""
from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Callable

from . import steam as steam_mod

SHIM_NAME = "steam"
BACKUP_SUFFIX = ".code-backup"
PROTON_TOOL = "proton-experimental"
NUDGE_AT = (12.0, 35.0)          # seconds after a foreign Steam client appeared: tell it to open Big Picture


# ------------------------------------------------------------------ a small, careful VDF reader / writer
class VdfError(ValueError):
    pass


_TOKEN = re.compile(r'\s*(?:"((?:[^"\\]|\\.)*)"|([{}]))', re.S)
_ESC = {"n": "\n", "t": "\t", "\\": "\\", '"': '"'}


def _unesc(s: str) -> str:
    return re.sub(r"\\(.)", lambda m: _ESC.get(m.group(1), "\\" + m.group(1)), s)


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")


def parse(text: str) -> dict:
    """VDF text -> nested dict (insertion order kept). Raises VdfError for anything it does not understand."""
    text = re.sub(r"(?m)^\s*//.*$", "", text.lstrip("\ufeff"))
    pos, n = 0, len(text)
    toks: list[tuple[str, str]] = []
    while pos < n:
        if not text[pos:].strip():
            break
        m = _TOKEN.match(text, pos)
        if not m:
            raise VdfError(f"unexpected text at {pos}")
        toks.append(("s", _unesc(m.group(1))) if m.group(1) is not None else ("b", m.group(2)))
        pos = m.end()

    def block(i: int, top: bool) -> tuple[dict, int]:
        out: dict = {}
        while i < len(toks):
            kind, val = toks[i]
            if kind == "b":
                if val == "}" and not top:
                    return out, i + 1
                raise VdfError("unbalanced braces")
            key = val
            i += 1
            if i >= len(toks):
                raise VdfError("a key without a value")
            kind2, val2 = toks[i]
            if kind2 == "s":
                out[key] = val2
                i += 1
            elif val2 == "{":
                out[key], i = block(i + 1, False)
            else:
                raise VdfError("unexpected '}'")
        if not top:
            raise VdfError("missing '}'")
        return out, i
    data, _ = block(0, True)
    return data


def dump(data: dict, depth: int = 0) -> str:
    pad = "\t" * depth
    out = []
    for k, v in data.items():
        if isinstance(v, dict):
            out.append(f'{pad}"{_esc(k)}"\n{pad}{{\n{dump(v, depth + 1)}{pad}}}\n')
        else:
            out.append(f'{pad}"{_esc(k)}"\t\t"{_esc(str(v))}"\n')
    return "".join(out)


def child(d: dict, key: str, create: bool = False) -> dict | None:
    """The sub-block called key (Valve mixes upper / lower case between versions, so the match ignores case)."""
    for k, v in d.items():
        if k.lower() == key.lower() and isinstance(v, dict):
            return v
    if create:
        d[key] = {}
        return d[key]
    return None


def _key(d: dict, key: str) -> str | None:
    return next((k for k in d if k.lower() == key.lower()), None)


# ------------------------------------------------------------------ where Steam keeps its files
def registry_candidates(home: Path) -> list[Path]:
    return [home / ".steam" / "registry.vdf", home / ".var/app/com.valvesoftware.Steam/.steam/registry.vdf",
            home / "snap/steam/common/.steam/registry.vdf"]


def config_path(home: Path, cfg_root: str = "") -> Path | None:
    root = steam_mod.find_steam_root(home, cfg_root)
    p = (root / "config" / "config.vdf") if root else None
    return p if p and p.is_file() else None


def _write_checked(path: Path, data: dict, backup: bool = True) -> None:
    text = dump(data)
    if parse(text) != data:                                  # never write what we cannot read back
        raise VdfError("round trip failed")
    if backup:
        b = path.with_name(path.name + BACKUP_SUFFIX)
        if not b.exists():
            shutil.copy2(path, b)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        shutil.copymode(path, tmp)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ------------------------------------------------------------------ the two Steam settings
def set_startup_bigpicture(home: Path | None = None, running: Callable[[], bool] | None = None) -> tuple[bool, str]:
    """Steam > Settings > Interface > "Start Steam in Big Picture Mode", written to registry.vdf. (changed?, plain text)"""
    home = home or Path.home()
    running = running or steam_mod.steam_running
    path = next((p for p in registry_candidates(home) if p.is_file()), None)
    if path is None:
        return False, "Steam has not been started yet (no registry.vdf): its start-up setting will be written next time."
    try:
        data = parse(path.read_text(encoding="utf-8", errors="replace"))
        node = data
        for part in ("Registry", "HKCU", "Software", "Valve", "Steam"):
            node = child(node, part, create=True)
        k = _key(node, "StartupMode")
        if k and node[k] == "1":
            return False, "Steam already starts in Big Picture mode."
        if running():
            return False, "Steam is open right now; its start-up setting is written the next time Steam is closed."
        node[k or "StartupMode"] = "1"
        _write_checked(path, data)
        return True, "Steam's own setting \"Start Steam in Big Picture Mode\" is now ON."
    except (OSError, VdfError) as exc:
        return False, f"Could not set Steam's Big Picture start-up setting ({exc}); the other ways still work."


def set_default_proton(home: Path | None = None, cfg_root: str = "", running: Callable[[], bool] | None = None,
                       tool: str = PROTON_TOOL) -> tuple[bool, str]:
    """Steam Play for every game: CompatToolMapping "0" = proton-experimental, unless a tool was already chosen."""
    home = home or Path.home()
    running = running or steam_mod.steam_running
    path = config_path(home, cfg_root)
    if path is None:
        return False, "Steam has no config yet (sign in once); Steam Play is set up next time."
    try:
        data = parse(path.read_text(encoding="utf-8", errors="replace"))
        node = data
        for part in ("InstallConfigStore", "Software", "Valve", "Steam"):
            node = child(node, part, create=True)
        mapping = child(node, "CompatToolMapping", create=True)
        existing = child(mapping, "0")
        if existing is not None and existing.get(_key(existing, "name") or "name", ""):
            return False, f"Steam Play already uses \"{existing[_key(existing, 'name')]}\" for all games - left as it is."
        if running():
            return False, "Steam is open right now; Steam Play is set up the next time Steam is closed."
        mapping["0"] = {"name": tool, "config": "", "priority": "75"}
        _write_checked(path, data)
        return True, f"Steam Play (Proton) is now ON for all games ({tool}); Steam downloads it the first time a Windows game starts."
    except (OSError, VdfError) as exc:
        return False, f"Could not set up Steam Play ({exc}). In Steam: Settings > Compatibility > Enable Steam Play for all other titles."


# ------------------------------------------------------------------ the `steam` wrapper
WRAPPER = """#!/bin/sh
# Written by CodeAque. In CodeAque-only mode every plain `steam` that CodeAque (or anything it started) runs opens Big Picture.
case "$0" in */*) SHIM_DIR="${0%/*}" ;; *) SHIM_DIR="$(pwd)" ;; esac
real=
OLD_IFS="$IFS"; IFS=:
for d in $PATH; do
    [ -n "$d" ] || continue
    [ "$d" = "$SHIM_DIR" ] && continue
    [ -x "$d/steam" ] && { real="$d/steam"; break; }
done
IFS="$OLD_IFS"
[ -n "$real" ] || { echo "steam: the real Steam was not found" >&2; exit 127; }
for a in "$@"; do
    case "$a" in -gamepadui|-bigpicture|steam://*|-applaunch|-shutdown|-silent|-exitsteam|-ifrunning) exec "$real" "$@" ;; esac
done
if pgrep -x steam >/dev/null 2>&1; then exec "$real" "$@" steam://open/bigpicture; fi
exec "$real" -gamepadui "$@"
"""


def shim_dir(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".local" / "share" / "atari" / "shims"


def install_shim(home: Path | None = None) -> Path | None:
    d = shim_dir(home)
    try:
        d.mkdir(parents=True, exist_ok=True)
        f = d / SHIM_NAME
        if not f.exists() or f.read_text() != WRAPPER:
            f.write_text(WRAPPER)
        f.chmod(0o755)
        return d
    except OSError:
        return None


def put_shim_first(env: dict, home: Path | None = None) -> bool:
    d = install_shim(home)
    if d is None:
        return False
    parts = [p for p in env.get("PATH", "").split(":") if p and p != str(d)]
    env["PATH"] = ":".join([str(d)] + parts)
    return True


# ------------------------------------------------------------------ the watcher (pure logic; CodeAque calls tick() every few seconds)
class Guard:
    """Tells a Steam client that CodeAque did not start to open Big Picture: at NUDGE_AT seconds after it appeared, twice at most."""

    def __init__(self, nudge_at=NUDGE_AT):
        self.nudge_at = tuple(nudge_at)
        self.seen_at: float | None = None
        self.done = 0
        self.handled = False

    def handled_by_code(self) -> None:
        """CodeAque started Steam in Big Picture itself: no nudges for this Steam process."""
        self.handled = True

    def silent_start(self, now: float, seconds: float = 600.0) -> None:
        """CodeAque started Steam hidden (`steam -silent` at boot): never ask THAT Steam for Big Picture (0.5.0 did, which put Steam
        in front of CodeAque). Kept even while the Steam process is not visible yet."""
        self.quiet_until = now + seconds
        self.handled = True

    def tick(self, running: bool, now: float) -> bool:
        """True when a nudge should be sent now."""
        if now < getattr(self, "quiet_until", 0.0):
            if running:
                self.seen_at, self.handled = self.seen_at or now, True
            return False
        if not running:
            self.seen_at, self.done, self.handled = None, 0, False
            return False
        if self.seen_at is None:
            self.seen_at = now
        if self.handled or self.done >= len(self.nudge_at):
            return False
        if now - self.seen_at >= self.nudge_at[self.done]:
            self.done += 1
            return True
        return False


def set_startup_normal(home: Path | None = None, running: Callable[[], bool] | None = None) -> tuple[bool, str]:
    """Undo "Start Steam in Big Picture Mode" (StartupMode 1 -> 0): with it on, even `steam -silent` opens Big Picture full screen
    in front of CodeAque. Used when "Start Steam at boot (hidden)" is on; the Steam tile still opens Big Picture (-gamepadui)."""
    home = home or Path.home()
    running = running or steam_mod.steam_running
    path = next((p for p in registry_candidates(home) if p.is_file()), None)
    if path is None:
        return False, "Steam has no registry.vdf yet."
    try:
        data = parse(path.read_text(encoding="utf-8", errors="replace"))
        node = data
        for part in ("Registry", "HKCU", "Software", "Valve", "Steam"):
            node = child(node, part)
            if node is None:
                return False, "Steam starts normally (not in Big Picture)."
        k = _key(node, "StartupMode")
        if not k or node[k] != "1":
            return False, "Steam starts normally (not in Big Picture)."
        if running():
            return False, "Steam is open right now; it will start hidden from the next start."
        node[k] = "0"
        _write_checked(path, data)
        return True, "Steam no longer opens Big Picture by itself at start (so it can stay hidden); the Steam tile still opens Big Picture."
    except (OSError, VdfError) as exc:
        return False, f"Could not change Steam's start-up setting ({exc})."


def apply(cfg, home: Path | None = None, running: Callable[[], bool] | None = None, proton: bool = True,
          bigpicture_start: bool = True) -> list[str]:
    """Everything that can be done before Steam starts. Returns plain sentences (also for the log)."""
    out: list[str] = []
    ok, text = (set_startup_bigpicture if bigpicture_start else set_startup_normal)(home, running)
    out.append(text)
    if proton and getattr(cfg, "steam_proton_default", True):
        ok2, text2 = set_default_proton(home, getattr(cfg, "steam_root", ""), running)
        out.append(text2)
    return out
