"""Mixing: per-track volume / pan / mute, one-click presets, master loudness, optional EQ + compressor. numpy only."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .synth import SR

PRESETS = {
    "none": "No effect",
    "vocal_clean": "Vocal clean (tidy low end, gentle squeeze, a little sparkle)",
    "reverb": "Reverb (a roomy space)",
    "echo": "Echo (repeats that fade)",
    "vocal_space": "Vocal clean + reverb",
}
LOUDNESS = {"quiet": -20.0, "normal": -16.0, "loud": -12.0}      # target RMS in dBFS; the peak is always kept below -1 dBFS
PRESET_ORDER = list(PRESETS)


@dataclass
class Channel:
    name: str
    audio: "np.ndarray"          # mono, float
    volume: float = 0.8          # 0 .. 1.5
    pan: float = 0.0             # -1 (left) .. +1 (right)
    mute: bool = False
    preset: str = "none"
    eq_low: float = 0.0          # dB (advanced)
    eq_mid: float = 0.0
    eq_high: float = 0.0
    comp: float = 0.0            # 0 .. 1 (advanced)


def db(x: float) -> float:
    return 10 ** (x / 20.0)


def _fft_gain(x, gain_fn):
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(len(x), 1 / SR)
    return np.fft.irfft(spec * gain_fn(freqs), len(x))


def eq3(x, low_db=0.0, mid_db=0.0, high_db=0.0):
    """Three bands (below 250 Hz / 250 Hz - 4 kHz / above 4 kHz) with smooth edges."""
    if not (low_db or mid_db or high_db) or len(x) == 0:
        return x

    def g(f):
        lo = 1 / (1 + (f / 250.0) ** 4)
        hi = 1 / (1 + (4000.0 / np.maximum(f, 1.0)) ** 4)
        mid = 1 - lo - hi
        return db(low_db) * lo + db(mid_db) * mid + db(high_db) * hi
    return _fft_gain(x, g)


def highpass(x, cutoff=90.0):
    return _fft_gain(x, lambda f: 1 / (1 + (cutoff / np.maximum(f, 1.0)) ** 4)) if len(x) else x


def presence(x, amount_db=3.0):
    return _fft_gain(x, lambda f: 1 + (db(amount_db) - 1) * np.exp(-((f - 4000.0) / 2500.0) ** 2)) if len(x) else x


def compress(x, amount=0.5, threshold_db=-24.0):
    """A simple feed-forward compressor: block loudness -> gain reduction -> smoothed -> applied. 'amount' 0..1."""
    if amount <= 0 or len(x) < SR // 50:
        return x
    block = SR // 100
    n = len(x) // block
    rms = np.sqrt(np.mean(x[: n * block].reshape(n, block) ** 2, axis=1)) + 1e-9
    lvl = 20 * np.log10(rms)
    ratio = 1.5 + 5.5 * amount
    over = np.maximum(lvl - threshold_db, 0.0)
    gain_db = -(over - over / ratio)
    gain_db = np.convolve(np.pad(gain_db, 3, mode="edge"), np.ones(7) / 7, mode="valid")
    gain = np.interp(np.arange(len(x)), (np.arange(n) + 0.5) * block, db(gain_db))
    return x * gain * db(amount * 6.0 * 0.5)                               # a little make-up gain


def reverb(x, wet=0.28, seconds=1.4):
    n = int(seconds * SR)
    t = np.arange(n) / SR
    ir = np.random.default_rng(11).standard_normal(n) * np.exp(-t * 4.2)
    ir = np.convolve(ir, np.ones(8) / 8, mode="same")                      # softens the very top
    size = 1 << int(np.ceil(np.log2(len(x) + n)))
    y = np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(ir, size), size)[: len(x)]
    y *= np.max(np.abs(x) + 1e-9) / (np.max(np.abs(y)) + 1e-9) * 0.9
    return x * (1 - wet * 0.5) + y * wet


def echo(x, tempo=100, wet=0.35, feedback=0.4, taps=4):
    d = int(60.0 / tempo * 0.75 * SR)                                       # a dotted eighth: the classic echo
    y = x.copy()
    gain = wet
    for k in range(1, taps + 1):
        if k * d >= len(x):
            break
        y[k * d:] += x[: len(x) - k * d] * gain
        gain *= feedback / 0.4 * 0.4
    return y


def apply_preset(x, preset: str, tempo: int = 100):
    if preset == "vocal_clean":
        return presence(compress(highpass(x, 90), 0.4), 3.0)
    if preset == "vocal_space":
        return reverb(presence(compress(highpass(x, 90), 0.4), 3.0), 0.22)
    if preset == "reverb":
        return reverb(x)
    if preset == "echo":
        return echo(x, tempo)
    return x


def process(ch: Channel, tempo: int = 100):
    x = apply_preset(ch.audio, ch.preset, tempo)
    x = eq3(x, ch.eq_low, ch.eq_mid, ch.eq_high)
    return compress(x, ch.comp) if ch.comp else x


def to_stereo(x, volume, pan):
    """Equal-power pan."""
    a = (pan + 1) * np.pi / 4
    return np.stack([x * volume * np.cos(a), x * volume * np.sin(a)], axis=1)


def master(stereo, loudness: str = "normal"):
    """Bring the mix to the chosen loudness, then a soft limiter keeps every peak under -1 dBFS (no harsh clipping)."""
    if len(stereo) == 0:
        return stereo.astype(np.float32)
    rms = float(np.sqrt(np.mean(stereo ** 2))) + 1e-9
    target = db(LOUDNESS.get(loudness, LOUDNESS["normal"]))
    y = stereo * min(target / rms, 40.0)
    ceiling = db(-1.0)
    y = np.tanh(y / ceiling) * ceiling
    peak = float(np.max(np.abs(y))) + 1e-9
    if peak > ceiling:
        y *= ceiling / peak
    return y.astype(np.float32)


def mixdown(channels: list, tempo: int = 100, loudness: str = "normal"):
    """Mix every channel (muted ones skipped) to a stereo float32 array at the master loudness."""
    live = [c for c in channels if not c.mute and len(c.audio)]
    n = max((len(c.audio) for c in live), default=0)
    mix = np.zeros((n, 2))
    for c in live:
        x = process(c, tempo)
        mix[: len(x)] += to_stereo(x, c.volume, c.pan)[: n]
    return master(mix, loudness)


def rms_db(stereo) -> float:
    return 20 * np.log10(float(np.sqrt(np.mean(np.asarray(stereo, dtype=np.float64) ** 2))) + 1e-12)
