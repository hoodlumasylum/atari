"""Cleans Code's final boot art (codeaque-boot-art-final.png, 1671x941):
* paints out the green four-pane window shape in the middle (too close to Microsoft's logo) and puts an ORIGINAL glowing gold-and-green
  ankh made of our own falling-code glyphs in the same spot, at a similar size;
* paints out the baked-in "CODEAQUE OS / SYSTEM INITIALISING..." text and the progress bar (they are live in Plymouth now).
Needs atarilauncher/bootscreen/rain-*.png? No - it draws its own glyphs (make_boot_assets.glyph). Usage: clean_boot_art.py <in> <out>"""
import random
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_boot_assets import glyph  # noqa: E402

im = Image.open(sys.argv[1]).convert("RGB")
W, H = im.size
rnd = random.Random(11)


def fill_box(img, x0, x1, y0, y1, dim):
    px = img.load()
    f = img.copy()
    po = f.load()
    for y in range(y0, y1):
        L = [sum(px[x0 - k, y][i] for k in range(1, 9)) / 8 for i in range(3)]
        R = [sum(px[x1 + k, y][i] for k in range(1, 9)) / 8 for i in range(3)]
        for x in range(x0, x1):
            t = (x - x0) / (x1 - x0)
            po[x, y] = tuple(max(0, min(255, int(L[i] * (1 - t) + R[i] * t))) for i in range(3))
    patch = ImageEnhance.Brightness(f.filter(ImageFilter.GaussianBlur(8))).enhance(dim)
    m = Image.new("L", img.size, 0)
    ImageDraw.Draw(m).rectangle((x0 + 6, y0 + 4, x1 - 6, y1 - 4), fill=255)
    return Image.composite(patch, img, m.filter(ImageFilter.GaussianBlur(7)))


out = fill_box(im, 640, 1035, 418, 712, 0.30)          # the four-pane shape
out = fill_box(out, 495, 1180, 708, 866, 0.40)         # text + bar


# faint falling-code columns over the painted area, so it matches the rest of the art
lay = Image.new("RGBA", im.size, (0, 0, 0, 0))
d = ImageDraw.Draw(lay)
s = 13
for _ in range(26):
    x = rnd.uniform(520, 1150)
    y = rnd.uniform(400, 700)
    n = rnd.randint(5, 14)
    for i in range(n):
        a = int(25 + 110 * (i / n) ** 1.5)
        glyph(d, rnd.choice((0, 1, 0, 1, 2, 3, 4, 5, 6, 7)), x, y + i * s, s, (40, 220, 110, a))
out = Image.alpha_composite(out.convert("RGBA"), lay)

# the ankh made of glyphs: a mask of the ankh shape, filled with a grid of small glyphs (green, gold at the edges), plus a glow
cx, top, AW, AH = 837, 425, 250, 285
mask = Image.new("L", im.size, 0)
md = ImageDraw.Draw(mask)
loop_w, loop_h, t = AW * 0.46, AH * 0.40, 30
md.ellipse((cx - loop_w / 2, top, cx + loop_w / 2, top + loop_h), fill=255)
md.ellipse((cx - loop_w / 2 + t, top + t, cx + loop_w / 2 - t, top + loop_h - t), fill=0)
bar_y = top + loop_h - 6
md.rectangle((cx - AW / 2, bar_y, cx + AW / 2, bar_y + t), fill=255)
md.rectangle((cx - t / 2, bar_y, cx + t / 2, top + AH), fill=255)
edge = ImageChops.subtract(mask, mask.filter(ImageFilter.MinFilter(7)))
ank = Image.new("RGBA", im.size, (0, 0, 0, 0))
ad = ImageDraw.Draw(ank)
g = 9
mp, ep = mask.load(), edge.load()
for y in range(int(top), int(top + AH), g):
    for x in range(int(cx - AW / 2), int(cx + AW / 2), g):
        if mp[x + g // 2, y + g // 2] > 128:
            gold = ep[x + g // 2, y + g // 2] > 0 or rnd.random() < 0.18
            col = (240, 196, 84, 255) if gold else (70, 255, 140, 235)
            glyph(ad, rnd.choice((0, 1, 2, 3, 4, 5, 6, 7)), x, y, g, col)
glow_g = Image.new("RGBA", im.size, (40, 230, 110, 0))
glow_g.putalpha(mask.filter(ImageFilter.GaussianBlur(18)).point(lambda v: int(v * 0.75)))
glow_y = Image.new("RGBA", im.size, (226, 182, 74, 0))
glow_y.putalpha(mask.filter(ImageFilter.GaussianBlur(5)).point(lambda v: int(v * 0.35)))
out = Image.alpha_composite(Image.alpha_composite(Image.alpha_composite(out, glow_g), glow_y), ank)
out.convert("RGB").save(sys.argv[2])
