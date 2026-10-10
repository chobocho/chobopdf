import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from chobopdf.ui.main_window import MainWindow
from chobopdf.ui.page_delegate import CELL_SIZE
from conftest import make_pdf, wait_for

PAGES = 20


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


def order(window):
    model = window._model
    return [model.page(row).index for row in range(model.rowCount())]


def select(window, rows):
    window._view._select_rows(rows)


def test_drop_target_follows_grid(window):
    view = window._view
    w, h = CELL_SIZE.width(), CELL_SIZE.height()
    assert view._columns() == 4
    assert view.drop_target(QPoint(10, 10))[0] == 0             # left half of first cell
    assert view.drop_target(QPoint(w - 10, 10))[0] == 1         # right half of first cell
    assert view.drop_target(QPoint(w * 4 - 10, 10))[0] == 4     # end of first row
    assert view.drop_target(QPoint(w + 10, h + 10))[0] == 5     # second row
    assert view.drop_target(QPoint(w * 2, h * 20))[0] == PAGES  # below the last page


def test_move_selection_and_undo(window):
    select(window, [0, 1])
    window._view.move_selected_to(5)
    assert order(window)[:6] == [2, 3, 4, 0, 1, 5]
    assert window._view.selected_rows() == [3, 4]
    assert window.isWindowModified()
    window._undo_stack.undo()
    assert order(window) == list(range(PAGES))
    assert window._view.selected_rows() == [0, 1]
    assert not window.isWindowModified()


def test_keyboard_shortcuts(window):
    view = window._view
    view.setFocus()
    select(window, [2])
    QTest.keyClick(view, Qt.Key.Key_R)
    assert window._model.page(2).rotation == 90
    QTest.keyClick(view, Qt.Key.Key_R, Qt.KeyboardModifier.ShiftModifier)
    QTest.keyClick(view, Qt.Key.Key_R, Qt.KeyboardModifier.ShiftModifier)
    assert window._model.page(2).rotation == 270

    QTest.keyClick(view, Qt.Key.Key_Delete)
    assert order(window)[:4] == [0, 1, 3, 4]
    assert view.selected_rows() == [2]  # the page that slid into place

    QTest.keyClick(view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert order(window) == list(range(PAGES))


def test_copy_paste_and_duplicate(window):
    view = window._view
    select(window, [0, 1])
    view.copy_selected()
    select(window, [3])
    view.paste()
    assert order(window)[:7] == [0, 1, 2, 3, 0, 1, 4]
    assert view.selected_rows() == [4, 5]
    view.duplicate_selected()
    assert order(window)[:9] == [0, 1, 2, 3, 0, 1, 0, 1, 4]
    assert window._model.rowCount() == PAGES + 4


def test_cut_then_paste_moves_pages(window):
    view = window._view
    select(window, [0])
    view.cut_selected()
    select(window, [PAGES - 2])
    view.paste()
    assert order(window) == [*range(1, PAGES), 0]


def test_zoom_doubles_cells_and_rerenders_sharper(window, app):
    view = window._view
    key = window._model.page(0).key
    while window._thumbnailer.get(key) is None:
        wait_for(window._thumbnailer.thumbnailReady)
    assert window._thumbnailer.get(key).height() == 160

    view.set_zoom(500)  # clamped to the 200% maximum
    assert view.zoom() == 200
    assert view.gridSize().width() == 320 + (CELL_SIZE.width() - 160)
    assert view._columns() == 2
    while window._thumbnailer.get(key).height() != 320:
        wait_for(window._thumbnailer.thumbnailReady)

    view.set_zoom(100)
    assert view.gridSize() == CELL_SIZE
