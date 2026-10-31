"""Themes: one small file per theme in atarilauncher/themes/<id>.toml (name, description, colours, background, rain). To add a theme,
drop a new file there (or in ~/.config/atari/themes/) - it shows up in Settings > Theme. Original designs only.
A theme whose text would be hard to read (contrast too low) is refused, so every theme keeps text and the controller highlight readable."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import paths

try:
    import tomllib
except ImportError:  # pragma: no cover - Python < 3.11
    import tomli as tomllib  # type: ignore

DEFAULT = "codeaque-gold"
KEYS = ("bg", "panel", "card", "line", "text", "dim", "faint", "accent", "focus", "accent_dark", "yellow", "green", "blue", "overlay",
        "grad_top", "grad_bottom")


@dataclass
class Theme:
    id: str
    name: str
    description: str = ""
    order: int = 99
    rain: bool = False
    wave_opacity: float = 0.55
    colors: dict = field(default_factory=dict)

    def qml(self, rain_on: bool = True) -> dict:
        """What the screens use (Theme.qml): the colour names the QML already knows."""
        c = self.colors
        return {"bg": c["bg"], "panel": c["panel"], "card": c["card"], "line": c["line"], "text": c["text"], "dim": c["dim"],
                "faint": c["faint"], "red": c["accent"], "redBright": c["focus"], "redDark": c["accent_dark"], "yellow": c["yellow"],
                "green": c["green"], "blue": c["blue"], "overlay": c["overlay"], "gradTop": c["grad_top"], "gradBottom": c["grad_bottom"],
                "waveOpacity": self.wave_opacity, "rain": bool(self.rain and rain_on), "id": self.id}


def _rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    if len(h) == 8:
        h = h[2:]                                   # #AARRGGBB (Qt) - contrast is about the colour
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore


def luminance(h: str) -> float:
    def ch(v):
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(v) for v in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def problems(t: Theme) -> list[str]:
    """Readability rules every theme must pass (WCAG: 4.5 for text, 3 for large text and the focus highlight)."""
    out = [f"missing colour {k}" for k in KEYS if k not in t.colors]
    if out:
        return out
    c = t.colors
    for surf in ("bg", "panel", "card"):
        if contrast(c["text"], c[surf]) < 4.5:
            out.append(f"text on {surf} is hard to read")
        if contrast(c["dim"], c[surf]) < 3.0:
            out.append(f"grey text on {surf} is hard to read")
    if contrast(c["focus"], c["bg"]) < 3.0:
        out.append("the controller highlight is hard to see")
    return out


def _load(f: Path) -> Theme | None:
    try:
        d = tomllib.loads(f.read_text(encoding="utf-8"))
        t = Theme(f.stem, str(d.get("name") or f.stem), str(d.get("description", "")), int(d.get("order", 99)), bool(d.get("rain", False)),
                  float(d.get("wave_opacity", 0.55)), {k: str(v) for k, v in dict(d.get("colors", {})).items()})
    except (OSError, ValueError, TypeError, tomllib.TOMLDecodeError):
        return None
    return None if problems(t) else t


def folders() -> list[Path]:
    return [Path(__file__).resolve().parent / "themes", paths.config_dir() / "themes"]


def all_themes() -> list[Theme]:
    found: dict[str, Theme] = {}
    for d in folders():
        try:
            files = sorted(d.glob("*.toml"))
        except OSError:
            continue
        for f in files:
            t = _load(f)
            if t is not None:
                found[t.id] = t
    return sorted(found.values(), key=lambda t: (t.order, t.name.lower()))


def get(theme_id: str) -> Theme:
    ts = {t.id: t for t in all_themes()}
    return ts.get(theme_id) or ts.get(DEFAULT) or Theme(DEFAULT, "CodeAque Gold", colors={
        "bg": "#08090e", "panel": "#0f111a", "card": "#151826", "line": "#272b3d", "text": "#f3f4f8", "dim": "#9aa1b6", "faint": "#5c6279",
        "accent": "#e0202a", "focus": "#ff3a43", "accent_dark": "#5a0b11", "yellow": "#f2c230", "green": "#3fae49", "blue": "#2f7de1",
        "overlay": "#ee06070b", "grad_top": "#08090e", "grad_bottom": "#08090e"})
