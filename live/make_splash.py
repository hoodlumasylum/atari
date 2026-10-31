"""The legacy-BIOS boot menu background (640x480): the CodeAque logo on black. Usage: make_splash.py <logo.png> <out.png>"""
import sys
from PIL import Image
logo = Image.open(sys.argv[1]).convert("RGBA")
bg = Image.new("RGB", (640, 480), (0, 0, 0))
logo.thumbnail((140, 140), Image.LANCZOS)
bg.paste(logo, ((640 - logo.width) // 2, 8), logo)
bg.save(sys.argv[2])
