import pikepdf
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest

from chobopdf.model.document import PageRef
from chobopdf.ui.main_window import MainWindow
from chobopdf.ui.page_delegate import CELL_SIZE
from conftest import make_pdf, wait_for

PAGES = 12


@pytest.fixture
def window(app, tmp_path):
    path = make_pdf(tmp_path / "pages.pdf", [(200, 300)] * PAGES)
    window = MainWindow()
    window.resize(CELL_SIZE.width() * 4 + 60, 600)  # room for 4 columns
    window.show()
    window.open_file(path)
    wait_for(window._thumbnailer.opened)
    app.processEvents()
    yield window
    window._undo_stack.setClean()  # skip the unsaved-changes prompt
    window.close()


def marked(window):
    """Original page numbers of the marked pages, in document order."""
    return [page.index for page in window._model.pages() if page.marked]


def mark(window, rows):
    window._view._select_rows(rows)
    window._view.toggle_mark_selected()


def test_m_marks_and_unmarks_without_changing_the_document(window):
    view = window._view
    view.setFocus()
    view._select_rows([2])
    QTest.keyClick(view, Qt.Key.Key_M)
    assert marked(window) == [2]
    assert not window.isWindowModified()                       # a mark is not an edit
    assert not window._undo_stack.canUndo()
    assert "표시 1쪽" in window.statusBar().currentMessage()

    view._select_rows([2, 3])                                  # mixed: marks the rest
    QTest.keyClick(view, Qt.Key.Key_M)
    assert marked(window) == [2, 3]
    QTest.keyClick(view, Qt.Key.Key_M)                         # all marked: unmarks them
    assert marked(window) == []
    assert window._model.page(2) == PageRef(window._document, 2)


def test_mark_is_painted_on_the_top_right_corner(window, app):
    view = window._view
    while window._thumbnailer.get(window._model.page(0).key) is None:
        wait_for(window._thumbnailer.thumbnailReady)

    def reddish_pixels():
        app.processEvents()
        cell = view.visualRect(window._model.index(0))
        image = view.viewport().grab(cell).toImage()
        half = image.width() // 2
        count = {"left": 0, "right": 0}
        for y in range(image.height() // 2):
            for x in range(image.width()):
                color = QColor(image.pixel(x, y))
                if color.red() > 180 and color.green() < 90 and color.blue() < 130:
                    count["left" if x < half else "right"] += 1
        return count

    view.clearSelection()
    assert reddish_pixels() == {"left": 0, "right": 0}
    window._model.set_marked([0], True)
    pixels = reddish_pixels()
    assert pixels["right"] > 100 and pixels["left"] == 0


def test_mark_follows_its_page_through_edits_and_undo(window):
    view = window._view
    mark(window, [1])
    view._select_rows([1])
    view.move_selected_to(PAGES)                               # to the end
    assert window._model.marked_rows() == [PAGES - 1]

    mark(window, [0])                                          # marked after the move...
    window._undo_stack.undo()                                  # ...and still there after undoing it
    assert marked(window) == [0, 1]
    assert window._model.marked_rows() == [0, 1]

    view._select_rows([1])
    view.rotate_selected(90)
    view.delete_selected()
    assert marked(window) == [0]
    window._undo_stack.undo()
    assert marked(window) == [0, 1]
    window._undo_stack.undo()                                  # the rotation
    assert marked(window) == [0, 1]


def test_copies_are_not_marked(window):
    view = window._view
    mark(window, [0])
    view._select_rows([0])
    view.duplicate_selected()
    view._select_rows([0])
    view.copy_selected()
    view.paste()
    assert [page.index for page in window._model.pages()][:3] == [0, 0, 0]
    assert window._model.marked_rows() == [0]


def test_next_and_previous_mark_wrap_around(window):
    view = window._view
    mark(window, [2, 7])
    view._select_rows([0])
    view.setFocus()
    QTest.keyClick(view, Qt.Key.Key_N)
    assert view.selected_rows() == [2]
    QTest.keyClick(view, Qt.Key.Key_N)
    assert view.selected_rows() == [7]
    QTest.keyClick(view, Qt.Key.Key_N)
    assert view.selected_rows() == [2]                         # wrapped
    QTest.keyClick(view, Qt.Key.Key_N, Qt.KeyboardModifier.ShiftModifier)
    assert view.selected_rows() == [7]

    view.clear_marks()
    assert marked(window) == []
    QTest.keyClick(view, Qt.Key.Key_N)                         # nothing to go to
    assert view.selected_rows() == [7]


def test_marks_stay_on_their_pages_after_saving_but_are_not_written(window):
    view = window._view
    mark(window, [3])
    view._select_rows([0])
    view.delete_selected()                                     # the marked page is now row 2
    source = window._document
    window.save_to(source)
    wait_for(window._thumbnailer.opened)

    assert window._model.rowCount() == PAGES - 1
    assert window._model.marked_rows() == [2]
    assert not window.isWindowModified()
    with pikepdf.open(source) as pdf:
        assert len(pdf.pages) == PAGES - 1
        assert "/Outlines" not in pdf.Root
