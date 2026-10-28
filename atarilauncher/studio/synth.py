"""Original sound synthesis for the Studio (numpy only). No samples: every drum, bass and keyboard sound is a formula."""
from __future__ import annotations

import numpy as np

from .beatgen import BUSES, STEPS, Pattern

SR = 44100


def _t(sec: float) -> "np.ndarray":
    return np.arange(int(sec * SR)) / SR


def _rng(seed: int = 1):
    return np.random.default_rng(seed)


def hp(x, amount: int = 2):
    """A cheap high-pass: differences remove low frequencies (more passes = thinner)."""
    for _ in range(amount):
        x = np.concatenate([[0.0], np.diff(x)])
    return x


def kick(punch: float = 1.0):
    t = _t(0.42)
    f = 45 + 95 * np.exp(-t * 28)
    ph = 2 * np.pi * np.cumsum(f) / SR
    body = np.sin(ph) * np.exp(-t * 7.5)
    click = _rng(2).standard_normal(len(t)) * np.exp(-t * 300) * 0.25 * punch
    return np.tanh((body + click) * 1.6) * 0.95


def snare():
    t = _t(0.28)
    noise = hp(_rng(3).standard_normal(len(t)), 1) * np.exp(-t * 20)
    tone = np.sin(2 * np.pi * (185 + 40 * np.exp(-t * 40)) * t) * np.exp(-t * 26)
    return _peak(np.tanh(noise * 0.55 + tone * 0.9), 0.8)


def clap():
    t = _t(0.3)
    n = hp(_rng(4).standard_normal(len(t)), 1)
    env = np.zeros(len(t))
    for off in (0.0, 0.011, 0.022):
        env += np.exp(-np.clip(t - off, 0, None) * 120) * (t >= off)
    env += np.exp(-np.clip(t - 0.032, 0, None) * 22) * (t >= 0.032) * 0.7
    return _peak(np.tanh(n * env * 0.7), 0.75)


def _peak(x, level: float):
    m = float(np.max(np.abs(x))) or 1.0
    return x * (level / m)


def hat(open_: bool = False):
    t = _t(0.3 if open_ else 0.06)
    n = hp(_rng(5 if open_ else 6).standard_normal(len(t)), 2)
    return _peak(n * np.exp(-t * (14 if open_ else 70)), 0.45 if open_ else 0.6)


def bass808(midi: int, length_s: float, drive: float = 1.5, glide_from: int | None = None):
    n = int((length_s + 0.25) * SR)
    t = np.arange(n) / SR
    f = 440.0 * 2 ** ((midi - 69) / 12)
    f0 = f * 2 ** ((glide_from - midi) / 12) if glide_from is not None else f
    glide = f + (f0 - f) * np.exp(-t * 18) + f * 0.5 * np.exp(-t * 60)          # tiny pitch drop = the 808 "thump"
    ph = 2 * np.pi * np.cumsum(glide) / SR
    env = np.minimum(1.0, t / 0.004) * np.exp(-np.clip(t - length_s, 0, None) * 18) * np.exp(-t * 1.2)
    return np.tanh(np.sin(ph) * env * drive) * 0.9


def keys(midi: int, length_s: float):
    """A soft electric-piano-like tone: a few decaying harmonics."""
    n = int((length_s + 0.4) * SR)
    t = np.arange(n) / SR
    f = 440.0 * 2 ** ((midi - 69) / 12)
    out = np.zeros(n)
    for k, (amp, dec) in enumerate(((1.0, 2.2), (0.45, 3.5), (0.2, 5.0), (0.08, 7.0)), start=1):
        out += amp * np.sin(2 * np.pi * f * k * t + 0.4 * k) * np.exp(-t * dec)
    env = np.minimum(1.0, t / 0.006) * np.exp(-np.clip(t - length_s, 0, None) * 9)
    return out * env * 0.22


def pluck(midi: int, length_s: float):
    n = int((length_s + 0.2) * SR)
    t = np.arange(n) / SR
    f = 440.0 * 2 ** ((midi - 69) / 12)
    wave = np.sin(2 * np.pi * f * t) + 0.3 * np.sin(4 * np.pi * f * t) * np.exp(-t * 12) + 0.1 * np.sin(6 * np.pi * f * t)
    env = np.minimum(1.0, t / 0.004) * np.exp(-t * 5.5) * np.exp(-np.clip(t - length_s, 0, None) * 14)
    return wave * env * 0.3


def _add(buf, sample, at: int, gain: float = 1.0):
    if at >= len(buf):
        return
    end = min(len(buf), at + len(sample))
    buf[at:end] += sample[: end - at] * gain


def render_tracks(p: Pattern, loops: int = 1) -> dict:
    """Render each pattern track to a mono float array ({name: array}); all are the same length."""
    step_s = 60.0 / p.tempo / 4
    total = int(p.total_steps * step_s * SR * loops) + int(0.6 * SR)       # a little tail for the last sounds to ring out
    out = {n: np.zeros(total, dtype=np.float64) for n in p.tracks}
    drive = 1.2 + 1.8 * p.vibe
    shots = {"kick": kick(0.7 + 0.6 * p.vibe), "snare": snare(), "clap": clap(), "hat": hat(), "ohat": hat(True)}

    def start(step: int, loop: int) -> int:
        swing = p.swing * step_s if step % 2 == 1 else 0.0
        return int(((step + loop * p.total_steps) * step_s + swing) * SR)

    for loop in range(loops):
        for name, notes in p.tracks.items():
            for i, n in enumerate(notes):
                at = start(n.step, loop)
                dur = n.length * step_s
                if name in shots:
                    _add(out[name], shots[name], at, n.vel)
                elif name == "bass808":
                    prev = notes[i - 1].midi if i > 0 and notes[i - 1].step // STEPS == n.step // STEPS else None
                    glide = prev if (prev is not None and prev != n.midi) else None
                    _add(out[name], bass808(n.midi, dur, drive, glide), at, n.vel)
                elif name == "chords":
                    _add(out[name], keys(n.midi, dur), at, n.vel)
                elif name == "melody":
                    _add(out[name], pluck(n.midi, dur), at, n.vel)
    return out


def render_buses(p: Pattern, loops: int = 1) -> dict:
    """The four mixer channels of a beat: Drums, 808 bass, Chords, Melody."""
    tr = render_tracks(p, loops)
    return {bus: sum((tr[t] for t in names if t in tr), np.zeros_like(next(iter(tr.values())))) for bus, names in BUSES.items()}


def countin(tempo: int, beats: int = 4):
    """A bar of clicks to count you in (the same little tick sound as the menus, rendered here so the beat stays in time)."""
    beat = 60.0 / tempo
    out = np.zeros(int(beat * beats * SR) + 2000)
    t = _t(0.05)
    for b in range(beats):
        click = np.sin(2 * np.pi * (1800 if b == 0 else 1200) * t) * np.exp(-t * 60) * 0.7
        _add(out, click, int(b * beat * SR))
    return out
