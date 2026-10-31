"""Builds CodeAque's boot-screen pictures (GRUB backgrounds, selection bar, Plymouth glow / line) from the CodeAque logo.
Original art: a gradient, thin gold lines and the logo. Run: python scripts/make_boot_assets.py <logo.png> [out_dir]. Needs Pillow."""
import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

EMERALD_TOP, EMERALD_BOTTOM = (3, 18, 14), (6, 40, 31)
GOLD, EMERALD = (226, 182, 74), (34, 201, 140)


def gradient(w, h):
    im = Image.new("RGB", (w, h))
    px = im.load()
    for y in range(h):
        t = y / (h - 1)
        for x in range(w):
            r = math.hypot((x - w * 0.5) / w, (y - h * 0.42) / h)
            k = max(0.0, 1.0 - r * 1.6)
            c = [int(EMERALD_TOP[i] + (EMERALD_BOTTOM[i] - EMERALD_TOP[i]) * t + 18 * k * (i == 1) + 8 * k * (i == 2)) for i in range(3)]
            px[x, y] = tuple(c)
    return im


def circuits(w, h, seed=7):
    """Thin gold 'circuit' lines along the edges - Egyptian-cyberpunk feel, away from the text."""
    lay = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(lay)
    rnd = random.Random(seed)
    s = w / 1920
    for _ in range(34):
        side = rnd.choice(("l", "r"))
        x = rnd.uniform(0, w * 0.16) if side == "l" else rnd.uniform(w * 0.84, w)
        y = rnd.uniform(h * 0.05, h * 0.95)
        pts = [(x, y)]
        for _ in range(rnd.randint(2, 4)):
            if rnd.random() < 0.5:
                x += rnd.choice((-1, 1)) * rnd.uniform(30, 120) * s
            else:
                y += rnd.choice((-1, 1)) * rnd.uniform(30, 120) * s
            pts.append((x, y))
        col = tuple(int(c * rnd.uniform(0.25, 0.55)) for c in GOLD)
        d.line(pts, fill=col, width=max(1, int(2 * s)))
        ex, ey = pts[-1]
        r = 4 * s
        d.ellipse((ex - r, ey - r, ex + r, ey + r), outline=col, width=max(1, int(2 * s)))
    # a thin gold frame line top and bottom, and a stepped 'pyramid' line under the logo
    d.line((w * 0.2, h * 0.03, w * 0.8, h * 0.03), fill=tuple(int(c * 0.5) for c in GOLD), width=max(1, int(2 * s)))
    d.line((w * 0.2, h * 0.97, w * 0.8, h * 0.97), fill=tuple(int(c * 0.5) for c in GOLD), width=max(1, int(2 * s)))
    return lay


def logo_layer(logo, w, h, size_frac, cy_frac):
    size = int(h * size_frac)
    lg = logo.convert("RGB").resize((size, size), Image.LANCZOS)
    lay = Image.new("RGB", (w, h))
    lay.paste(lg, (w // 2 - size // 2, int(h * cy_frac) - size // 2))
    glow = lay.filter(ImageFilter.GaussianBlur(size * 0.06))
    glow = ImageChops.multiply(glow, Image.new("RGB", (w, h), GOLD))
    return ImageChops.lighter(lay, glow)


def grub_background(logo, w, h):
    im = gradient(w, h)
    im = ImageChops.lighter(im, circuits(w, h))
    im = ImageChops.lighter(im, logo_layer(logo, w, h, 0.36, 0.25))
    return im


def selection_bar(out: Path):
    """GRUB styled box 'select_*.png': a gold bar (9-slice: c, n, s, e, w and corners)."""
    for part, size in (("c", (8, 8)), ("n", (8, 3)), ("s", (8, 3)), ("e", (3, 8)), ("w", (3, 8)),
                       ("ne", (3, 3)), ("nw", (3, 3)), ("se", (3, 3)), ("sw", (3, 3))):
        col = (150, 116, 40) if part == "c" else GOLD
        Image.new("RGB", size, col).save(out / f"select_{part}.png")


def plymouth(logo, out: Path):
    lg = logo.convert("RGB").resize((420, 420), Image.LANCZOS)
    lg.save(out / "code-logo.png")
    mask = lg.convert("L").filter(ImageFilter.GaussianBlur(26)).point(lambda v: min(255, int(v * 1.8)))
    glow = Image.new("RGBA", (420, 420), GOLD + (0,))
    glow.putalpha(mask)
    big = Image.new("RGBA", (520, 520), GOLD + (0,))
    big.paste(glow, (50, 50))
    big.filter(ImageFilter.GaussianBlur(10)).save(out / "code-glow.png")
    Image.new("RGB", (8, 3), EMERALD).save(out / "code-line.png")


def preview_plymouth(logo, w=1920, h=1080, pulse=0.8, progress=0.55):
    im = Image.new("RGB", (w, h), (0, 0, 0))
    lg = logo.convert("RGB").resize((h // 3, h // 3), Image.LANCZOS)
    x, y = w // 2 - lg.width // 2, h // 2 - lg.height // 2
    halo = Image.new("RGB", (w, h))
    halo.paste(lg, (x, y))
    halo = ImageChops.multiply(halo.filter(ImageFilter.GaussianBlur(40)), Image.new("RGB", (w, h), tuple(int(c * pulse) for c in GOLD)))
    im = ImageChops.lighter(im, halo)
    im.paste(lg, (x, y), lg.convert("L").point(lambda v: 255 if v > 8 else v * 30))
    d = ImageDraw.Draw(im)
    lw = int(w * 0.3)
    d.rectangle((w // 2 - lw // 2, int(h * 0.78), w // 2 - lw // 2 + int(lw * progress), int(h * 0.78) + 3), fill=EMERALD)
    return im


LOGO_BOX = (0.10, 0.36, 0.90, 0.60)     # where the gold winged logo sits in the art (fractions)


def fit(art, w, h):
    """Cover w x h (crop the long side), LANCZOS + a light sharpen: the source is 1672x941, so 1920x1080 is a small upscale."""
    sw, sh = art.size
    k = max(w / sw, h / sh)
    im = art.resize((round(sw * k), round(sh * k)), Image.LANCZOS)
    l, t = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((l, t, l + w, t + h)).filter(ImageFilter.UnsharpMask(1.2, 60, 2))


def art_glow(art, out: Path):
    """A soft glow over the bright parts (the eyes, the gold logo, the ankh), the size of the whole picture at half resolution, so
    Plymouth pulses one sprite (cheap on old GPUs)."""
    small = art.resize((art.width // 2, art.height // 2), Image.LANCZOS)
    hsv = small.convert("HSV")
    lum = small.convert("L")
    bright = lum.point(lambda v: 255 if v > 165 else 0)
    glow = Image.new("RGBA", small.size)
    glow.paste(small.filter(ImageFilter.GaussianBlur(3)), (0, 0))
    glow.putalpha(bright.filter(ImageFilter.GaussianBlur(9)).point(lambda v: min(220, int(v * 1.6))))
    glow.save(out / "code-glow.png", optimize=True)
    del hsv


GLYPHS = 14


def glyph(d, kind, x, y, s, col):
    """Our own little symbols: 0 / 1 and simple hieroglyph-style marks (ankh, eye, wave, reed, sun, step) - drawn, not a font."""
    w = max(1, int(s / 7))
    if kind == 0:
        d.ellipse((x + s * .2, y + s * .1, x + s * .8, y + s * .9), outline=col, width=w)
    elif kind == 1:
        d.line((x + s * .5, y + s * .1, x + s * .5, y + s * .9), fill=col, width=w)
        d.line((x + s * .35, y + s * .25, x + s * .5, y + s * .1), fill=col, width=w)
    elif kind == 2:     # ankh
        d.ellipse((x + s * .32, y + s * .05, x + s * .68, y + s * .4), outline=col, width=w)
        d.line((x + s * .5, y + s * .4, x + s * .5, y + s * .95), fill=col, width=w)
        d.line((x + s * .2, y + s * .5, x + s * .8, y + s * .5), fill=col, width=w)
    elif kind == 3:     # eye
        d.arc((x + s * .1, y + s * .2, x + s * .9, y + s * .8), 200, 340, fill=col, width=w)
        d.arc((x + s * .1, y + s * .2, x + s * .9, y + s * .8), 20, 160, fill=col, width=w)
        d.ellipse((x + s * .42, y + s * .42, x + s * .58, y + s * .58), fill=col)
    elif kind == 4:     # water wave
        for k in range(3):
            d.line((x + s * (.1 + .27 * k), y + s * .55, x + s * (.23 + .27 * k), y + s * .4, x + s * (.37 + .27 * k), y + s * .55), fill=col, width=w)
    elif kind == 5:     # reed
        d.line((x + s * .5, y + s * .95, x + s * .5, y + s * .3), fill=col, width=w)
        d.line((x + s * .5, y + s * .3, x + s * .75, y + s * .1), fill=col, width=w)
    elif kind == 6:     # sun
        d.ellipse((x + s * .25, y + s * .25, x + s * .75, y + s * .75), outline=col, width=w)
        d.point((x + s * .5, y + s * .5), fill=col)
    else:               # steps
        d.line((x + s * .1, y + s * .9, x + s * .1, y + s * .65, x + s * .4, y + s * .65, x + s * .4, y + s * .4, x + s * .7, y + s * .4,
                x + s * .7, y + s * .15, x + s * .9, y + s * .15), fill=col, width=w)


def rain(out: Path, columns=6, s=18, length=22):
    """A few tall column strips of falling symbols with a bright head and a fading tail. Plymouth moves ~24 sprites of these down the
    screen (no per-frame drawing)."""
    rnd = random.Random(3)
    for c in range(columns):
        im = Image.new("RGBA", (s, s * length), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        for i in range(length):
            k = i / (length - 1)                       # 0 = top of the tail, 1 = the head
            kind = rnd.choice((0, 1, 0, 1, 2, 3, 4, 5, 6, 7))
            col = (200, 255, 210, 255) if i == length - 1 else (40, 220, 110, int(30 + 200 * k ** 1.6))
            glyph(d, kind, 0, i * s, s, col)
        im.save(out / f"rain-{c}.png", optimize=True)


def spinner(out: Path, n=12, size=64):
    for f in range(n):
        im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        for i in range(n):
            a = 2 * math.pi * i / n
            x, y = size / 2 + math.cos(a) * size * 0.38, size / 2 + math.sin(a) * size * 0.38
            k = ((i - f) % n) / n
            r = size * 0.055 + size * 0.03 * (1 - k)
            d.ellipse((x - r, y - r, x + r, y + r), fill=EMERALD + (int(255 * (1 - k) ** 1.5) + 20,))
        im.save(out / f"spin-{f:02d}.png")


def main():
    art = Image.open(sys.argv[1]).convert("RGB")       # the cleaned boot art (scripts/clean_boot_art.py)
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "atarilauncher/bootscreen")
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()
    for w, h in ((1920, 1080), (1366, 768)):
        fit(art, w, h).save(out / f"background-{w}x{h}.png", optimize=True)
    selection_bar(out)
    art_glow(art, out)
    rain(out)
    Image.new("RGB", (8, 4), (60, 230, 110)).save(out / "code-line.png")
    Image.new("RGB", (8, 4), (22, 40, 30)).save(out / "code-track.png")
    hd = Image.new("RGBA", (12, 12), (0, 0, 0, 0))
    ImageDraw.Draw(hd).ellipse((0, 0, 11, 11), fill=GOLD + (255,))
    hd.filter(ImageFilter.GaussianBlur(1)).save(out / "code-head.png")
    print("written to", out)


if __name__ == "__main__":
    main()
