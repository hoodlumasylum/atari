"""Builds every CodeAque picture from the owner's logo (needs Pillow; a developer tool, not used at run time).

    python3 scripts/make_brand_assets.py /path/to/codeaque-logo.png

The source is a black-background PNG (1254 px). Black is turned into transparency (the outside glow stays soft, the dark body stays
solid), then: atarilauncher/assets/codeaque-logo.png (in-app logo, Plymouth), codeaque-icon.png (the Anubis head, for small sizes),
packaging/icons/code-<n>.png + atari-launcher.svg (app icon), docs/branding/* (banner, transparent logo, cut line, original)."""
import base64
import io
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent


def matte(src: Image.Image) -> tuple[Image.Image, Image.Image]:
    src = src.convert("RGB")
    w, h = src.size
    mx = ImageChops.lighter(ImageChops.lighter(src.getchannel("R"), src.getchannel("G")), src.getchannel("B"))
    th = mx.point(lambda v: 255 if v > 14 else 0).filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.MinFilter(9))
    fill = th.copy()
    for pt in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1), (w // 2, 0), (w // 2, h - 1), (0, h // 2), (w - 1, h // 2)):
        if fill.getpixel(pt) == 0:
            ImageDraw.floodfill(fill, pt, 128)
    inside = fill.point(lambda v: 0 if v == 128 else 255)
    glow = mx.point(lambda v: min(255, int(v * 1.6)))
    alpha = ImageChops.lighter(glow, inside.filter(ImageFilter.GaussianBlur(1.2)))
    r, g, b = src.split()
    return Image.merge("RGBA", (r, g, b, alpha)), inside


def save(im: Image.Image, path: Path, size: int | None = None) -> None:
    if size:
        im = im.resize((size, int(im.height * size / im.width)), Image.LANCZOS)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, optimize=True)
    print("wrote", path.relative_to(ROOT), im.size)


def main(src_path: str) -> None:
    src = Image.open(src_path)
    full, inside = matte(src)
    w = full.width
    icon = full.crop((int(w * 0.241), 0, int(w * 0.759), int(w * 0.518)))
    icon = icon.crop((0, 0, icon.width, icon.width)) if icon.height >= icon.width else icon.resize((icon.width, icon.width))
    assets = ROOT / "atarilauncher" / "assets"
    save(full, assets / "codeaque-logo.png", 800)
    save(icon, assets / "codeaque-icon.png", 512)
    for n in (512, 256, 128, 64):
        save(icon, ROOT / "packaging" / "icons" / f"code-{n}.png", n)
    buf = io.BytesIO()
    icon.resize((256, 256), Image.LANCZOS).save(buf, "PNG", optimize=True)
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 256 256" width="256" height="256">\n'
           '  <!-- The CodeAque logo (original artwork by the project owner), embedded as PNG so every desktop can show it. -->\n'
           '  <image width="256" height="256" xlink:href="data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode() + '"/>\n</svg>\n')
    (ROOT / "packaging" / "atari-launcher.svg").write_text(svg, encoding="utf-8")
    brand = ROOT / "docs" / "branding"
    shutil.copyfile(src_path, brand / "codeaque-logo-source.png")
    save(full, brand / "codeaque-logo.png")
    # banner: the logo on the dark app background
    banner = Image.new("RGBA", (1280, 420), (5, 6, 11, 255))
    small = full.resize((400, 400), Image.LANCZOS)
    banner.alpha_composite(small, (440, 10))
    save(banner.convert("RGB"), brand / "codeaque-banner.png")
    # one-colour cut line: the solid outline of the emblem (black on transparent) - a starting point for a sticker contour, not a finished sticker
    cut = Image.new("RGBA", full.size, (0, 0, 0, 0))
    cut.paste((0, 0, 0, 255), mask=inside)
    save(cut, brand / "codeaque-cutline.png", 2000)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/workspace/branding-assets/codeaque-logo.png")
