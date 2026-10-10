from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPalette, QPixmap, QTransform
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QScrollArea, QToolButton, QVBoxLayout,
                               QWidget)

from chobopdf.model.document import PageRef
from chobopdf.render.thumbnailer import Thumbnailer

_ZOOM_STEPS = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0]  # multiples of "fit to width"
_MAX_RENDER_PX = 3500  # widest image asked of the renderer; beyond it the image is stretched
_MARGIN = 8
_EPSILON = 1e-6


class PreviewPane(QWidget):
    """Shows one page large, fitted to the pane's width, for checking its content.

    The size is changed with the header buttons, Ctrl+wheel, or Ctrl with + - 0.
    While the pane has the focus, Page Up / Page Down step through the document.
    The cached thumbnail is shown stretched at once and replaced when the
    sharp render arrives.
    """

    closeRequested = Signal()
    pageStepRequested = Signal(int)  # -1: previous page, +1: next page

    def __init__(self, thumbnailer: Thumbnailer, parent=None):
        super().__init__(parent)
        self._thumbnailer = thumbnailer
        self._page: PageRef | None = None
        self._aspect = 1.414  # height / width of the shown page
        self._scale = 1.0  # multiple of the width that fits the pane
        self._fit_page = False  # instead of _scale, size the page so all of it is visible
        self._token = 0
        self._requested: tuple[PageRef, int] | None = None

        self._title = QLabel()
        self._zoom_label = QLabel(alignment=Qt.AlignmentFlag.AlignCenter, minimumWidth=44)
        header = QHBoxLayout()
        header.setContentsMargins(8, 2, 2, 2)
        header.setSpacing(2)
        header.addWidget(self._title, 1)
        self._zoom_out_button = self._add_button(header, "－", "축소 (Ctrl+-)", lambda: self._zoom(-1))
        header.addWidget(self._zoom_label)
        self._zoom_in_button = self._add_button(header, "＋", "확대 (Ctrl++)", lambda: self._zoom(1))
        self._add_button(header, "폭 맞춤", "창 폭에 맞춤 (Ctrl+0)", lambda: self._set_scale(1.0))
        self._fit_page_button = self._add_button(
            header, "쪽 맞춤", "페이지 전체가 보이도록 세로 길이에 맞춤",
            lambda: self._set_scale(1.0, fit_page=True))
        header.addSpacing(8)
        self._add_button(header, "✕", "미리보기 닫기 (Esc)", self.closeRequested.emit)

        self._image = QLabel()
        self._image.setScaledContents(True)
        self._scroll = QScrollArea()
        self._scroll.setBackgroundRole(QPalette.ColorRole.Dark)
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Always shown, so fitting to the width does not flip the scroll bar on and off.
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self._scroll.setWidget(self._image)
        self._scroll.viewport().installEventFilter(self)
        self._scroll.installEventFilter(self)  # keys, once a click has given it the focus

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

    def _add_button(self, layout, text: str, tooltip: str, slot) -> QToolButton:
        # No focus of their own: the keyboard stays with the page after a click.
        button = QToolButton(text=text, autoRaise=True, toolTip=tooltip,
                             focusPolicy=Qt.FocusPolicy.NoFocus)
        button.clicked.connect(slot)
        layout.addWidget(button)
        return button

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
            self._zoom_out_button.setEnabled(False)
            self._zoom_in_button.setEnabled(False)
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

    def _fit_width(self) -> int:
        return max(50, self._scroll.viewport().width() - 2 * _MARGIN)

    def _current_scale(self) -> float:
        if not self._fit_page:
            return self._scale
        # Width at which the page is exactly as tall as the pane; a wide page stops at the pane's width.
        width = max(50, (self._scroll.viewport().height() - 2 * _MARGIN) / self._aspect)
        return min(1.0, width / self._fit_width())

    def _target_width(self) -> int:
        return round(self._fit_width() * self._current_scale())

    def _set_image(self, image: QImage) -> None:
        self._aspect = image.height() / image.width()
        self._image.setPixmap(QPixmap.fromImage(image))

    def _fit(self) -> None:
        width = self._target_width()
        self._image.resize(width, round(width * self._aspect))
        scale = self._current_scale()
        self._zoom_label.setText(f"{round(scale * 100)}%")
        self._zoom_out_button.setEnabled(scale > _ZOOM_STEPS[0] + _EPSILON)
        self._zoom_in_button.setEnabled(scale < _ZOOM_STEPS[-1] - _EPSILON)

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

    def _set_scale(self, scale: float, fit_page: bool = False) -> None:
        if self._page is not None:
            self._scale = scale
            self._fit_page = fit_page
            self._fit()
            self._render_timer.start()

    def _zoom(self, direction: int) -> None:
        """Step to the next larger (+1) or smaller (-1) size from wherever the page is now."""
        scale = self._current_scale()
        if direction > 0:
            steps = [step for step in _ZOOM_STEPS if step > scale + _EPSILON]
        else:
            steps = [step for step in reversed(_ZOOM_STEPS) if step < scale - _EPSILON]
        if steps:
            self._set_scale(steps[0])

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.KeyPress:
            if self._on_key(event):
                return True
        elif watched is not self._scroll.viewport():
            pass
        elif event.type() == QEvent.Type.Resize:
            if self._page is not None:
                self._fit()
                self._render_timer.start()
        elif (event.type() == QEvent.Type.Wheel
              and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self._zoom(1 if event.angleDelta().y() > 0 else -1)
            return True
        return super().eventFilter(watched, event)

    def _on_key(self, event) -> bool:
        key = event.key()
        if key == Qt.Key.Key_PageDown:
            self.pageStepRequested.emit(1)
        elif key == Qt.Key.Key_PageUp:
            self.pageStepRequested.emit(-1)
        elif not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            return False
        elif key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self._zoom(1)
        elif key == Qt.Key.Key_Minus:
            self._zoom(-1)
        elif key == Qt.Key.Key_0:
            self._set_scale(1.0)
        else:
            return False
        return True
