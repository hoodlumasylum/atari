"""Local favorites / play-time / recently-played store (JSON, written atomically)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from . import paths


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or paths.state_file()
        self.games: dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.games = data.get("games", {}) if isinstance(data, dict) else {}
        except (OSError, ValueError):
            self.games = {}

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"version": 1, "games": self.games}, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as exc:
            print(f"[atari] could not save {self.path}: {exc}")

    def get(self, gid: str) -> dict:
        return self.games.get(gid, {})

    def is_favorite(self, gid: str) -> bool:
        return bool(self.get(gid).get("favorite"))

    def toggle_favorite(self, gid: str) -> bool:
        rec = self.games.setdefault(gid, {})
        rec["favorite"] = not rec.get("favorite", False)
        self.save()
        return rec["favorite"]

    def mark_launched(self, gid: str, when: float | None = None) -> None:
        rec = self.games.setdefault(gid, {})
        rec["last_played"] = when if when is not None else time.time()
        rec["launches"] = rec.get("launches", 0) + 1
        self.save()

    def add_playtime(self, gid: str, seconds: float) -> None:
        if seconds <= 0:
            return
        rec = self.games.setdefault(gid, {})
        rec["playtime_sec"] = rec.get("playtime_sec", 0) + int(seconds)
        self.save()

    def playtime(self, gid: str) -> int:
        return int(self.get(gid).get("playtime_sec", 0))

    def last_played(self, gid: str) -> float:
        return float(self.get(gid).get("last_played", 0) or 0)

    def recent_ids(self, limit: int = 30) -> list[str]:
        items = [(r.get("last_played", 0), g) for g, r in self.games.items() if r.get("last_played")]
        items.sort(reverse=True)
        return [g for _, g in items[:limit]]


def format_playtime(sec: int) -> str:
    if sec < 60:
        return "Not played yet" if sec == 0 else "Under a minute"
    mins = sec // 60
    if mins < 60:
        return f"{mins} min"
    h, m = divmod(mins, 60)
    return f"{h} h {m:02d} min"


def format_last_played(ts: float, now: float | None = None) -> str:
    if not ts:
        return "Never"
    now = now if now is not None else time.time()
    days = int((now - ts) // 86400)
    if days <= 0:
        return "Today"
    if days == 1:
        return "Yesterday"
    if days < 30:
        return f"{days} days ago"
    return time.strftime("%d %b %Y", time.localtime(ts))
