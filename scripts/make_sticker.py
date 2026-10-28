"""Builds docs/branding/code-sticker.svg (+ high-res PNG): a simplified ONE-colour (black on transparent) redraw of the
Code emblem - winged crest, CODE with an ankh for the O, chevron - for metal transfer / vinyl stickers.
Solid shapes only (no gradients, no hairlines, no strokes), every gap at least ~2% of the width so it cuts and prints cleanly.
It is an original redraw, not a trace of the AI-generated colour logo.   Run:  python scripts/make_sticker.py"""
import math
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "docs" / "branding"
CX = 505.0


def feather(bx, by, ang, length, mirror=False):
    a = -ang if mirror else ang
    return (f'<path transform="translate({bx} {by}) rotate({a})" '
            f'd="M-24 0 L24 0 L24 {-length + 34:.0f} L0 {-length:.0f} L-24 {-length + 34:.0f} Z"/>')


def svg() -> str:
    parts = []
    # wings: 5 blades each side fanning from behind the letters
    wings = [(-28, 270), (-46, 290), (-64, 280), (-82, 245), (-98, 190)]
    for ang, ln in wings:
        parts.append(feather(300, 345, ang, ln))
        parts.append(feather(2 * CX - 300, 345, ang, ln, mirror=True))
    # crown
    parts.append('<path d="M425 292 L438 196 L478 246 L505 160 L532 246 L572 196 L585 292 Z"/>')
    # letters (angular, filled)
    parts.append('<path d="M230 330 H110 L50 390 V530 L110 590 H230 V524 H130 L116 510 V410 L130 396 H230 Z"/>')   # C
    parts.append('<path fill-rule="evenodd" d="M560 330 H660 L740 400 V520 L670 590 H560 Z M626 396 V524 H650 L674 500 V420 L650 396 Z"/>')  # D
    parts.append('<path d="M780 330 H960 V396 H846 V428 H940 V490 H846 V524 H960 V590 H780 Z"/>')                  # E
    # ankh = the O
    parts.append('<path fill-rule="evenodd" d="M425 308 a78 92 0 1 0 0.01 0 Z M425 352 a36 48 0 1 1 -0.01 0 Z"/>')
    parts.append('<rect x="345" y="480" width="160" height="54" rx="6"/>')
    parts.append('<rect x="397" y="480" width="56" height="150" rx="6"/>')
    # chevron under the word
    parts.append('<path d="M330 640 L505 800 L680 640 L610 640 L505 735 L400 640 Z"/>')
    body = "\n  ".join(parts)
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1010 830" width="1010" height="830">\n'
            '  <title>Code - one-colour sticker (original redraw)</title>\n'
            f'  <g fill="#000000">\n  {body}\n  </g>\n</svg>\n')


def render_png(svg_text: str, path: Path, width: int = 4000) -> None:
    from PySide6.QtCore import QByteArray, Qt
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    app = QGuiApplication.instance() or QGuiApplication(["x", "-platform", "offscreen"])
    r = QSvgRenderer(QByteArray(svg_text.encode()))
    h = round(width * 830 / 1010)
    img = QImage(width, h, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p)
    p.end()
    img.save(str(path))
    del app


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    s = svg()
    (OUT / "code-sticker.svg").write_text(s, encoding="utf-8")
    render_png(s, OUT / "code-sticker.png")
    print("wrote", OUT / "code-sticker.svg", OUT / "code-sticker.png")
