"""xemu's settings file (xemu.toml): find the user's own Xbox files, check the [sys.files] paths, and repair them.

xemu (the original-Xbox emulator) takes its four files from xemu.toml, section [sys.files]:
    bootrom_path   the MCPX boot ROM (512 bytes)            flashrom_path  the BIOS (256 KB, 512 KB or 1 MB)
    eeprom_path    the EEPROM (xemu makes one if empty)      hdd_path       the hard-disk image (qcow2)
Nothing is searched by name by xemu itself: an empty path gives "Failed to open flash file ''. Please check machine settings."
xemu writes its own xemu.toml with EMPTY paths the first time it is started, so a file written only "when none exists yet" is never used.
Here the paths are checked every time and filled in from the files that are really there; a path the user chose that still points to a real
file is never changed. Files are never bundled, downloaded or created (except the optional empty hard-disk image made with qemu-img).
Where the file lives: native / AppImage  ~/.local/share/xemu/xemu/xemu.toml ; Flatpak  ~/.var/app/app.xemu.xemu/data/xemu/xemu/xemu.toml ;
a xemu.toml next to the xemu program (portable mode) is read first by xemu, so that one is repaired too.
Pure Python, injectable tools, never raises."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

KEYS = ("bootrom_path", "flashrom_path", "eeprom_path", "hdd_path")
REQUIRED = ("bootrom_path", "flashrom_path", "hdd_path")
LABEL = {"bootrom_path": "Boot ROM (MCPX)", "flashrom_path": "BIOS (flash)", "eeprom_path": "EEPROM", "hdd_path": "Hard-disk image"}
CANONICAL = {"bootrom_path": "mcpx_1.0.bin", "flashrom_path": "Complex_4627v1.03.bin", "eeprom_path": "eeprom.bin", "hdd_path": "xbox_hdd.qcow2"}
BOOTROM_SIZE = 512
FLASH_SIZES = (256 * 1024, 512 * 1024, 1024 * 1024)
BACKUP_NAME = "xemu.toml.codeaque-backup"
EXTS = (".bin", ".rom", ".img", ".bios")
FLASH_VERSIONS = ("3944", "4034", "4134", "4627", "4817", "5101", "5530", "5713", "5788", "5838")


def _norm(stem: str) -> str:
    return re.sub(r"[^a-z0-9]", "", stem.lower())


def classify_name(name: str, generic: bool = True) -> str:
    """Which [sys.files] key a file NAME is for ('' = not recognised). Accepts spaces, dashes, versions, upper case, no extension:
    Complex_4627.bin, Complex 4627, complex-4627-v1.03.BIN, Cerbios.bin, xbox_bios.bin, mcpx_1.0.bin, MCPX v1.0.rom ...
    generic=False leaves out names that other consoles use too (bios.bin, flash.bin): used when reading a pack of unknown files."""
    low = name.lower()
    stem, ext = os.path.splitext(low)
    if ext not in EXTS and ext not in (".qcow2", ""):
        if not re.fullmatch(r"\.\d+", ext):                      # "Complex 4627v1.03" has a ".03" that is not an extension
            return ""
        stem, ext = low, ""
    if ext == ".qcow2":
        return "hdd_path"
    n = _norm(stem)
    if not n:
        return ""
    if n in ("eeprom", "xboxeeprom"):
        return "eeprom_path"
    if n.startswith("mcpx") or n in ("bootrom", "xboxbootrom", "mcpxrom"):
        return "bootrom_path"
    if n.startswith(("complex", "cerbios")) or n in ("xboxbios", "xemubios", "xbioscomplex"):
        return "flashrom_path"
    if generic and n in ("flashrom", "flash", "bios", "xbox"):
        return "flashrom_path"
    if "bios" in n and ("xbox" in n or any(v in n for v in FLASH_VERSIONS)):
        return "flashrom_path"
    if "complex" in n or "cerbios" in n:
        return "flashrom_path"
    return ""


def size_problem(key: str, size: int) -> str:
    """'' when the size is right for this file, else why not."""
    if key == "bootrom_path" and size != BOOTROM_SIZE:
        return f"the boot ROM must be exactly 512 bytes (this one is {size})"
    if key == "flashrom_path" and size not in FLASH_SIZES:
        return f"the BIOS must be 256 KB, 512 KB or 1 MB (this one is {size} bytes)"
    if key == "hdd_path" and size <= 0:
        return "the disk image is empty"
    return ""


# ------------------------------------------------------------------ where things are
def data_folders(home: Path | None = None, which: Callable = shutil.which) -> list[Path]:
    """The folders xemu reads/writes in: the ones CodeAque copies BIOS files to, first."""
    from . import bios
    home = home or Path.home()
    out = list(bios.target_dirs("xemu", home, None, which))
    emu_id, fp_id, native, flat = bios.TARGETS["xemu"]
    for rel in [home / r for r in native] + [home / ".var/app" / fp_id / r for r in flat]:
        if rel not in out:
            out.append(rel)
    return out


def config_files(home: Path | None = None, which: Callable = shutil.which) -> list[Path]:
    """xemu.toml files to check: the one(s) xemu will read (in the order xemu looks), plus any other that already exists."""
    from . import bios
    home = home or Path.home()
    used = [f / "xemu.toml" for f in bios.target_dirs("xemu", home, None, which)]
    out: list[Path] = []
    exe = which("xemu")
    if exe:                                                      # portable mode: a xemu.toml next to the program wins
        p = Path(exe).resolve().parent / "xemu.toml"
        if p.is_file():
            out.append(p)
    out += used
    for f in data_folders(home, which):
        t = f / "xemu.toml"
        if t.is_file() and t not in out:
            out.append(t)
    return list(dict.fromkeys(out))


def search_folders(home: Path | None = None, which: Callable = shutil.which) -> list[Path]:
    home = home or Path.home()
    out = data_folders(home, which)
    for g in ("Atari", "Code", "CodeAque"):
        out.append(home / "Games" / g / "xbox")
    return [p for p in dict.fromkeys(out)]


@dataclass
class Found:
    path: Path
    how: str            # "name" | "size"
    problem: str = ""


def find_files(home: Path | None = None, which: Callable = shutil.which) -> dict[str, Found]:
    """The user's Xbox files that are really on the computer, by name first (variants accepted), then - only for the BIOS and the
    boot ROM, only when nothing matched by name - a single unnamed file of exactly the right size. The data folders are searched
    before the games folders."""
    found: dict[str, Found] = {}
    unknown: list[Path] = []
    from . import bios
    data = set(data_folders(home, which))
    for folder in search_folders(home, which):
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for n in names:
            p = folder / n
            try:
                if not p.is_file():
                    continue
                size = p.stat().st_size
            except OSError:
                continue
            key = classify_name(n)
            if key:
                prob = size_problem(key, size)
                old = found.get(key)
                exact = n == CANONICAL[key]
                if old is None or (old.problem and not prob) or (not prob and exact and old.path.name != CANONICAL[key]):
                    found[key] = Found(p, "name", prob)
            elif n.lower().endswith((".bin", ".rom")) and n.lower() not in bios.KNOWN_BY_NAME and folder in data:
                unknown.append(p)
    for key, test in (("flashrom_path", lambda s: s in FLASH_SIZES), ("bootrom_path", lambda s: s == BOOTROM_SIZE)):
        if key in found and not found[key].problem:
            continue
        cands = []
        for p in unknown:
            try:
                if test(p.stat().st_size):
                    cands.append(p)
            except OSError:
                pass
        if len(cands) == 1:
            found[key] = Found(cands[0], "size")
    return found


# ------------------------------------------------------------------ reading and writing the toml
def read_files_section(text: str) -> dict[str, str]:
    """The [sys.files] values of a xemu.toml text ({} when none / unreadable)."""
    try:
        import tomllib
        data = tomllib.loads(text)
        sec = data.get("sys", {}).get("files", {})
        return {k: str(v) for k, v in sec.items() if isinstance(v, str)}
    except Exception:
        pass
    vals: dict[str, str] = {}
    cur = ""
    for line in text.splitlines():
        m = re.match(r"^\s*\[([^\]]+)\]\s*$", line)
        if m:
            cur = m.group(1).strip()
            continue
        m = re.match(r"""^\s*([A-Za-z_]+)\s*=\s*(?:'([^']*)'|"((?:[^"\\]|\\.)*)")""", line)
        if m and cur == "sys.files":
            vals[m.group(1)] = m.group(2) if m.group(2) is not None else (m.group(3) or "")
    return vals


def toml_string(value: str) -> str:
    if "'" not in value and "\n" not in value:
        return "'" + value + "'"
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return toml_string(str(v))


def set_section_values(text: str, header: str, values: dict) -> str:
    """Return the text with these keys set in the table [header] (added at the end when the table is missing), leaving every other
    line exactly as it is."""
    lines = text.splitlines(keepends=True)
    pat = re.compile(r"^\s*\[" + re.escape(header) + r"\]\s*$")
    start = next((i for i, ln in enumerate(lines) if pat.match(ln)), None)
    if start is None:
        body = "".join(f"{k} = {toml_value(v)}\n" for k, v in values.items())
        sep = "" if (not text or text.endswith("\n\n")) else ("\n" if text.endswith("\n") else "\n\n")
        return text + sep + f"[{header}]\n" + body
    end = next((i for i in range(start + 1, len(lines)) if re.match(r"^\s*\[", lines[i])), len(lines))
    todo = dict(values)
    for i in range(start + 1, end):
        m = re.match(r"^(\s*)([A-Za-z_0-9]+)(\s*=\s*)", lines[i])
        if m and m.group(2) in todo:
            lines[i] = f"{m.group(1)}{m.group(2)} = {toml_value(todo.pop(m.group(2)))}\n"
    if todo:
        ins = "".join(f"{k} = {toml_value(v)}\n" for k, v in todo.items())
        if end > start + 1 and not lines[end - 1].endswith("\n"):
            lines[end - 1] += "\n"
        # new keys go right after the last key of the table (before blank lines that lead to the next table)
        pos = end
        while pos > start + 1 and not lines[pos - 1].strip():
            pos -= 1
        lines.insert(pos, ins)
    return "".join(lines)


def set_files_section(text: str, values: dict[str, str]) -> str:
    """Return the text with these [sys.files] keys set, leaving every other setting exactly as it is."""
    return set_section_values(text, "sys.files", values)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


# ------------------------------------------------------------------ check and repair
@dataclass
class Row:
    key: str
    label: str
    path: str            # the path now in the file ('' = none)
    state: str           # ok | fixed (written now) | todo (can be fixed) | missing | bad
    text: str


@dataclass
class Report:
    rows: list[Row] = field(default_factory=list)
    configs: list[str] = field(default_factory=list)     # xemu.toml files looked at / written
    written: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    ok: bool = False                                     # all required files set and present

    @property
    def missing(self) -> list[Row]:
        return [r for r in self.rows if r.state in ("missing", "bad", "todo") and r.key in REQUIRED]

    def lines(self) -> list[str]:
        out = [f"xemu settings file: {c}" for c in self.configs]
        for r in self.rows:
            out.append(f"{r.label}: {r.path or '(not set)'}  -  {r.text}")
        out += self.notes
        return out


def _valid(key: str, value: str) -> str:
    """'' when value is a usable file for key, else the reason."""
    if not value.strip():
        return "empty"
    p = Path(value).expanduser()
    try:
        if not p.is_file():
            return "the file is not there"
        return size_problem(key, p.stat().st_size)
    except OSError as exc:
        return f"cannot be read ({exc.strerror or exc})"


def is_portal_path(value: str) -> bool:
    """A Flatpak document-portal path (/run/user/1000/doc/<id>/file): what xemu's Flatpak file picker hands back. It only exists while
    the portal keeps it (it can be gone after a restart), so CodeAque copies such files into xemu's own folder and uses that path."""
    v = str(value or "")
    return v.startswith("/run/user/") and "/doc/" in v


def keep_portal_file(key: str, value: str, folder: Path) -> Path | None:
    """Copy a portal file into folder (standard name; never over a different existing file). The new path, or None."""
    try:
        src = Path(value)
        if not src.is_file():
            return None
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / CANONICAL.get(key, src.name)
        if dest.exists():
            if dest.stat().st_size == src.stat().st_size:
                return dest
            dest = folder / src.name
            if dest.exists():
                return dest if dest.stat().st_size == src.stat().st_size else None
        shutil.copy2(src, dest)
        return dest
    except OSError:
        return None


def _check_one(toml: Path, found: dict[str, Found], write: bool, folder: Path | None = None) -> tuple[list[Row], bool, str]:
    """Check (and with write=True fix) one xemu.toml. Returns (rows, wrote, note)."""
    try:
        text = toml.read_text(encoding="utf-8") if toml.is_file() else ""
    except OSError as exc:
        return [], False, f"Could not read {toml}: {exc.strerror or exc}"
    note = ""
    try:
        import tomllib
        tomllib.loads(text)
    except ImportError:
        pass
    except Exception:
        note = f"{toml.name} could not be read as settings; a copy was kept as {toml.name}.codeaque-bad and a fresh one is written."
        if write:
            try:
                shutil.copyfile(toml, toml.with_name(toml.name + ".codeaque-bad"))
            except OSError:
                pass
        text = ""
    cur = read_files_section(text)
    rows: list[Row] = []
    new: dict[str, str] = {}
    for key in KEYS:
        value = cur.get(key, "")
        if is_portal_path(value) and folder is not None and not _valid(key, value):
            kept = keep_portal_file(key, value, folder) if write else None
            if kept is not None:
                new[key] = str(kept)
                rows.append(Row(key, LABEL[key], str(kept), "fixed", f"was a temporary Flatpak path ({value}); copied to {kept} and set"))
                continue
            if not write:
                rows.append(Row(key, LABEL[key], value, "todo", "is a temporary Flatpak path that can vanish after a restart - "
                                "Repair copies the file into xemu's folder"))
                continue
        why = _valid(key, value)
        if not why:
            rows.append(Row(key, LABEL[key], value, "ok", "OK (kept)"))
            continue
        f = found.get(key)
        if f is not None and not f.problem:
            new[key] = str(f.path)
            how = " (picked by its size - check it is your BIOS)" if f.how == "size" else ""
            was = "was empty" if why == "empty" else "was wrong: " + why
            rows.append(Row(key, LABEL[key], str(f.path), "fixed" if write else "todo",
                            was + (", now set" if write else f", can be set to {f.path.name}") + how))
        elif key == "eeprom_path":
            rows.append(Row(key, LABEL[key], value, "ok", "not set - xemu makes its own (fine)" if why == "empty" else "will be made by xemu: " + why))
        elif f is not None:
            rows.append(Row(key, LABEL[key], value, "bad", f"found {f.path.name} but {f.problem}"))
        else:
            rows.append(Row(key, LABEL[key], value, "missing", ("not set and " if why == "empty" else why + " and ") + "no matching file was found"))
    wrote = False
    if new and write:
        if toml.is_file():
            bak = toml.with_name(BACKUP_NAME)
            if not bak.exists():
                try:
                    shutil.copyfile(toml, bak)
                except OSError:
                    pass
        _atomic_write(toml, set_files_section(text, new))
        wrote = True
    return rows, wrote, note


def check(home: Path | None = None, which: Callable = shutil.which, repair: bool = False) -> Report:
    """Look at every xemu.toml xemu may read; with repair=True fill in empty or wrong paths from the files found. Never raises."""
    rep = Report()
    try:
        found = find_files(home, which)
        configs = config_files(home, which)
        for toml in configs:
            rows, wrote, note = _check_one(toml, found, repair, data_folders(home, which)[0])
            rep.configs.append(str(toml))
            if wrote:
                rep.written.append(str(toml))
            if note:
                rep.notes.append(note)
            if not rep.rows and rows:
                rep.rows = rows
        rep.ok = all(r.state in ("ok", "fixed") for r in rep.rows if r.key in REQUIRED) and bool(rep.rows)
        if any(r.how == "size" for r in found.values()):
            rep.notes.append("A file was picked only by its size (its name was not recognised). Check that it really is your Xbox BIOS / boot ROM.")
    except Exception as exc:  # pragma: no cover - never stop the launcher
        rep.notes.append(f"Could not check the xemu settings: {exc}")
    return rep


def repair(home: Path | None = None, which: Callable = shutil.which) -> Report:
    return check(home, which, repair=True)


MISSING_HELP = {
    "bootrom_path": "the boot ROM (mcpx_1.0.bin, 512 bytes)",
    "flashrom_path": "the BIOS (for example Complex_4627v1.03.bin, 256 KB / 512 KB / 1 MB)",
    "hdd_path": "a hard-disk image (xbox_hdd.qcow2)",
}


def launch_problem(rep: Report) -> str:
    """'' when xemu can start, else a plain sentence that replaces xemu's own empty-path dialog."""
    if rep.ok:
        return ""
    parts = [f"{r.label}: {r.text}" for r in rep.missing]
    need = ", ".join(MISSING_HELP[r.key] for r in rep.missing if r.key in MISSING_HELP)
    return ("xemu cannot start yet - it still needs " + need + ". (" + "; ".join(parts) + ".) "
            "Use Settings > Emulators > Xbox: check and repair xemu settings, or Add BIOS files with files from your own Xbox.")


def ensure_for_launch(home: Path | None = None, which: Callable = shutil.which) -> tuple[bool, str, Report]:
    """Called just before xemu starts: repair the paths, then say whether it can work. Never raises."""
    rep = repair(home, which)
    return rep.ok, launch_problem(rep), rep


# ------------------------------------------------------------------ the empty hard-disk image (optional, needs qemu-img)
HDD_SIZE = "8G"


def hdd_tool(which: Callable = shutil.which) -> str:
    for n in ("xemu-img", "qemu-img"):
        p = which(n)
        if p:
            return p
    return ""


def create_empty_hdd(home: Path | None = None, which: Callable = shutil.which, runner: Callable = subprocess.run) -> tuple[bool, str]:
    """An empty (unformatted) qcow2 disk image in xemu's data folder, never over an existing file. The Xbox's own start-up formats it."""
    tool = hdd_tool(which)
    if not tool:
        return False, "No disk-image tool is installed. Install it once (Terminal):  sudo apt install qemu-utils   - then press this button again."
    have = find_files(home, which).get("hdd_path")
    if have is not None:
        return False, f"{have.path} already exists - nothing was changed."
    folder = data_folders(home, which)[0]
    dest = folder / CANONICAL["hdd_path"]
    if dest.exists():
        return False, f"{dest} already exists - nothing was changed."
    try:
        folder.mkdir(parents=True, exist_ok=True)
        r = runner([tool, "create", "-f", "qcow2", str(dest), HDD_SIZE], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"Could not make the disk image: {exc}"
    if getattr(r, "returncode", 1) != 0 or not dest.is_file():
        try:
            if dest.exists() and dest.stat().st_size == 0:
                dest.unlink()
        except OSError:
            pass
        return False, "The disk-image tool failed: " + ((getattr(r, "stderr", "") or "").strip()[:200] or f"code {getattr(r, 'returncode', '?')}")
    return True, f"Made an empty {HDD_SIZE} disk image (it only uses space as games need it): {dest}."


# xemu's own pre-built 8 GB disk (linked from xemu.app/docs/required-files): already FATX-formatted, no Microsoft files - only
# xemu's small unsigned starter dashboard. Pinned: the zip and the disk inside must match these SHA-256 sums (checked 31 Oct 2026).
READY_HDD_URL = "https://github.com/xemu-project/xemu-hdd-image/releases/download/1.0/xbox_hdd.qcow2.zip"
READY_HDD_ZIP_SHA256 = "d9f5a4c1224ff24cf9066067bda70cc8b9c874ea22b9c542eb2edbfc4621bb39"
READY_HDD_SHA256 = "eb35d069715dfc0d37cfac086a0b73a89a02e8f12519cd8eda82ad479d1a4eed"
READY_HDD_NAME = "xbox_hdd_formatted.qcow2"


def _sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _download(url: str, dest: Path, progress: Callable[[float], None] | None = None) -> None:
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "CodeAque"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        while True:
            b = r.read(16384)
            if not b:
                break
            f.write(b)
            got += len(b)
            if progress and total:
                progress(min(1.0, got / total))


def get_ready_hdd(home: Path | None = None, which: Callable = shutil.which, fetch: Callable = _download,
                  say: Callable[[str, float], None] | None = None) -> tuple[bool, str, Path | None]:
    """Download xemu's formatted disk, check both checksums, keep it as xbox_hdd_formatted.qcow2 in xemu's folder (never over another
    file) and point hdd_path at it. The old disk (if any) is left where it is. -> (ok, message, path)."""
    import tempfile
    import zipfile
    say = say or (lambda stage, frac: None)
    folder = data_folders(home, which)[0]
    dest = folder / READY_HDD_NAME
    try:
        folder.mkdir(parents=True, exist_ok=True)
        if not (dest.is_file() and _sha256(dest) == READY_HDD_SHA256):
            moved = None
            if dest.exists():
                # usually our own disk, changed by xemu while you played (xemu writes to it) - never delete: keep it as a .bak
                import time as _t
                moved = dest.with_name(dest.name + "." + _t.strftime("%Y%m%d-%H%M%S") + ".bak")
                n = 1
                while moved.exists():
                    n += 1
                    moved = dest.with_name(dest.name + "." + _t.strftime("%Y%m%d-%H%M%S") + f"-{n}.bak")
                os.replace(dest, moved)
                say("Kept your old disk as " + moved.name, 0.0)
            with tempfile.TemporaryDirectory(dir=folder) as td:
                z = Path(td) / "hdd.zip"
                say("Downloading", 0.0)
                try:
                    fetch(READY_HDD_URL, z, lambda f: say("Downloading", f))
                except TypeError:
                    fetch(READY_HDD_URL, z)
                say("Checking", 1.0)
                if _sha256(z) != READY_HDD_ZIP_SHA256:
                    if moved is not None and not dest.exists():
                        os.replace(moved, dest)
                    return False, "The download did not match xemu's published disk (checksum) - nothing was changed.", None
                with zipfile.ZipFile(z) as zf:
                    member = next((n for n in zf.namelist() if n.endswith(".qcow2") and "/" not in n.strip("/")), None)
                    if member is None:
                        if moved is not None and not dest.exists():
                            os.replace(moved, dest)
                        return False, "The download had no disk image in it - nothing was changed.", None
                    tmp = Path(td) / "disk.qcow2"
                    with zf.open(member) as src, open(tmp, "wb") as out:
                        shutil.copyfileobj(src, out)
                if _sha256(tmp) != READY_HDD_SHA256:
                    if moved is not None and not dest.exists():
                        os.replace(moved, dest)
                    return False, "The disk inside the download did not match its checksum - nothing was changed.", None
                os.replace(tmp, dest)
    except (OSError, zipfile.BadZipFile) as exc:
        return False, f"Could not get the ready-made disk: {exc}", None
    except Exception as exc:  # network errors (urllib)
        return False, f"Could not download the ready-made disk (is the internet on?): {exc}", None
    say("Setting it up", 1.0)
    wrote = []
    for toml in config_files(home, which) or [folder / "xemu.toml"]:
        try:
            text = toml.read_text() if toml.exists() else ""
            _atomic_write(toml, set_files_section(text, {"hdd_path": str(dest)}))
            if read_files_section(toml.read_text()).get("hdd_path") == str(dest):
                wrote.append(str(toml))
        except OSError:
            continue
    if not wrote:
        return False, f"Got the disk ({dest}) but could not write it into xemu's settings - pick it in xemu: Machine > System.", dest
    old = sorted(folder.glob(READY_HDD_NAME + ".*.bak"))
    return True, (f"Done. A formatted 8 GB Xbox hard disk (xemu's own, checksum verified) at {dest}, set in " + ", ".join(wrote)
                  + ". Close and reopen xemu if it was running."
                  + (f" Your previous disk was kept (not deleted) as {old[-1].name}." if old else "")), dest


HDD_PAGE = "https://xemu.app/docs/required-files/"
FORMAT_HELP = ("A new blank disk is not formatted yet, and xemu cannot format it by itself (the Xbox shows an error such as "
               "\"Your Xbox requires service\" / error 05 or 07, or xemu stops at a black screen). Three ways, from easiest: "
               "(1) xemu's own free ready-made 8 GB disk (no Microsoft files in it; linked on xemu's Required Files page - press "
               "\"Open xemu's disk page\", download it yourself, then Find my BIOS files or Add BIOS files puts it in place); "
               "(2) a copy of your own Xbox's hard disk; (3) format the blank disk with XboxHDM or FATXplorer (other people's tools, "
               "for Windows). CodeAque never downloads it for you.")


# ------------------------------------------------------------------ player 1 controller
PAD_DRIVER = "usb-xbox-gamepad"


def read_pad(home: Path | None = None, which: Callable = shutil.which) -> dict:
    """What xemu.toml says about player 1 now: {'file': str, 'driver': str, 'guid': str, 'auto_bind': bool|None}. Never raises."""
    out = {"file": "", "driver": "", "guid": "", "auto_bind": None}
    try:
        import tomllib
        for toml in config_files(home, which):
            if not toml.is_file():
                continue
            data = tomllib.loads(toml.read_text(encoding="utf-8"))
            inp = data.get("input", {})
            b = inp.get("bindings", {})
            out.update(file=str(toml), driver=str(b.get("port1_driver", "")), guid=str(b.get("port1", "")), auto_bind=inp.get("auto_bind"))
            break
    except Exception:
        pass
    return out


def set_pad(guid: str, home: Path | None = None, which: Callable = shutil.which) -> tuple[bool, list[str], str]:
    """Bind this pad (SDL GUID) to player 1 of the virtual Xbox in every xemu.toml xemu may read, and keep xemu's own automatic binding on.
    Only [input] auto_bind and [input.bindings] port1_driver / port1 are written; everything else stays. A copy of the old file is
    kept once. Returns (worked, files written, text)."""
    written: list[str] = []
    try:
        for toml in config_files(home, which):
            text = toml.read_text(encoding="utf-8") if toml.is_file() else ""
            try:
                import tomllib
                tomllib.loads(text)
            except ImportError:
                pass
            except Exception:
                return False, written, f"{toml.name} could not be read as settings - use Repair xemu settings first."
            new = set_section_values(text, "input", {"auto_bind": True})
            new = set_section_values(new, "input.bindings", {"port1_driver": PAD_DRIVER, "port1": guid})
            if new != text:
                if toml.is_file():
                    bak = toml.with_name(BACKUP_NAME)
                    if not bak.exists():
                        shutil.copyfile(toml, bak)
                _atomic_write(toml, new)
                written.append(str(toml))
    except OSError as exc:
        return False, written, f"Could not write xemu's settings: {exc.strerror or exc}"
    if not written:
        return True, written, "xemu already has this controller as player 1 - nothing needed changing."
    return True, written, "Player 1 is set. Close xemu first if it is open (it would overwrite the file when it closes)."
