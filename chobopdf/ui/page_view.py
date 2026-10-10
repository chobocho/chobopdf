from pathlib import Path

from PySide6.QtCore import (QItemSelection, QItemSelectionModel, QMimeData, QPoint, QRect, Qt, QTimer,
                            Signal)
from PySide6.QtGui import QColor, QDrag, QPainter, QPixmap, QTransform, QUndoStack
from PySide6.QtWidgets import QAbstractItemView, QListView

from chobopdf.model.commands import DeletePages, InsertPages, MovePages, RotatePages
from chobopdf.model.document import PageListModel, PageRef
from chobopdf.render.thumbnailer import Thumbnailer
from chobopdf.ui.page_delegate import THUMB_SIZE, PageDelegate, cell_size

_SCREENS_AHEAD = 2
_SCREENS_BEHIND = 1
_DRAG_MIME = "application/x-chobopdf-pages"
_DRAG_PIXMAP_SIZE = 96

MIN_ZOOM = 100  # percent
MAX_ZOOM = 200


def pdf_paths(mime_data) -> list[Path]:
    """Local PDF files carried by a drag from the file manager."""
    return [Path(url.toLocalFile()) for url in mime_data.urls()
            if url.isLocalFile() and url.toLocalFile().lower().endswith(".pdf")]


class PageView(QListView):
    """Thumbnail grid. Only pages on or near the screen are ever rendered.

    Edits go through the undo stack and only touch the page list, never the PDF.
    """

    zoomChanged = Signal(int)  # percent
    filesDropped = Signal(list, int)  # PDF paths, row to insert them before

    def __init__(self, model: PageListModel, thumbnailer: Thumbnailer, undo_stack: QUndoStack,
                 parent=None):
        super().__init__(parent)
        self._thumbnailer = thumbnailer
        self._undo_stack = undo_stack
        self._clipboard: list[PageRef] = []
        self._drop_line: QRect | None = None
        self._zoom = MIN_ZOOM
        self._last_scroll = 0

        self.setViewMode(QListView.ViewMode.IconMode)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        # Drops are handled here, with our own insertion line between cells.
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(False)
        self.setItemDelegate(PageDelegate(thumbnailer, self))
        self.setModel(model)
        self._apply_zoom()

        # Coalesce bursts of scroll/resize events into one queue update.
        self._wanted_timer = QTimer(self, singleShot=True, interval=0)
        self._wanted_timer.timeout.connect(self._update_wanted)
        self.verticalScrollBar().valueChanged.connect(self._schedule_wanted)
        self.verticalScrollBar().rangeChanged.connect(self._schedule_wanted)
        model.modelReset.connect(self._schedule_wanted)
        model.rowsInserted.connect(self._schedule_wanted)
        model.rowsRemoved.connect(self._schedule_wanted)
        model.placed.connect(self._select_rows)
        thumbnailer.thumbnailReady.connect(self._on_thumbnail_ready)

    # --- zoom ------------------------------------------------------------

    def zoom(self) -> int:
        return self._zoom

    def set_zoom(self, percent: int) -> None:
        percent = max(MIN_ZOOM, min(MAX_ZOOM, percent))
        if percent == self._zoom:
            return
        top_row = self.top_row()  # keep it in view across the relayout
        self._zoom = percent
        self._apply_zoom()
        self.scroll_to_row(top_row)
        self._schedule_wanted()
        self.zoomChanged.emit(percent)

    def top_row(self) -> int:
        """First page of the topmost visible grid row."""
        return (self.verticalScrollBar().value() // self.gridSize().height()) * self._columns()

    def scroll_to_row(self, row: int) -> None:
        count = self.model().rowCount()
        if count:
            self.scrollTo(self.model().index(min(row, count - 1)),
                          QAbstractItemView.ScrollHint.PositionAtTop)

    def _apply_zoom(self) -> None:
        thumb_size = THUMB_SIZE * self._zoom // 100
        self.itemDelegate().thumb_size = thumb_size
        self.setGridSize(cell_size(thumb_size))
        self.verticalScrollBar().setSingleStep(self.gridSize().height() // 4)
        self._thumbnailer.set_render_px(round(thumb_size * self.devicePixelRatioF()))

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            step = 10 if event.angleDelta().y() > 0 else -10
            self.set_zoom(self._zoom + step)
            event.accept()
        else:
            super().wheelEvent(event)

    # --- editing ---------------------------------------------------------

    def selected_rows(self) -> list[int]:
        return sorted(index.row() for index in self.selectionModel().selectedIndexes())

    def can_paste(self) -> bool:
        return bool(self._clipboard)

    def clear_clipboard(self) -> None:
        self._clipboard = []

    def rotate_selected(self, degrees: int) -> None:
        rows = self.selected_rows()
        if rows:
            self._undo_stack.push(RotatePages(self.model(), rows, degrees))

    def delete_selected(self, text: str = "삭제") -> None:
        rows = self.selected_rows()
        if not rows:
            return
        self._undo_stack.push(DeletePages(self.model(), rows, text))
        # Leave the page that slid into place selected, so Delete can be repeated.
        remaining = self.model().rowCount()
        if remaining:
            self._select_rows([min(rows[0], remaining - 1)])

    def copy_selected(self) -> None:
        rows = self.selected_rows()
        if rows:
            self._clipboard = [self.model().page(row) for row in rows]

    def cut_selected(self) -> None:
        self.copy_selected()
        self.delete_selected("잘라내기")

    def paste(self) -> None:
        if self._clipboard:
            self._insert_after_selection(list(self._clipboard), "붙여넣기")

    def duplicate_selected(self) -> None:
        rows = self.selected_rows()
        if rows:
            self._insert_after_selection([self.model().page(row) for row in rows], "복제")

    def _insert_after_selection(self, pages: list[PageRef], text: str) -> None:
        rows = self.selected_rows()
        row = rows[-1] + 1 if rows else self.model().rowCount()
        self._undo_stack.push(InsertPages(self.model(), row, pages, text))

    def move_selected_to(self, dest: int) -> None:
        rows = self.selected_rows()
        if not rows:
            return
        command = MovePages(self.model(), rows, dest)
        if not command.is_noop():
            self._undo_stack.push(command)

    def _select_rows(self, rows: list[int]) -> None:
        model = self.model()
        selection = QItemSelection()
        for row in rows:
            selection.select(model.index(row), model.index(row))
        self.selectionModel().select(selection, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        first = model.index(rows[0])
        self.selectionModel().setCurrentIndex(first, QItemSelectionModel.SelectionFlag.NoUpdate)
        self.scrollTo(first)

    # --- drag and drop ---------------------------------------------------

    def startDrag(self, supported_actions) -> None:
        rows = self.selected_rows()
        if not rows:
            return
        mime = QMimeData()
        mime.setData(_DRAG_MIME, b"")
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(self._drag_pixmap(len(rows)))
        drag.exec(Qt.DropAction.MoveAction)
        self._set_drop_line(None)

    def _drag_pixmap(self, count: int) -> QPixmap:
        current = self.currentIndex()
        page = self.model().page(current.row() if current.isValid() else self.selected_rows()[0])
        image = self._thumbnailer.get(page.key)
        if image is None or image.isNull():
            pixmap = QPixmap(_DRAG_PIXMAP_SIZE * 3 // 4, _DRAG_PIXMAP_SIZE)
            pixmap.fill(QColor(225, 225, 225))
        else:
            pixmap = QPixmap.fromImage(image.transformed(QTransform().rotate(page.rotation))).scaled(
                _DRAG_PIXMAP_SIZE, _DRAG_PIXMAP_SIZE, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
        painter = QPainter(pixmap)
        painter.setPen(QColor(120, 120, 120))
        painter.drawRect(pixmap.rect().adjusted(0, 0, -1, -1))
        if count > 1:
            badge = QRect(0, 0, 34, 22)
            badge.moveCenter(pixmap.rect().center())
            painter.fillRect(badge, self.palette().highlight())
            painter.setPen(self.palette().highlightedText().color())
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, str(count))
        painter.end()
        return pixmap

    def _is_page_drag(self, event) -> bool:
        return event.source() is self and event.mimeData().hasFormat(_DRAG_MIME)

    def _is_file_drag(self, event) -> bool:
        # With nothing open there is no position to insert at: the window opens the files instead.
        return self.model().rowCount() > 0 and bool(pdf_paths(event.mimeData()))

    def dragEnterEvent(self, event) -> None:
        if self._is_page_drag(event) or self._is_file_drag(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if self._is_page_drag(event):
            action = Qt.DropAction.MoveAction
        elif self._is_file_drag(event):
            action = Qt.DropAction.CopyAction
        else:
            event.ignore()
            return
        super().dragMoveEvent(event)  # keeps edge auto-scrolling
        self._set_drop_line(self.drop_target(event.position().toPoint())[1])
        event.setDropAction(action)
        event.accept()

    def dragLeaveEvent(self, event) -> None:
        super().dragLeaveEvent(event)
        self._set_drop_line(None)

    def dropEvent(self, event) -> None:
        dest = self.drop_target(event.position().toPoint())[0]
        self._set_drop_line(None)
        if self._is_page_drag(event):
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
            self.move_selected_to(dest)
        elif self._is_file_drag(event):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            self.filesDropped.emit(pdf_paths(event.mimeData()), dest)
        else:
            event.ignore()

    def drop_target(self, pos: QPoint) -> tuple[int, QRect]:
        """Row a drop at `pos` inserts before, and the insertion line to show for it."""
        count = self.model().rowCount()
        cell = self.gridSize()
        columns = self._columns()
        scroll = self.verticalScrollBar().value()
        grid_row = (pos.y() + scroll) // cell.height()
        column = min(columns, (pos.x() + cell.width() // 2) // cell.width())
        row = grid_row * columns + column
        if row >= count:
            row = count
            last = self.visualRect(self.model().index(count - 1))
            x, y = last.right() + 1, last.top()
        else:
            x, y = column * cell.width(), grid_row * cell.height() - scroll
        return row, QRect(max(0, x - 1), y + 4, 3, cell.height() - 8)

    def _set_drop_line(self, line: QRect | None) -> None:
        if line != self._drop_line:
            self._drop_line = line
            self.viewport().update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._drop_line is not None:
            QPainter(self.viewport()).fillRect(self._drop_line, self.palette().highlight())

    # --- thumbnail scheduling --------------------------------------------

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._schedule_wanted()

    def _schedule_wanted(self, *_) -> None:
        self._wanted_timer.start()

    def _on_thumbnail_ready(self, _key) -> None:
        self.viewport().update()

    def _columns(self) -> int:
        model = self.model()
        count = model.rowCount()
        top = self.visualRect(model.index(0)).top()
        columns = 1
        while columns < count and self.visualRect(model.index(columns)).top() == top:
            columns += 1
        return columns

    def _update_wanted(self) -> None:
        model = self.model()
        count = model.rowCount()
        if count == 0:
            self._thumbnailer.set_wanted([])
            return
        columns = self._columns()
        cell_height = self.gridSize().height()
        scroll = self.verticalScrollBar().value()
        first = (scroll // cell_height) * columns
        last = min(count, ((scroll + self.viewport().height()) // cell_height + 1) * columns)
        screen = max(last - first, columns)

        ahead = range(last, min(count, last + _SCREENS_AHEAD * screen))
        behind = range(first - 1, max(-1, first - 1 - _SCREENS_BEHIND * screen), -1)
        if scroll < self._last_scroll:  # scrolling up: prefetch above first
            ahead, behind = behind, ahead
        self._last_scroll = scroll

        rows = [*range(first, last), *ahead, *behind]
        self._thumbnailer.set_wanted([model.page(row).key for row in rows])
