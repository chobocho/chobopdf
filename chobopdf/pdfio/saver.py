import threading
from collections.abc import Callable
from pathlib import Path

import pikepdf
from PySide6.QtCore import QObject, Signal

from chobopdf.model.document import PageRef

_ASSEMBLE_SHARE = 10  # percent of the progress bar given to collecting pages; the rest is writing


class SaveCancelled(Exception):
    pass


def write_pdf(pages: list[PageRef], dest: Path,
              progress: Callable[[int], None] = lambda percent: None,
              is_cancelled: Callable[[], bool] = lambda: False) -> None:
    """Write `pages` to a new PDF at `dest`.

    Page contents are copied as they are, without re-encoding. Document-level
    data that no longer matches the new page order (bookmarks, form fields) is
    not carried over.
    """
    def check() -> None:
        if is_cancelled():
            raise SaveCancelled

    def on_write(percent: int) -> None:
        check()
        progress(_ASSEMBLE_SHARE + percent * (100 - _ASSEMBLE_SHARE) // 100)

    sources: dict[Path, pikepdf.Pdf] = {}
    out = pikepdf.new()
    try:
        for done, ref in enumerate(pages):
            check()
            source = sources.get(ref.source)
            if source is None:
                source = sources[ref.source] = pikepdf.open(ref.source)
                if done == 0:
                    info = source.trailer.get("/Info")
                    if info is not None and info.is_indirect:
                        out.trailer["/Info"] = out.copy_foreign(info)
            # Appending the same source page again makes an independent copy
            # of the page that shares its content, so duplicates stay small.
            out.pages.append(source.pages[ref.index])
            progress(done * _ASSEMBLE_SHARE // len(pages))
        # Rotate only once every page is in place: a copy made after its
        # original was rotated would inherit that rotation.
        for page, ref in zip(out.pages, pages):
            if ref.rotation:
                page.rotate(ref.rotation, relative=True)
        out.save(dest, progress=on_write)
    finally:
        out.close()
        for source in sources.values():
            source.close()


class SaveJob(QObject):
    """Runs write_pdf on its own thread and reports back with signals."""

    progress = Signal(int)  # percent
    finished = Signal()
    cancelled = Signal()
    failed = Signal(str)

    def __init__(self, pages: list[PageRef], dest: Path, parent=None):
        super().__init__(parent)
        self._pages = pages
        self._dest = dest
        self._cancel = threading.Event()
        self._thread = threading.Thread(target=self._run, name="save", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def cancel(self) -> None:
        self._cancel.set()

    def wait(self) -> None:
        self._thread.join()

    def _run(self) -> None:
        try:
            write_pdf(self._pages, self._dest, self.progress.emit, self._cancel.is_set)
        except SaveCancelled:
            self._dest.unlink(missing_ok=True)
            self.cancelled.emit()
        except Exception as e:
            self._dest.unlink(missing_ok=True)
            self.failed.emit(str(e))
        else:
            self.finished.emit()
