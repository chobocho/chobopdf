from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPalette, QPixmap, QTransform
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QScrollArea, QToolButton, QVBoxLayout,
                               QWidget)

from chobopdf.model.document import PageRef
from chobopdf.render.thumbnailer import Thumbnailer

_ZOOM_STEPS = [1.0, 1.25, 1.5, 2.0, 3.0, 4.0]  # multiples of "fit to width"
_MAX_RENDER_PX = 3500  # widest image asked of the renderer; beyond it the image is stretched
_MARGIN = 8


class PreviewPane(QWidget):
    """Shows one page large, fitted to the pane's width, for checking its content.

    Ctrl+wheel zooms in. The cached thumbnail is shown stretched at once and
    replaced when the sharp render arrives.
    """

    closeRequested = Signal()

    def __init__(self, thumbnailer: Thumbnailer, parent=None):
        super().__init__(parent)
        self._thumbnailer = thumbnailer
        self._page: PageRef | None = None
        self._aspect = 1.414  # height / width of the shown page
        self._zoom_step = 0
        self._token = 0
        self._requested: tuple[PageRef, int] | None = None

        self._title = QLabel()
        self._zoom_label = QLabel()
        close_button = QToolButton(text="✕", autoRaise=True, toolTip="미리보기 닫기 (Esc)")
        close_button.clicked.connect(self.closeRequested)
        header = QHBoxLayout()
        header.setContentsMargins(8, 2, 2, 2)
        header.addWidget(self._title, 1)
        header.addWidget(self._zoom_label)
        header.addWidget(close_button)

        self._image = QLabel()
        self._image.setScaledContents(True)
        self._scroll = QScrollArea()
        self._scroll.setBackgroundRole(QPalette.ColorRole.Dark)
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        # Always shown, so fitting to the width does not flip the scroll bar on and off.
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self._scroll.setWidget(self._image)
        self._scroll.viewport().installEventFilter(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(header)
        layout.addWidget(self._scroll, 1)
        self.setMinimumWidth(200)

        # Resizing and zooming re-render only once the size has settled.
        self._render_timer = QTimer(self, singleShot=True, interval=120)
        self._render_timer.timeout.connect(self._request)
        thumbnailer.previewReady.connect(self._on_ready)
        self.show_page(None, 0)

    def show_page(self, page: PageRef | None, number: int) -> None:
        """Show `page`, the `number`-th of the document; None empties the pane."""
        self._title.setText(f"{number}쪽" if page else "페이지를 선택하세요")
        if page == self._page:
            return
        same_sheet = page and self._page and page.key == self._page.key
        self._page = page
        if page is None:
            self._token += 1  # drop any render still on its way
            self._requested = None
            self._image.clear()
            self._image.resize(0, 0)
            self._zoom_label.clear()
            return
        if not same_sheet:
            self._scroll.verticalScrollBar().setValue(0)
        thumbnail = self._thumbnailer.get(page.key)
        if thumbnail is not None and not thumbnail.isNull():
            self._set_image(thumbnail.transformed(QTransform().rotate(page.rotation)))
        else:
            self._image.clear()
        self._fit()
        self._request()

    def _target_width(self) -> int:
        fit = max(50, self._scroll.viewport().width() - 2 * _MARGIN)
        return round(fit * _ZOOM_STEPS[self._zoom_step])

    def _set_image(self, image: QImage) -> None:
        self._aspect = image.height() / image.width()
        self._image.setPixmap(QPixmap.fromImage(image))

    def _fit(self) -> None:
        width = self._target_width()
        self._image.resize(width, round(width * self._aspect))
        self._zoom_label.setText(f"{round(_ZOOM_STEPS[self._zoom_step] * 100)}%")

    def _request(self) -> None:
        if self._page is None:
            return
        width_px = min(_MAX_RENDER_PX, round(self._target_width() * self.devicePixelRatioF()))
        if (self._page, width_px) == self._requested:
            return
        self._requested = (self._page, width_px)
        self._token += 1
        self._thumbnailer.request_preview(
            self._token, self._page.source, self._page.index, self._page.rotation, width_px)

    def _on_ready(self, token: int, image: QImage) -> None:
        if token != self._token or self._page is None:
            return  # answer to a request that has been replaced
        if image.isNull():
            self._title.setText(self._title.text() + " · 표시할 수 없습니다")
            return
        self._set_image(image)
        self._fit()

    def _zoom(self, steps: int) -> None:
        step = max(0, min(len(_ZOOM_STEPS) - 1, self._zoom_step + steps))
        if step != self._zoom_step and self._page is not None:
            self._zoom_step = step
            self._fit()
            self._render_timer.start()

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.Resize:
            if self._page is not None:
                self._fit()
                self._render_timer.start()
        elif (event.type() == QEvent.Type.Wheel
              and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self._zoom(1 if event.angleDelta().y() > 0 else -1)
            return True
        return super().eventFilter(watched, event)
