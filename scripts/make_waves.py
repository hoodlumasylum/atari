#!/usr/bin/env python3
"""Draws the two soft, tileable wave pictures behind Code's main screen (original artwork, standard library only).

    python3 scripts/make_waves.py      # writes atarilauncher/assets/wave1.png and wave2.png

Both wrap around seamlessly: Code slides two copies sideways, which costs the GPU almost nothing.
"""
import math
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "atarilauncher" / "assets"
W, H = 960, 220


def png(path, rows):
    raw = b"".join(b"\x00" + bytes(r) for r in rows)

    def chunk(kind, data):
        c = struct.pack(">I", len(data)) + kind + data
        return c + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 6, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def wave(path, color, cycles, phase, second, base):
    rows = [[0] * (W * 4) for _ in range(H)]
    for x in range(W):
        t = 2 * math.pi * x / W
        crest = H * (base + 0.13 * math.sin(cycles * t + phase) + 0.05 * math.sin(second * t + 1.3 * phase))
        for y in range(H):
            d = y - crest
            if d < 0:
                a = 0.0
            else:
                a = 0.30 * math.exp(-d / 48.0)                         # glow under the crest, fading downwards
            line = math.exp(-(d * d) / 3.0)                            # a thin bright line along the crest
            a = min(1.0, a + 0.75 * line)
            i = x * 4
            rows[y][i:i + 4] = [color[0], color[1], color[2], int(a * 255)]
    png(path, rows)


if __name__ == "__main__":
    wave(OUT / "wave1.png", (224, 40, 52), 2, 0.0, 5, 0.45)
    wave(OUT / "wave2.png", (110, 90, 230), 3, 2.1, 7, 0.55)
    for n in ("wave1.png", "wave2.png"):
        print(n, (OUT / n).stat().st_size // 1024, "KB")
