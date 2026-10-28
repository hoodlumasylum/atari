"""Qt list model + filtering logic for the game grid."""
from __future__ import annotations

import hashlib

from PySide6.QtCore import QAbstractListModel, QByteArray, QModelIndex, Qt, QUrl

from .library import Game
from .store import Store, format_last_played, format_playtime


def filter_games(games: list[Game], store: Store, key: str, query: str) -> list[Game]:
    """Pure filtering function (unit-tested)."""
    q = query.strip().lower()
    if q:
        pool = [g for g in games if key not in ("all", "recent", "favorites") and g.platform == key] \
            if key not in ("all", "recent", "favorites") else list(games)
        words = q.split()
        pool = [g for g in pool if all(w in g.title.lower() or w in g.platform_name.lower() for w in words)]
        return sorted(pool, key=lambda g: g.title.lower())
    if key == "all":
        return sorted(games, key=lambda g: g.title.lower())
    if key == "favorites":
        return sorted([g for g in games if store.is_favorite(g.gid)], key=lambda g: g.title.lower())
    if key == "recent":
        by_id = {g.gid: g for g in games}
        return [by_id[i] for i in store.recent_ids() if i in by_id]
    return sorted([g for g in games if g.platform == key], key=lambda g: g.title.lower())


class GameModel(QAbstractListModel):
    ROLES = ["gid", "title", "platform", "platformName", "cover", "favorite", "playtime", "lastPlayed",
             "note", "hue"]

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
            return int(hashlib.sha1(g.title.encode()).hexdigest()[:4], 16) / 65535.0
        return None

    def set_visible(self, games: list[Game]) -> None:
        self.beginResetModel()
        self._visible = games
        self.endResetModel()

    def game_at(self, row: int) -> Game | None:
        return self._visible[row] if 0 <= row < len(self._visible) else None

    def row_changed(self, row: int) -> None:
        idx = self.index(row)
        self.dataChanged.emit(idx, idx)
