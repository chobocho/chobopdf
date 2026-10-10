import threading
from collections import OrderedDict, deque
from pathlib import Path

import pypdfium2 as pdfium
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

Key = tuple[Path, int]

DEFAULT_CACHE_BYTES = 256 * 1024 * 1024


class Thumbnailer(QObject):
    """Opens PDFs and renders pages off the UI thread: cached thumbnails, plus one large preview.

    PDFium is not thread-safe, so every PDFium call happens on the single
    worker thread owned by this object.
    """

    opened = Signal(object, int)  # path, page count
    openFailed = Signal(object, str)  # path, message
    thumbnailReady = Signal(object)  # key
    previewReady = Signal(int, QImage)  # request token, image (null if the page failed)

    def __init__(self, render_px: int, cache_bytes: int = DEFAULT_CACHE_BYTES, parent=None):
        super().__init__(parent)
        self._render_px = render_px
        self._cache_limit = cache_bytes
        self._cache_bytes = 0
        # A null QImage marks a page that failed to render, so it is not retried forever.
        self._cache: OrderedDict[Key, QImage] = OrderedDict()
        self._wanted: deque[Key] = deque()
        self._preview: tuple[int, Path, int, int, int] | None = None  # latest request only
        self._commands: deque[tuple[str, Path, threading.Event | None]] = deque()
        self._stop = False
        self._cond = threading.Condition()
        self._docs: dict[Path, pdfium.PdfDocument] = {}  # worker thread only
        self._thread = threading.Thread(target=self._run, name="thumbnailer", daemon=True)
        self._thread.start()

    def open(self, path: Path) -> None:
        self._post("open", path)

    def close(self, path: Path, wait: bool = False) -> None:
        """Release the file and its thumbnails. It is reopened on demand if rendered again.

        With `wait`, returns only once the file handle is gone, so the file can be replaced.
        """
        done = threading.Event() if wait else None
        with self._cond:
            if self._stop:  # the worker is gone and has already released everything
                return
            self._wanted = deque(k for k in self._wanted if k[0] != path)
        self._post("close", path, done)
        if done is not None:
            done.wait()

    def set_render_px(self, render_px: int) -> None:
        """Change the thumbnail resolution. Cached smaller ones stay usable until re-rendered."""
        self._render_px = render_px

    def set_wanted(self, keys: list[Key]) -> None:
        """Replace the render queue. Keys are in priority order; anything not listed is dropped."""
        with self._cond:
            self._wanted = deque(k for k in keys if not self._is_current(k))
            self._cond.notify()

    def _is_current(self, key: Key) -> bool:
        image = self._cache.get(key)
        if image is None:
            return False
        # Null marks a failed page. One pixel of slack covers rounding in the renderer.
        return image.isNull() or max(image.width(), image.height()) >= self._render_px - 1

    def request_preview(self, token: int, path: Path, index: int, rotation: int,
                        width_px: int) -> None:
        """Render one page `width_px` wide, turned by `rotation`. Replaces any pending request.

        The answer comes through previewReady with the same token. It is not cached.
        """
        with self._cond:
            self._preview = (token, path, index, rotation, width_px)
            self._cond.notify()

    def get(self, key: Key) -> QImage | None:
        with self._cond:
            image = self._cache.get(key)
            if image is not None:
                self._cache.move_to_end(key)
            return image

    def stop(self) -> None:
        with self._cond:
            self._stop = True
            self._cond.notify()
        self._thread.join()

    def _post(self, command: str, path: Path, done: threading.Event | None = None) -> None:
        with self._cond:
            self._commands.append((command, path, done))
            self._cond.notify()

    def _run(self) -> None:
        while True:
            with self._cond:
                while not (self._stop or self._commands or self._preview or self._wanted):
                    self._cond.wait()
                if self._stop:
                    break
                key = preview = None
                if self._commands:
                    command, path, done = self._commands.popleft()
                elif self._preview:  # what the user is waiting for goes before thumbnails
                    preview, self._preview = self._preview, None
                else:
                    key = self._wanted.popleft()
            if preview is not None:
                self._render_preview(*preview)
                continue
            if key is not None:
                self._render(key)
                continue
            if command == "open":
                self._open(path)
            else:
                self._close(path)
            if done is not None:
                done.set()
        for doc in self._docs.values():
            doc.close()
        self._docs.clear()

    def _doc(self, path: Path) -> pdfium.PdfDocument:
        doc = self._docs.get(path)
        if doc is None:
            doc = self._docs[path] = pdfium.PdfDocument(path)
        return doc

    def _open(self, path: Path) -> None:
        try:
            count = len(self._doc(path))
        except Exception as e:
            self.openFailed.emit(path, str(e))
            return
        self.opened.emit(path, count)

    def _close(self, path: Path) -> None:
        doc = self._docs.pop(path, None)
        if doc is not None:
            doc.close()
        with self._cond:
            for key in [k for k in self._cache if k[0] == path]:
                self._cache_bytes -= self._cache.pop(key).sizeInBytes()

    def _render_image(self, path: Path, index: int, scale_for, rotation: int = 0,
                      draw_annots: bool = False) -> QImage:
        """Render a page; `scale_for(width, height)` picks the scale from its size in points."""
        try:
            page = self._doc(path)[index]
            try:
                bitmap = page.render(
                    scale=scale_for(*page.get_size()), rotation=rotation,
                    may_draw_forms=False, draw_annots=draw_annots, prefer_bgrx=True
                )
                try:
                    return QImage(
                        bitmap.buffer,
                        bitmap.width,
                        bitmap.height,
                        bitmap.stride,
                        QImage.Format.Format_RGB32,
                    ).copy()
                finally:
                    bitmap.close()
            finally:
                page.close()
        except Exception:
            return QImage()

    def _render_preview(self, token: int, path: Path, index: int, rotation: int,
                        width_px: int) -> None:
        def scale_for(width: float, height: float) -> float:
            return width_px / (height if rotation % 180 == 90 else width)

        self.previewReady.emit(
            token, self._render_image(path, index, scale_for, rotation, draw_annots=True))

    def _render(self, key: Key) -> None:
        image = self._render_image(*key, lambda width, height: self._render_px / max(width, height))
        with self._cond:
            previous = self._cache.pop(key, None)
            if previous is not None:
                self._cache_bytes -= previous.sizeInBytes()
            self._cache[key] = image
            self._cache_bytes += image.sizeInBytes()
            while self._cache_bytes > self._cache_limit and len(self._cache) > 1:
                _, evicted = self._cache.popitem(last=False)
                self._cache_bytes -= evicted.sizeInBytes()
        self.thumbnailReady.emit(key)
