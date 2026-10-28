"""Checklist model for the "Add Games" screen."""
from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QByteArray, QModelIndex, Qt, Signal, Slot

from .importer import ImportItem, human_size


class ImportModel(QAbstractListModel):
    ROLES = ["name", "systemName", "sizeText", "checked", "rel", "kind", "extra"]
    selectionChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[ImportItem] = []
        self._names: dict[str, str] = {}
        self._checked: list[bool] = []
        self._bios = False
        self._role_ids = {Qt.UserRole + 1 + i: n for i, n in enumerate(self.ROLES)}

    def roleNames(self):
        return {k: QByteArray(v.encode()) for k, v in self._role_ids.items()}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._items)

    def data(self, index, role):
        if not index.isValid() or not 0 <= index.row() < len(self._items):
            return None
        it = self._items[index.row()]
        name = self._role_ids.get(role)
        if name == "name":
            return it.name
        if name == "systemName":
            return self._names.get(it.system, it.system)
        if name == "sizeText":
            return human_size(it.size)
        if name == "checked":
            return self._checked[index.row()]
        if name == "rel":
            return it.rel
        if name == "kind":
            return "folder" if it.is_dir else "file"
        if name == "extra":  # BIOS list: what the file is and whether it checked out
            if not self._bios:
                return ""
            from .bios import STATUS_TEXT
            return f"{it.label}  -  {STATUS_TEXT.get(it.status, '')}"
        return None

    def set_items(self, items: list, names: dict[str, str] | None = None, kind: str = "games") -> None:
        self.beginResetModel()
        self._items = list(items)
        self._names = names or {}
        self._bios = kind == "bios"
        # BIOS list: unusual files and notes start unticked
        self._checked = [not (self._bios and getattr(it, "status", "") in ("odd", "note")) for it in self._items]
        self.endResetModel()
        self.selectionChanged.emit()

    def add_items(self, items: list) -> None:
        """Append games (ticked) - used when the user has said which console some files are for."""
        if not items:
            return
        first = len(self._items)
        self.beginInsertRows(QModelIndex(), first, first + len(items) - 1)
        self._items.extend(items)
        self._checked.extend([True] * len(items))
        self.endInsertRows()
        self.selectionChanged.emit()

    @Slot(int)
    def toggle(self, row: int) -> None:
        if 0 <= row < len(self._items):
            self._checked[row] = not self._checked[row]
            idx = self.index(row)
            self.dataChanged.emit(idx, idx, [Qt.UserRole + 1 + self.ROLES.index("checked")])
            self.selectionChanged.emit()

    @Slot(bool)
    def set_all(self, on: bool) -> None:
        if not self._items:
            return
        self._checked = [on] * len(self._items)
        self.dataChanged.emit(self.index(0), self.index(len(self._items) - 1),
                              [Qt.UserRole + 1 + self.ROLES.index("checked")])
        self.selectionChanged.emit()

    def selected_items(self) -> list[ImportItem]:
        return [it for it, c in zip(self._items, self._checked) if c]

    @Slot(result=int)
    def selectedCount(self) -> int:
        return sum(self._checked)

    @Slot(result=str)
    def summary(self) -> str:
        n = sum(self._checked)
        total = sum(it.size for it, c in zip(self._items, self._checked) if c)
        return f"{n} of {len(self._items)} selected  \u00b7  {human_size(total)}"

    @Slot(result=str)
    def selectedSizeText(self) -> str:
        return human_size(sum(it.size for it, c in zip(self._items, self._checked) if c))

    @Slot(result=bool)
    def allSelected(self) -> bool:
        return bool(self._checked) and all(self._checked)
