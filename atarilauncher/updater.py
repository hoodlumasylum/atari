"""In-app update: ask GitHub for the latest release, download it, check its SHA256, run its install.sh, restart.

Pure Python (no Qt) so it can be tested with a fake local release server. Rules:
  * the release's own SHA256SUMS.txt must contain the tarball and match, otherwise nothing is installed;
  * only install.sh is run (it never touches ~/.config/atari or ~/.local/share/atari: settings, favourites, history);
  * the old program files are backed up first and put back if the install fails;
  * everything (download, unpacking, the install log) lives in a temp / cache folder, not in your Code data.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import __version__

REPO = "hoodlumasylum/atari"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
USER_AGENT = f"Code-Launcher/{__version__} (+https://github.com/{REPO}; update check)"
CHECK_EVERY = 24 * 3600
MAX_DOWNLOAD = 600 * 1024 * 1024
KEEP = ("atarilauncher", "scripts", "packaging", "run.sh", "install.sh", "uninstall.sh", "requirements.txt",
        "requirements-gamepad.txt", "requirements-studio.txt", "pyproject.toml", "README.md", "LICENSE")


class UpdateError(Exception):
    """A problem with a plain-English message that can be shown as it is."""


class Offline(UpdateError):
    pass


class Cancelled(UpdateError):
    pass


@dataclass
class Release:
    version: str
    notes: str
    page: str
    tar_name: str
    tar_url: str
    sums_url: str

    def as_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d: dict) -> "Release | None":
        try:
            return cls(**{k: str(d[k]) for k in ("version", "notes", "page", "tar_name", "tar_url", "sums_url")})
        except (KeyError, TypeError):
            return None


# ------------------------------------------------------------------ versions
def parse_version(text: str) -> tuple:
    m = re.match(r"^\s*v?(\d+(?:\.\d+)*)", str(text))
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def is_newer(latest: str, current: str = __version__) -> bool:
    a, b = parse_version(latest), parse_version(current)
    if not a or not b:
        return False
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


# ------------------------------------------------------------------ where things live
def app_dir() -> Path:
    """The folder this running copy of Code lives in."""
    return Path(__file__).resolve().parent.parent


def can_self_update(root: Path | None = None) -> tuple[bool, str]:
    """Only a copy put there by install.sh is updated in place (not a source checkout)."""
    root = root or app_dir()
    if (root / ".venv").is_dir() and (root / "install.sh").is_file():
        return True, ""
    return False, ("This copy of Code was not set up with install.sh, so it cannot update itself. "
                   f"Download the new version from https://github.com/{REPO}/releases/latest")


def cache_dir() -> Path:
    override = os.environ.get("ATARI_CACHE_DIR")
    if override:
        return Path(override)
    return Path(os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")) / "atari"


# ------------------------------------------------------------------ talking to GitHub
def _open(url: str, timeout: float, accept: str = "*/*"):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    return urllib.request.urlopen(req, timeout=timeout)


def _net_error(exc: Exception) -> UpdateError:
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code in (403, 429):
            return UpdateError("GitHub is asking us to slow down. Please try again in an hour.")
        if exc.code == 404:
            return UpdateError("No release was found online yet.")
        return UpdateError(f"The update server answered with an error ({exc.code}). Try again later.")
    return Offline("Could not reach the update server. Check your internet connection and try again.")


def fetch_latest(api_url: str | None = None, timeout: float = 10.0) -> Release | None:
    """The latest published release, or None when it has no installable package."""
    url = api_url or os.environ.get("ATARI_UPDATE_API") or API_URL
    try:
        with _open(url, timeout, "application/vnd.github+json") as resp:
            data = json.loads(resp.read(2_000_000).decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise _net_error(exc)
    except ValueError:
        raise UpdateError("The update server sent something unexpected. Try again later.")
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    version = str(data.get("tag_name") or "").lstrip("vV")
    assets = {str(a.get("name")): str(a.get("browser_download_url")) for a in data.get("assets") or []
              if isinstance(a, dict)}
    # Releases keep the file name atari-<version>.tar.gz (copies of Code older than 0.4 look for exactly that name);
    # a future release named code-<version>.tar.gz is understood too.
    tar_name = next((n for n in (f"atari-{version}.tar.gz", f"code-{version}.tar.gz") if n in assets), f"atari-{version}.tar.gz")
    if not version or tar_name not in assets or "SHA256SUMS.txt" not in assets:
        return None
    return Release(version, str(data.get("body") or "").strip(), str(data.get("html_url") or ""),
                   tar_name, assets[tar_name], assets["SHA256SUMS.txt"])


def check(current: str = __version__, api_url: str | None = None) -> Release | None:
    """The release if it is newer than this copy, else None."""
    rel = fetch_latest(api_url)
    return rel if rel and is_newer(rel.version, current) else None


def due(last_checked: float, now: float | None = None) -> bool:
    return (now if now is not None else time.time()) - float(last_checked or 0) >= CHECK_EVERY


# ------------------------------------------------------------------ download + verify
def download(url: str, dest: Path, progress: Callable[[int, int], None] | None = None,
             cancel: threading.Event | None = None, timeout: float = 30.0) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    try:
        with _open(url, timeout) as resp, open(part, "wb") as fh:
            total = int(resp.headers.get("Content-Length") or 0)
            if total > MAX_DOWNLOAD:
                raise UpdateError("The download is much bigger than expected, so it was not started.")
            done = 0
            while True:
                if cancel is not None and cancel.is_set():
                    raise Cancelled("Cancelled.")
                buf = resp.read(256 * 1024)
                if not buf:
                    break
                done += len(buf)
                if done > MAX_DOWNLOAD:
                    raise UpdateError("The download is much bigger than expected, so it was stopped.")
                fh.write(buf)
                if progress:
                    progress(done, total)
        part.replace(dest)
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        part.unlink(missing_ok=True)
        if isinstance(exc, (urllib.error.URLError, TimeoutError)):
            raise _net_error(exc)
        raise UpdateError(f"Could not save the download: {exc}")
    except BaseException:
        part.unlink(missing_ok=True)
        raise


def read_text(url: str, timeout: float = 20.0) -> str:
    try:
        with _open(url, timeout) as resp:
            return resp.read(1_000_000).decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise _net_error(exc)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def expected_hash(sums_text: str, name: str) -> str:
    for line in sums_text.splitlines():
        m = re.match(r"^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$", line)
        if m and Path(m.group(2)).name == name:
            return m.group(1).lower()
    return ""


def verify(tar_path: Path, sums_text: str) -> None:
    want = expected_hash(sums_text, tar_path.name)
    if not want:
        raise UpdateError("The release has no checksum for this file, so Code will not install it.")
    if sha256_of(tar_path) != want:
        tar_path.unlink(missing_ok=True)
        raise UpdateError("The downloaded file is damaged or was changed (its checksum does not match). "
                          "Nothing was installed. Please try again.")


# ------------------------------------------------------------------ unpack + install
def safe_extract(tar_path: Path, dest: Path) -> Path:
    """Unpack into dest (regular files and folders only, nothing outside dest). Returns the folder with install.sh."""
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    try:
        with tarfile.open(tar_path, "r:gz") as tf:
            members = []
            for m in tf.getmembers():
                target = (dest / m.name).resolve()
                if not (target == root or str(target).startswith(str(root) + os.sep)):
                    raise UpdateError("The update package contains an unsafe path, so it was not unpacked.")
                if m.isdir() or m.isreg():
                    m.mode = (m.mode & 0o777) | 0o600
                    members.append(m)
                # links, devices etc. are skipped on purpose
            try:
                tf.extractall(dest, members=members, filter="data")
            except TypeError:   # older Python without extraction filters (members are already vetted above)
                tf.extractall(dest, members=members)
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise UpdateError(f"The update package could not be unpacked ({exc}).")
    for cand in [dest] + sorted(p for p in dest.iterdir() if p.is_dir()):
        if (cand / "install.sh").is_file() and (cand / "atarilauncher" / "__init__.py").is_file():
            return cand
    raise UpdateError("The update package does not look like Code (no install.sh inside).")


def version_in(folder: Path) -> str:
    try:
        text = (folder / "atarilauncher" / "__init__.py").read_text(encoding="utf-8")
    except OSError:
        return ""
    m = re.search(r'^__version__ = "(.*)"', text, flags=re.M)
    return m.group(1) if m else ""


def _backup(root: Path, into: Path) -> None:
    into.mkdir(parents=True, exist_ok=True)
    for name in KEEP:
        src = root / name
        if src.is_dir():
            shutil.copytree(src, into / name, symlinks=True)
        elif src.is_file():
            shutil.copy2(src, into / name)


def _restore(root: Path, frm: Path) -> None:
    for name in KEEP:
        cur = root / name
        if cur.is_dir() and not cur.is_symlink():
            shutil.rmtree(cur, ignore_errors=True)
        elif cur.exists() or cur.is_symlink():
            cur.unlink()
        src = frm / name
        if src.is_dir():
            shutil.copytree(src, cur, symlinks=True)
        elif src.is_file():
            shutil.copy2(src, cur)


def run_install(src: Path, root: Path, progress: Callable[[str], None] | None = None,
                log_path: Path | None = None, timeout: float = 3600.0) -> None:
    """Run the new package's install.sh (no questions, no sudo) into root. On failure the old files come back."""
    backup = Path(tempfile.mkdtemp(prefix="atari-old-"))
    _backup(root, backup)
    env = dict(os.environ, ATARI_INSTALL_DIR=str(root), TERM="dumb")
    env.pop("PYTHONPATH", None)
    log_path = log_path or (cache_dir() / "update.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    tail: list[str] = []
    try:
        with open(log_path, "w", encoding="utf-8") as log:
            proc = subprocess.Popen(["bash", str(src / "install.sh"), "--yes", "--no-system-packages"], cwd=str(src),
                                    env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, errors="replace")
            timer = threading.Timer(timeout, proc.kill)
            timer.start()
            try:
                for line in proc.stdout:
                    log.write(line)
                    clean = re.sub(r"\x1b\[[0-9;]*m", "", line).strip()
                    if clean:
                        tail.append(clean)
                        tail[:] = tail[-6:]
                    if clean.startswith("==>") and progress:
                        progress(clean[3:].strip())
                code = proc.wait()
            finally:
                timer.cancel()
    except OSError as exc:
        _restore(root, backup)
        shutil.rmtree(backup, ignore_errors=True)
        raise UpdateError(f"Could not run the installer: {exc}")
    if code != 0:
        _restore(root, backup)
        shutil.rmtree(backup, ignore_errors=True)
        why = tail[-1] if tail else f"exit code {code}"
        raise UpdateError(f"The installer stopped ({why}). Your old version was put back and still works. "
                          f"Details: {log_path}")
    shutil.rmtree(backup, ignore_errors=True)


def perform(rel: Release, root: Path | None = None, progress: Callable[[str, str, float], None] | None = None,
            cancel: threading.Event | None = None) -> str:
    """The whole update. progress(state, text, fraction 0..1 or -1). Returns the installed version."""
    root = root or app_dir()
    ok, why = can_self_update(root)
    if not ok:
        raise UpdateError(why)
    say = progress or (lambda *_: None)
    work = Path(tempfile.mkdtemp(prefix="atari-update-"))
    try:
        say("downloading", "Checking the release ...", -1)
        sums = read_text(rel.sums_url)
        tar = work / rel.tar_name

        def dl(done: int, total: int) -> None:
            mb = done / 1048576
            say("downloading", f"Downloading {rel.version}: {mb:.0f} MB" + (f" of {total / 1048576:.0f} MB" if total else ""),
                (done / total) if total else -1)

        download(rel.tar_url, tar, dl, cancel)
        say("verifying", "Checking the download is genuine ...", -1)
        verify(tar, sums)
        say("installing", "Unpacking ...", -1)
        src = safe_extract(tar, work / "pkg")
        got = version_in(src)
        if got and got != rel.version:
            raise UpdateError(f"The package says version {got}, not {rel.version}. Nothing was installed.")
        if cancel is not None and cancel.is_set():
            raise Cancelled("Cancelled.")
        say("installing", "Installing (this can take a few minutes) ...", -1)
        run_install(src, root, lambda step: say("installing", step + " ...", -1))
        new = version_in(root)
        if new and new != rel.version:
            raise UpdateError(f"After installing, Code reports version {new}. Please try again.")
        return rel.version
    finally:
        shutil.rmtree(work, ignore_errors=True)


def restart_command(root: Path | None = None, argv: list[str] | None = None) -> list[str]:
    """A detached command that starts the freshly installed Code a moment after this one has quit."""
    root = root or app_dir()
    args = [a for a in (argv or []) if a not in ("--selftest",)]
    return ["bash", "-c", 'sleep 1.5; exec "$0" "$@"', str(root / "run.sh"), *args]
