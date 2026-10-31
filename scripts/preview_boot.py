"""Mock-ups of the GRUB menu and the Plymouth splash (frames + a short GIF), drawn the way theme.txt / codeaque.script place things.
The real look depends on GRUB / Plymouth on the computer. Usage: preview_boot.py [out_dir]"""
import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

A = Path(__file__).resolve().parent.parent / "atarilauncher" / "bootscreen"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
GOLD, DARK, LIGHT, DIM = (226, 182, 74), (20, 13, 2), (255, 233, 168), (189, 167, 114)


def grub(out, w=1920, h=1080):
    im = Image.open(A / f"background-{w}x{h}.png").convert("RGB")
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype(BOLD, int(36 * h / 1080 * 1.2))
    small = ImageFont.truetype(BOLD, int(20 * h / 1080 * 1.2))
    x0, y, iw, ih = int(w * 0.33), int(h * 0.76), int(w * 0.34), int(50 * h / 1080)
    for i, t in enumerate(("CodeAque", "Windows", "Advanced options for CodeAque")):
        sel = i == 0
        if sel:
            d.rectangle((x0, y, x0 + iw, y + ih), fill=(150, 116, 40), outline=GOLD, width=3)
        d.text((x0 + 18, y + ih / 2), t, font=f if i < 2 else small, fill=DARK if sel else (GOLD if i < 2 else DIM), anchor="lm")
        y += ih + int(8 * h / 1080)
    d.text((w / 2, h * 0.92), "Starting CodeAque in 5 s   -   Up / Down and Enter to choose",
           font=ImageFont.truetype(BOLD, int(24 * h / 1080)), fill=LIGHT, anchor="mt")
    im.save(out)


class Splash:
    def __init__(self, w=960, h=540, anim=True):
        self.w, self.h, self.anim = w, h, anim
        self.bg = Image.open(A / "background-1920x1080.png").convert("RGBA").resize((w, h), Image.LANCZOS)
        self.glow = Image.open(A / "code-glow.png").resize((w, h), Image.LANCZOS)
        rnd = random.Random(5)
        strips = [Image.open(A / f"rain-{j}.png") for j in range(6)]
        k = h / 1080
        self.strips = [s.resize((max(1, int(s.width * k)), int(s.height * k))) for s in strips]
        self.drops = []
        for j in range(24):
            cx = w * (0.02 + 0.28 * rnd.random()) if j % 2 == 0 else w * (0.70 + 0.28 * rnd.random())
            self.drops.append([cx, -self.strips[0].height - rnd.random() * h, (2 + rnd.random() * 4) * k, j % 6])
        self.f1 = ImageFont.truetype(BOLD, int(26 * k * 1.3))
        self.f2 = ImageFont.truetype(REG, int(16 * k * 1.3))

    def frame(self, t, progress):
        w, h = self.w, self.h
        im = self.bg.copy()
        if self.anim:
            layer = Image.new("RGBA", (w, h))
            for dr in self.drops:
                dr[1] += dr[2]
                if dr[1] > h:
                    dr[1] = -self.strips[0].height
                s = self.strips[dr[3]].copy()
                s.putalpha(s.getchannel("A").point(lambda v: int(v * 0.8)))
                layer.paste(s, (int(dr[0]), int(dr[1])), s)
            im.alpha_composite(layer)
        g = self.glow.copy()
        a = 0.25 + 0.35 * (0.5 + 0.5 * math.sin(t / 40))
        g.putalpha(self.glow.getchannel("A").point(lambda v: int(v * a)))
        im.alpha_composite(g)
        d = ImageDraw.Draw(im)
        d.text((w / 2, h * 0.765), "CODEAQUE  OS", font=self.f1, fill=GOLD, anchor="mt")
        d.text((w / 2, h * 0.815), "SYSTEM INITIALISING...", font=self.f2, fill=(212, 237, 217), anchor="mt")
        bw, bx, by = w * 0.34, w / 2 - w * 0.17, h * 0.865
        d.rectangle((bx, by, bx + bw, by + 6 * h / 1080 + 1), fill=(22, 40, 30))
        d.rectangle((bx, by, bx + bw * progress, by + 6 * h / 1080 + 1), fill=(60, 230, 110))
        r = 6 * h / 1080 + 2
        d.ellipse((bx + bw * progress - r, by - r / 2, bx + bw * progress + r, by + r * 1.5), fill=GOLD)
        return im.convert("RGB")


if __name__ == "__main__":
    o = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/branding")
    o.mkdir(parents=True, exist_ok=True)
    grub(o / "preview-grub-1920x1080.png")
    grub(o / "preview-grub-1366x768.png", 1366, 768)
    big = Splash(1920, 1080)
    for t in range(120):
        fr = big.frame(t, 0.6)
    fr.save(o / "preview-plymouth-1920x1080.png")
    Splash(1920, 1080, anim=False).frame(0, 0.6).save(o / "preview-plymouth-static-1920x1080.png")
    sp = Splash(640, 360)
    frames = [sp.frame(t, min(1.0, t / 140)) for t in range(0, 150)]
    frames[0].save(o / "preview-plymouth.gif", save_all=True, append_images=frames[1::2], duration=40, loop=0, optimize=True)
    print(o)
