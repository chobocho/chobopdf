from PySide6.QtCore import QPointF, QRectF, QSize, QSizeF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from chobopdf.render.thumbnailer import Thumbnailer

THUMB_SIZE = 160  # thumbnail box edge at 100% zoom, logical pixels
PADDING = 10
LABEL_HEIGHT = 20


def cell_size(thumb_size: int) -> QSize:
    return QSize(thumb_size + 2 * PADDING, thumb_size + LABEL_HEIGHT + 2 * PADDING)


CELL_SIZE = cell_size(THUMB_SIZE)

_PLACEHOLDER_COLOR = QColor(225, 225, 225)
_BORDER_COLOR = QColor(150, 150, 150)
_MARK_COLOR = QColor(225, 29, 72)
_MARK_EDGE_COLOR = QColor(255, 255, 255)


class PageDelegate(QStyledItemDelegate):
    def __init__(self, thumbnailer: Thumbnailer, parent=None):
        super().__init__(parent)
        self._thumbnailer = thumbnailer
        self.thumb_size = THUMB_SIZE

    def sizeHint(self, option, index) -> QSize:
        return cell_size(self.thumb_size)

    def paint(self, painter: QPainter, option, index) -> None:
        page = index.model().page(index.row())
        cell = option.rect
        selected = bool(option.state & QStyle.StateFlag.State_Selected)

        painter.save()
        if selected:
            painter.fillRect(cell.adjusted(2, 2, -2, -2), option.palette.highlight())

        box = QRectF(cell.x() + PADDING, cell.y() + PADDING, self.thumb_size, self.thumb_size)
        image = self._thumbnailer.get(page.key)
        ready = image is not None and not image.isNull()
        sideways = page.rotation % 180 == 90

        size = QSizeF(image.size()) if ready else QSizeF(1, 1.414)  # A4 portrait until rendered
        size = size.scaled(box.size().transposed() if sideways else box.size(),
                           Qt.AspectRatioMode.KeepAspectRatio)
        # Draw around the box centre so the extra rotation needs no re-render.
        painter.save()
        painter.translate(box.center())
        painter.rotate(page.rotation)
        target = QRectF(-size.width() / 2, -size.height() / 2, size.width(), size.height())
        if ready:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(target, image)
        else:
            painter.fillRect(target, _PLACEHOLDER_COLOR)
        painter.setPen(_BORDER_COLOR)
        painter.drawRect(target)
        painter.restore()

        if page.marked:
            shown = size.transposed() if sideways else size
            self._paint_mark(painter, box.center().x() + shown.width() / 2,
                             box.center().y() - shown.height() / 2)

        role = option.palette.ColorRole.HighlightedText if selected else option.palette.ColorRole.Text
        painter.setPen(option.palette.color(role))
        label = QRectF(cell.x(), box.bottom() + 2, cell.width(), LABEL_HEIGHT)
        painter.drawText(label, Qt.AlignmentFlag.AlignCenter, str(index.row() + 1))
        painter.restore()

    def _paint_mark(self, painter: QPainter, right: float, top: float) -> None:
        """Bookmark ribbon hanging over the top right corner of the page at (right, top)."""
        width = max(16.0, self.thumb_size * 0.13)
        height = width * 1.6
        left = right - width - width * 0.35
        top -= 4  # sticks out above the page, so it shows on a dark page too
        ribbon = QPolygonF([QPointF(left, top), QPointF(left + width, top),
                            QPointF(left + width, top + height),
                            QPointF(left + width / 2, top + height - width * 0.45),
                            QPointF(left, top + height)])
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(_MARK_EDGE_COLOR, 1.5))
        painter.setBrush(_MARK_COLOR)
        painter.drawPolygon(ribbon)
        painter.restore()
