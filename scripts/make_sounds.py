#!/usr/bin/env python3
"""Synthesises Code's UI sounds from scratch (sine waves, noise and envelopes - no samples, nothing from anyone else).

    python3 scripts/make_sounds.py            # writes atarilauncher/assets/sfx/*.wav

The files are small (mono, 16-bit) and are committed, so users never need to run this. Uses only the standard library
(numpy would also work, but is not needed for sounds this short).
"""
import math
import random
import struct
import wave
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "atarilauncher" / "assets" / "sfx"
SR = 22050


def env(n, attack=0.004, release=0.05):
    a, r = max(1, int(attack * SR)), max(1, int(release * SR))
    return [min(1.0, i / a, (n - i) / r) for i in range(n)]


def tone(freq, dur, amp=0.4, decay=6.0, harm=(1.0, 0.25, 0.08), start=0.0, sweep_to=None):
    n = int(dur * SR)
    e = env(n)
    out = []
    ph = 0.0
    for i in range(n):
        t = i / SR
        f = freq if sweep_to is None else freq + (sweep_to - freq) * (i / n)
        ph += 2 * math.pi * f / SR
        v = sum(h * math.sin(ph * (k + 1)) for k, h in enumerate(harm)) / sum(harm)
        out.append(v * amp * math.exp(-decay * t) * e[i])
    return [0.0] * int(start * SR) + out


def mix(*tracks):
    n = max(len(t) for t in tracks)
    out = [0.0] * n
    for t in tracks:
        for i, v in enumerate(t):
            out[i] += v
    return out


def whoosh(dur=0.65, amp=0.5):
    random.seed(7)                                   # the same file every time
    n = int(dur * SR)
    out, lp = [], 0.0
    for i in range(n):
        x = i / n
        cutoff = 0.02 + 0.55 * math.sin(math.pi * x) ** 2            # the band opens, then closes
        lp += cutoff * (random.uniform(-1, 1) - lp)
        out.append(lp * amp * math.sin(math.pi * x) ** 1.5)
    sweep = tone(180, dur, amp=0.25, decay=1.5, harm=(1.0,), sweep_to=900)
    return mix(out, sweep)


def ambient(dur=8.0, amp=0.5):
    """A soft pad that loops without a click: every pitch and slow wobble fits a whole number of times into 8 seconds."""
    sr = 11025
    n = int(dur * sr)
    out = []
    for i in range(n):
        t = i / sr
        v = 0.0
        for f, a, wob in ((110.0, 0.5, 1 / 8), (165.0, 0.3, 2 / 8), (220.0, 0.25, 3 / 8), (277.5, 0.12, 1 / 8)):
            v += a * math.sin(2 * math.pi * f * t) * (0.65 + 0.35 * math.sin(2 * math.pi * wob * t))
        out.append(v * amp * 0.45)
    return out, sr


def intro(dur=3.6):
    """The start-up sound: a soft rising chord that blooms, a little shimmer, then fades out. Original, ~3.6 s."""
    n = int(dur * SR)
    notes = ((261.63, 0.05), (329.63, 0.35), (392.0, 0.65), (523.25, 0.95))
    parts = []
    for f, t0 in notes:
        parts.append(tone(f, dur - t0 - 0.2, amp=0.22, decay=1.1, harm=(1.0, 0.3, 0.1), start=t0))
    parts.append(tone(1046.5, 1.8, amp=0.12, decay=2.2, harm=(1.0, 0.1), start=1.25))
    parts.append(tone(1568.0, 1.4, amp=0.08, decay=2.6, harm=(1.0,), start=1.55))
    low = tone(65.4, dur, amp=0.18, decay=0.55, harm=(1.0, 0.2))
    out = mix(*parts, low)
    out = out[:n] + [0.0] * max(0, n - len(out))
    for i in range(int(0.5 * SR)):               # fade out
        out[n - 1 - i] *= i / (0.5 * SR)
    return [(out[i] + out[i + 1]) / 2 for i in range(0, n - 1, 2)]      # half the sample rate = half the size


def write(name, samples, peak=0.85, sr=SR):
    m = max(1e-9, max(abs(s) for s in samples))
    k = min(1.0, peak / m) if name != "ambient" else peak / m
    OUT.mkdir(parents=True, exist_ok=True)
    with wave.open(str(OUT / f"{name}.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, s * k)) * 32767)) for s in samples))


def main():
    write("tick", tone(1900, 0.035, amp=0.5, decay=70, harm=(1.0, 0.2)))
    write("select", mix(tone(660, 0.16, decay=9), tone(990, 0.16, decay=9, start=0.06)))
    write("back", mix(tone(620, 0.12, decay=10), tone(440, 0.14, decay=10, start=0.05)))
    write("fav", mix(tone(880, 0.1, decay=12, start=0.0), tone(1320, 0.1, decay=12, start=0.07),
                     tone(1760, 0.2, decay=9, start=0.14)))
    write("launch", whoosh())
    write("error", mix(tone(220, 0.14, decay=8, harm=(1.0, 0.6, 0.4, 0.3)),
                       tone(165, 0.22, decay=7, harm=(1.0, 0.6, 0.4, 0.3), start=0.13)))
    write("start", mix(tone(523.25, 1.4, amp=0.3, decay=2.6), tone(659.25, 1.4, amp=0.3, decay=2.6, start=0.12),
                       tone(783.99, 1.4, amp=0.3, decay=2.6, start=0.24), tone(1046.5, 1.6, amp=0.3, decay=2.2, start=0.36)))
    write("intro", intro(), peak=0.6, sr=SR // 2)
    pad, sr = ambient()
    write("ambient", pad, peak=0.6, sr=sr)
    for p in sorted(OUT.glob("*.wav")):
        print(f"{p.name:14} {p.stat().st_size // 1024:4d} KB")


if __name__ == "__main__":
    main()
