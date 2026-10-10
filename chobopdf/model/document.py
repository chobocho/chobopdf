from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, Signal


@dataclass(frozen=True)
class PageRef:
    """One page of the edited document: a pointer into a source PDF.

    Editing only rearranges these; the source files are never touched
    until the document is saved.
    """

    source: Path
    index: int
    rotation: int = 0  # extra clockwise rotation in degrees, multiple of 90

    @property
    def key(self) -> tuple[Path, int]:
        """Thumbnail cache key. Rotation is applied at paint time, so it is not part of it."""
        return (self.source, self.index)


class PageListModel(QAbstractListModel):
    # Rows an edit has just put in place, so the view can select and reveal them.
    placed = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pages: list[PageRef] = []

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._pages)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and role == Qt.ItemDataRole.DisplayRole:
            return str(index.row() + 1)
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return (Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsDragEnabled)

    def page(self, row: int) -> PageRef:
        return self._pages[row]

    def pages(self) -> list[PageRef]:
        return list(self._pages)

    def insert(self, row: int, pages: list[PageRef]) -> None:
        if not pages:
            return
        self.beginInsertRows(QModelIndex(), row, row + len(pages) - 1)
        self._pages[row:row] = pages
        self.endInsertRows()

    def remove(self, row: int, count: int = 1) -> None:
        if count <= 0:
            return
        self.beginRemoveRows(QModelIndex(), row, row + count - 1)
        del self._pages[row:row + count]
        self.endRemoveRows()

    def replace(self, row: int, page: PageRef) -> None:
        self._pages[row] = page
        index = self.index(row)
        self.dataChanged.emit(index, index)

    def set_pages(self, pages: list[PageRef]) -> None:
        self.beginResetModel()
        self._pages = list(pages)
        self.endResetModel()

    def set_document(self, source: Path, page_count: int) -> None:
        self.set_pages([PageRef(source, i) for i in range(page_count)])
