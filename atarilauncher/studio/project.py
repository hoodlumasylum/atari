"""Studio projects: a folder in ~/Music/Atari Studio/<name>/ with project.json, the takes (WAV) and exports."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import beatgen, mixer, synth

LOOPS = 2                       # the beat is played this many times (4 bars x 2 = 8 bars) in previews and exports
COUNT_IN_BEATS = 4


def studio_dir() -> Path:
    return Path(os.environ.get("ATARI_STUDIO_DIR") or (Path.home() / "Music" / "Atari Studio"))


def safe_name(name: str) -> str:
    return re.sub(r"[^\w .-]+", "", name).strip(" .") or "My beat"


# ------------------------------------------------------------------ WAV files
def read_wav(path) -> "np.ndarray":
    """Any 16-bit PCM WAV -> mono float array at synth.SR (a simple resample if the rate differs)."""
    with wave.open(str(path)) as w:
        n, ch, width, rate = w.getnframes(), w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(n)
    if width != 2:
        raise ValueError("Only 16-bit WAV files are supported.")
    x = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    if rate != synth.SR and len(x):
        x = np.interp(np.linspace(0, len(x) - 1, int(len(x) * synth.SR / rate)), np.arange(len(x)), x)
    return x


def write_wav(path, stereo, rate: int = synth.SR) -> None:
    a = np.asarray(stereo)
    if a.ndim == 1:
        a = np.stack([a, a], axis=1)
    pcm = (np.clip(a, -1, 1) * 32767).astype("<i2")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def mp3_encoder(which=shutil.which) -> list[str] | None:
    """The command start for turning a WAV into an MP3 (ffmpeg, else lame), or None."""
    if which("ffmpeg"):
        return ["ffmpeg", "-y", "-loglevel", "error", "-i", "{wav}", "-codec:a", "libmp3lame", "-q:a", "2", "{mp3}"]
    if which("lame"):
        return ["lame", "--quiet", "-V2", "{wav}", "{mp3}"]
    return None


# ------------------------------------------------------------------ the project
@dataclass
class Take:
    file: str                 # relative to the project folder
    name: str = "Take"
    trim_start: float = 0.0   # seconds cut from the start / end (non-destructive: the file is never changed)
    trim_end: float = 0.0
    volume: float = 1.0
    pan: float = 0.0
    mute: bool = False
    preset: str = "vocal_clean"
    eq_low: float = 0.0
    eq_mid: float = 0.0
    eq_high: float = 0.0
    comp: float = 0.0


@dataclass
class Project:
    name: str = "My beat"
    pattern: beatgen.Pattern | None = None
    buses: dict = field(default_factory=lambda: {
        "Drums": {"volume": 0.8, "pan": 0.0, "mute": False, "preset": "none", "eq_low": 0, "eq_mid": 0, "eq_high": 0, "comp": 0},
        "808 bass": {"volume": 0.8, "pan": 0.0, "mute": False, "preset": "none", "eq_low": 0, "eq_mid": 0, "eq_high": 0, "comp": 0},
        "Chords": {"volume": 0.55, "pan": -0.2, "mute": False, "preset": "none", "eq_low": 0, "eq_mid": 0, "eq_high": 0, "comp": 0},
        "Melody": {"volume": 0.5, "pan": 0.25, "mute": False, "preset": "reverb", "eq_low": 0, "eq_mid": 0, "eq_high": 0, "comp": 0},
    })
    takes: list = field(default_factory=list)
    loudness: str = "normal"
    advanced: bool = False
    latency_ms: int = 90      # how late the microphone audio arrives compared with the beat (trimmed off every take)

    @property
    def folder(self) -> Path:
        return studio_dir() / safe_name(self.name)

    def to_dict(self) -> dict:
        return {"version": 1, "name": self.name, "pattern": self.pattern.to_dict() if self.pattern else None,
                "buses": self.buses, "takes": [t.__dict__ for t in self.takes], "loudness": self.loudness,
                "advanced": self.advanced, "latency_ms": self.latency_ms}

    @classmethod
    def from_dict(cls, d: dict) -> "Project":
        p = cls(str(d.get("name", "My beat")))
        if d.get("pattern"):
            p.pattern = beatgen.Pattern.from_dict(d["pattern"])
        for k, v in (d.get("buses") or {}).items():
            if k in p.buses and isinstance(v, dict):
                p.buses[k].update(v)
        for t in d.get("takes", []):
            if isinstance(t, dict) and t.get("file"):
                p.takes.append(Take(**{k: t[k] for k in Take.__dataclass_fields__ if k in t}))
        p.loudness = d.get("loudness", "normal") if d.get("loudness") in mixer.LOUDNESS else "normal"
        p.advanced = bool(d.get("advanced", False))
        p.latency_ms = int(d.get("latency_ms", 90))
        return p

    def save(self) -> Path:
        self.folder.mkdir(parents=True, exist_ok=True)
        f = self.folder / "project.json"
        tmp = f.with_name("project.json.tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        tmp.replace(f)
        return f

    @classmethod
    def load(cls, folder: Path) -> "Project":
        return cls.from_dict(json.loads((Path(folder) / "project.json").read_text(encoding="utf-8")))

    # -------------------------------------------------------------- audio
    def beat_seconds(self) -> float:
        p = self.pattern
        return p.total_steps * 60.0 / p.tempo / 4 * LOOPS if p else 0.0

    def take_audio(self, t: Take) -> "np.ndarray":
        x = read_wav(self.folder / t.file)
        start = int((t.trim_start + 0.0) * synth.SR)
        end = len(x) - int(t.trim_end * synth.SR)
        return x[start: max(start, end)]

    def channels(self, with_voice: bool = True) -> list:
        chs = []
        if self.pattern:
            for name, audio in synth.render_buses(self.pattern, LOOPS).items():
                chs.append(mixer.Channel(name, audio, **self.buses[name]))
        if with_voice:
            n = len(chs[0].audio) if chs else 0
            for t in self.takes:
                try:
                    x = self.take_audio(t)
                except (OSError, ValueError, wave.Error):
                    continue
                if n:
                    x = x[:n]
                chs.append(mixer.Channel(t.name, x, t.volume, t.pan, t.mute, t.preset, t.eq_low, t.eq_mid, t.eq_high, t.comp))
        return chs

    def render(self, with_voice: bool = True):
        tempo = self.pattern.tempo if self.pattern else 100
        return mixer.mixdown(self.channels(with_voice), tempo, self.loudness)

    def export(self, fmt: str = "wav", which=shutil.which, run=subprocess.run) -> Path:
        """Mix everything down into <project folder>/<name>.wav or .mp3 and return the path."""
        self.folder.mkdir(parents=True, exist_ok=True)
        wav = self.folder / f"{safe_name(self.name)}.wav"
        write_wav(wav, self.render())
        if fmt != "mp3":
            return wav
        enc = mp3_encoder(which)
        if enc is None:
            raise RuntimeError("MP3 needs ffmpeg or lame. Install one with:  sudo apt install ffmpeg   (the WAV was saved).")
        mp3 = wav.with_suffix(".mp3")
        r = run([a.replace("{wav}", str(wav)).replace("{mp3}", str(mp3)) for a in enc], capture_output=True, text=True)
        if r.returncode != 0 or not mp3.exists():
            raise RuntimeError("The MP3 could not be made (the WAV was saved). " + (r.stderr or "")[-200:])
        return mp3


def list_projects() -> list[Path]:
    root = studio_dir()
    try:
        return sorted((p for p in root.iterdir() if (p / "project.json").is_file()), key=lambda p: -(p / "project.json").stat().st_mtime)
    except OSError:
        return []


def auto_trim_silence(x, threshold_db: float = -45.0) -> tuple[float, float]:
    """(seconds of quiet to cut from the start, from the end) of a recording."""
    if len(x) == 0:
        return 0.0, 0.0
    block = synth.SR // 50
    n = len(x) // block
    if n == 0:
        return 0.0, 0.0
    lvl = 20 * np.log10(np.sqrt(np.mean(x[: n * block].reshape(n, block) ** 2, axis=1)) + 1e-9)
    loud = np.where(lvl > threshold_db)[0]
    if len(loud) == 0:
        return 0.0, 0.0
    keep_before = max(0, loud[0] - 3)                    # keep ~60 ms before the first sound
    keep_after = min(n, loud[-1] + 8)
    return keep_before * block / synth.SR, (len(x) - keep_after * block) / synth.SR
