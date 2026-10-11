from pathlib import Path

import pikepdf
import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent

import chobopdf
from chobopdf.model.document import PageRef
from chobopdf.ui.main_window import MERGED_NAME, MainWindow, natural_sorted
from chobopdf.ui.page_delegate import CELL_SIZE
from conftest import make_pdf, wait_for


@pytest.fixture
def files(tmp_path):
    """a.pdf: 2 pages 100 wide, b.pdf: 3 pages 200 wide, c.pdf: 1 page 300 wide."""
    return [make_pdf(tmp_path / f"{name}.pdf", [(width, 400)] * count)
            for name, width, count in [("a", 100, 2), ("b", 200, 3), ("c", 300, 1)]]


@pytest.fixture
def window(app):
    window = MainWindow()
    window.resize(CELL_SIZE.width() * 4 + 60, 600)
    window.show()
    yield window
    window._undo_stack.setClean()  # skip the unsaved-changes prompt
    window.close()


def load(window, start):
    """Run `start` and wait until the batch of files it opens has been applied."""
    start()
    while window._loading is not None:
        wait_for(window._thumbnailer.opened)


def sources(window):
    return [(page.source.stem, page.index) for page in window._model.pages()]


def widths(path):
    with pikepdf.open(path) as pdf:
        return [int(page.mediabox[2]) for page in pdf.pages]


def test_natural_sort_orders_numbers_by_value():
    names = ["scan10.pdf", "scan2.pdf", "Scan1.pdf", "b.pdf"]
    assert [p.name for p in natural_sorted([Path(n) for n in names])] == [
        "b.pdf", "Scan1.pdf", "scan2.pdf", "scan10.pdf"]


def test_opening_several_files_merges_them_in_order(window, files, tmp_path):
    a, b, c = files
    load(window, lambda: window.open_files([b, a, c]))
    assert sources(window) == [("b", 0), ("b", 1), ("b", 2), ("a", 0), ("a", 1), ("c", 0)]
    assert window._document is None
    assert MERGED_NAME in window.windowTitle()
    assert window.windowTitle().endswith(f"ChoboPDF V{chobopdf.__version__}")
    assert window.isWindowModified()  # nothing is saved yet

    dest = tmp_path / "merged.pdf"
    window.save_to(dest)
    wait_for(window._thumbnailer.opened)
    assert widths(dest) == [200, 200, 200, 100, 100, 300]
    assert window._document == dest
    assert not window.isWindowModified()
    assert window._model.pages() == [PageRef(dest, i) for i in range(6)]


def test_add_files_inserts_after_selection_and_undoes(window, files):
    a, b, c = files
    load(window, lambda: window.open_file(a))
    assert not window.isWindowModified()
    window._view._select_rows([0])
    load(window, lambda: window.add_files([c, b]))
    assert sources(window) == [("a", 0), ("c", 0), ("b", 0), ("b", 1), ("b", 2), ("a", 1)]
    assert window._view.selected_rows() == [1, 2, 3, 4]
    assert window._document == a
    assert window.isWindowModified()

    window._undo_stack.undo()
    assert sources(window) == [("a", 0), ("a", 1)]


def test_add_files_defaults_to_the_end(window, files):
    a, b, _ = files
    load(window, lambda: window.open_file(a))
    window._view.clearSelection()
    load(window, lambda: window.add_files([b]))
    assert sources(window)[:3] == [("a", 0), ("a", 1), ("b", 0)]


def test_unreadable_file_is_reported_and_the_rest_merged(window, files, tmp_path, monkeypatch):
    a, b, _ = files
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    warnings = []
    monkeypatch.setattr("chobopdf.ui.main_window.QMessageBox.warning",
                        lambda parent, title, text, *args: warnings.append(text))
    window.open_files([a, bad, b])
    while window._loading is not None:
        wait_for(window._thumbnailer.opened)
    assert sources(window) == [("a", 0), ("a", 1), ("b", 0), ("b", 1), ("b", 2)]
    assert len(warnings) == 1 and "bad.pdf" in warnings[0]


def test_files_dropped_on_the_grid_are_inserted_at_the_drop_position(window, files):
    a, b, _ = files
    load(window, lambda: window.open_file(b))
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(a))])
    position = QPointF(CELL_SIZE.width() - 10, 10)  # right half of the first cell
    assert window._view.drop_target(QPoint(CELL_SIZE.width() - 10, 10))[0] == 1
    event = QDropEvent(position, Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier)
    load(window, lambda: window._view.dropEvent(event))
    assert sources(window) == [("b", 0), ("a", 0), ("a", 1), ("b", 1), ("b", 2)]
