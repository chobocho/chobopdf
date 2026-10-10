import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pypdfium2 as pdfium
import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def make_pdf(path, sizes):
    doc = pdfium.PdfDocument.new()
    for width, height in sizes:
        doc.new_page(width, height)
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def pdf_path(tmp_path):
    return make_pdf(tmp_path / "sample.pdf", [(200, 400), (400, 200), (200, 400)])


def wait_for(signal, timeout_ms=5000):
    """Run the event loop until `signal` fires; return its arguments."""
    loop = QEventLoop()
    received = []
    signal.connect(lambda *args: (received.append(args), loop.quit()))
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    assert received, "signal did not fire"
    return received[0]
