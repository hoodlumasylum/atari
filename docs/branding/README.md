# CodeAque branding

| File | What it is |
| --- | --- |
| `codeaque-logo-source.png` | The original file as supplied by the project owner (gold and emerald Anubis, "CODEAQUE GAMING"), 1254x1254, opaque black background. |
| `codeaque-logo.png` | The same logo with a transparent background (made by `scripts/make_brand_assets.py`), 1254 px. |
| `codeaque-banner.png` | The logo on the dark app background, 1280x420, used at the top of the README. |
| `codeaque-cutline.png` | A plain black **outline** of the logo (2000 px) to give a print shop as a starting point for a contour cut. It is **not** a finished sticker file. |

The app and menu icons (`packaging/icons/code-*.png`, `packaging/atari-launcher.svg`) and the in-app pictures
(`atarilauncher/assets/codeaque-logo.png`, `codeaque-icon.png`, the Anubis head only) are made from the same file by
`python3 scripts/make_brand_assets.py` (needs Pillow). The file names `code-*` and `atari-launcher` are internal and stay the same on purpose,
so existing installs and updates keep working.

## Size - please read before ordering stickers
The source is **1254 pixels** square. That is sharp on a TV and in the app, but **too small for print-quality metal or large vinyl stickers**
(at 10 cm wide it is about 320 dpi, at 20 cm about 160 dpi, and the glow and the fine hieroglyphs will look soft). Ask for a larger or vector
version from whoever made the artwork, or have a designer redraw it. The matte (transparent) version was made by script from a black background, so
a very faint dark fringe can remain around the glow on light backgrounds.

## Rights - please read
The logo and the intro video were **made with AI tools** and supplied by the project owner. In many countries (for example the USA)
purely AI-generated artwork **cannot be copyrighted** and it may be difficult to register as a trademark, so do not count on exclusive rights
to it. They contain no third-party logos that we know of. The name "CodeAque" has **not** been checked in any trademark register: look it up for
your country before using it commercially. (The old name "Code" was also commonly used for Microsoft's Visual Studio Code.)

The intro video file, if you added one, is yours and is not changed by the app; the built-in animation and the boot screens use the logo above.
