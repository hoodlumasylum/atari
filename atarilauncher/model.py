"""Qt list model + filtering logic for the game grid."""
from __future__ import annotations

import hashlib

from PySide6.QtCore import QAbstractListModel, QByteArray, QModelIndex, Qt, QUrl, Slot

from .library import Game
from .store import Store, format_last_played, format_playtime


SORT_MODES = [("az", "A-Z"), ("za", "Z-A"), ("played", "Recently played"), ("added", "Recently added")]


def sort_games(games: list[Game], store: Store, sort: str) -> list[Game]:
    """Pure sorting function (unit-tested). Unknown sort names mean A-Z."""
    if sort == "za":
        return sorted(games, key=lambda g: g.title.lower(), reverse=True)
    if sort == "played":
        # most recently played first; never-played games follow in A-Z order
        return sorted(games, key=lambda g: (-store.last_played(g.gid), g.title.lower()))
    if sort == "added":
        return sorted(games, key=lambda g: (-g.added, g.title.lower()))
    return sorted(games, key=lambda g: g.title.lower())


def filter_games(games: list[Game], store: Store, key: str, query: str, sort: str = "az") -> list[Game]:
    """Pure filtering function (unit-tested)."""
    q = query.strip().lower()
    special = key in ("all", "recent", "favorites")
    if q:
        pool = list(games) if special else [g for g in games if g.platform == key]
        words = q.split()
        pool = [g for g in pool if all(w in g.title.lower() or w in g.platform_name.lower() for w in words)]
        return sort_games(pool, store, sort)
    if key == "all":
        # the PC Apps / Stores launchers (Roblox, Heroic, ...) have their own tile; "All Games" is games only
        return sort_games([g for g in games if g.platform not in ("apps", "streaming", "free", "studio", "tools")], store, sort)
    if key == "favorites":
        return sort_games([g for g in games if store.is_favorite(g.gid)], store, sort)
    if key == "recent":
        by_id = {g.gid: g for g in games}
        return [by_id[i] for i in store.recent_ids() if i in by_id]
    return sort_games([g for g in games if g.platform == key], store, sort)


class GameModel(QAbstractListModel):
    ROLES = ["gid", "title", "platform", "platformName", "cover", "favorite", "playtime", "lastPlayed",
             "note", "hue", "fit"]

    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self._store = store
        self._visible: list[Game] = []
        self._role_ids = {Qt.UserRole + 1 + i: n for i, n in enumerate(self.ROLES)}

    def roleNames(self):
        return {k: QByteArray(v.encode()) for k, v in self._role_ids.items()}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._visible)

    def data(self, index, role):
        if not index.isValid() or not 0 <= index.row() < len(self._visible):
            return None
        g = self._visible[index.row()]
        name = self._role_ids.get(role)
        s = self._store
        if name == "gid":
            return g.gid
        if name == "title":
            return g.title
        if name == "platform":
            return g.platform
        if name == "platformName":
            return g.platform_name
        if name == "cover":
            return QUrl.fromLocalFile(g.cover).toString() if g.cover else ""
        if name == "favorite":
            return s.is_favorite(g.gid)
        if name == "playtime":
            return format_playtime(s.playtime(g.gid))
        if name == "lastPlayed":
            return format_last_played(s.last_played(g.gid))
        if name == "note":
            return g.note
        if name == "hue":
            return self._hue(g)
        if name == "fit":
            return bool(g.fit)
        return None

    @Slot(int, result="QVariantMap")
    def get(self, row: int):
        """Everything the detail panel shows about one game ('-' where nothing is known)."""
        g = self.game_at(row)
        if g is None:
            return {}
        s = self._store
        m = g.meta or {}

        def text(key: str) -> str:
            v = m.get(key)
            return str(v).strip() if v not in (None, "") else "-"

        try:
            rating = max(0.0, min(5.0, float(m.get("rating")))) if m.get("rating") not in (None, "") else -1.0
        except (TypeError, ValueError):
            rating = -1.0
        return {
            "gid": g.gid, "title": g.title, "platform": g.platform, "platformName": g.platform_name,
            "cover": QUrl.fromLocalFile(g.cover).toString() if g.cover else "",
            "art": QUrl.fromLocalFile(g.header or g.cover).toString() if (g.header or g.cover) else "",
            "wideArt": bool(g.header) and g.header != g.cover, "fitArt": bool(g.fit),
            "favorite": s.is_favorite(g.gid), "playtime": format_playtime(s.playtime(g.gid)),
            "lastPlayed": format_last_played(s.last_played(g.gid)), "note": g.note,
            "hue": self._hue(g), "needsInstall": bool(g.missing), "genre": text("genre"), "players": text("players"),
            "release": text("release"), "rating": rating,
        }

    @staticmethod
    def _hue(g: Game) -> float:
        return int(hashlib.sha1(g.title.encode()).hexdigest()[:4], 16) / 65535.0

    def set_visible(self, games: list[Game]) -> None:
        self.beginResetModel()
        self._visible = games
        self.endResetModel()

    def game_at(self, row: int) -> Game | None:
        return self._visible[row] if 0 <= row < len(self._visible) else None

    def cover_updated(self, gid: str) -> None:
        """A cover file arrived for this game: refresh its tile (if it is on screen) without resetting the grid."""
        for row, g in enumerate(self._visible):
            if g.gid == gid:
                idx = self.index(row)
                self.dataChanged.emit(idx, idx, [Qt.UserRole + 1 + self.ROLES.index("cover"), Qt.UserRole + 1 + self.ROLES.index("fit")])
                return

    def row_changed(self, row: int) -> None:
        idx = self.index(row)
        self.dataChanged.emit(idx, idx)
