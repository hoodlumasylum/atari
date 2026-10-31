"""Which button names to show: PlayStation (cross / circle / square / triangle, OPTIONS / SHARE, L1 / R1) or Xbox (A B X Y,
Menu / View, LB / RB). Auto = the pad used last; unknown pads get the Xbox names (the layout SDL uses)."""
from __future__ import annotations

import re

PS_WORDS = ("wireless controller", "dualshock", "dualsense", "playstation", "sony", "ps4", "ps5", "ps3")
XBOX_WORDS = ("xbox", "x-box", "microsoft", "xinput")
CHOICES = ("auto", "ps", "xbox")
NAMES = {"auto": "Auto (matches your pad)", "ps": "PlayStation", "xbox": "Xbox"}
PS_FACE = {"A": "Cross", "B": "Circle", "X": "Square", "Y": "Triangle", "LB": "L1", "RB": "R1", "Start": "Options", "Back": "Share"}


def style_of(name: str) -> str:
    n = (name or "").lower()
    if any(w in n for w in XBOX_WORDS):
        return "xbox"
    if any(w in n for w in PS_WORDS):
        return "ps"
    return "xbox"


def resolve(pref: str, last_pad: str) -> str:
    return pref if pref in ("ps", "xbox") else (style_of(last_pad) if last_pad else "xbox")


_TOKEN = re.compile(r"(?<=/ )([ABXY])\b|\b([ABXY])(?= =| to | on |,| \()|(?<=\+ )([ABXY])\b|\b(LB|RB)\b")


def pad_text(text: str, style: str) -> str:
    """'Enter / A to press.  Esc / B = back.' -> 'Enter / Cross to press.  Esc / Circle = back.' for PlayStation pads."""
    if style != "ps" or not text:
        return text
    return _TOKEN.sub(lambda m: PS_FACE[next(g for g in m.groups() if g)], text)
