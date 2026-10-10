import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from chobopdf.ui.main_window import MainWindow
from conftest import make_pdf, wait_for


@pytest.fixture
def window(app, tmp_path):
    # Page 0 is portrait 200x400, page 1 landscape 400x200.
    path = make_pdf(tmp_path / "pages.pdf", [(200, 400), (400, 200), (200, 400)])
    window = MainWindow()
    window.resize(1000, 700)
    window.show()
    window.open_file(path)
    wait_for(window._thumbnailer.opened)
    app.processEvents()
    yield window
    window._undo_stack.setClean()  # skip the unsaved-changes prompt
    window.close()


def shown(window):
    """Size in pixels of the image the preview currently shows, once its render has arrived."""
    wait_for(window._thumbnailer.previewReady)
    pixmap = window._preview._image.pixmap()
    return pixmap.width(), pixmap.height()


def double_click(window, row):
    index = window._model.index(row)
    window._view.setCurrentIndex(index)
    window._view.doubleClicked.emit(index)


def test_double_click_splits_the_window_in_half(window, app):
    assert window._preview.isHidden()
    double_click(window, 0)
    app.processEvents()
    assert window._preview.isVisible()
    left, right = window._splitter.sizes()
    assert abs(left - right) <= 10
    assert window._preview._title.text() == "1쪽"

    width, height = shown(window)
    assert height == pytest.approx(width * 2, abs=2)          # portrait 200x400 page
    assert width > 300                                         # far sharper than a thumbnail
    assert width == window._preview._target_width()            # fitted to the pane


def test_preview_follows_the_current_page_and_its_rotation(window, app):
    double_click(window, 0)
    shown(window)

    window._view._select_rows([1])                             # single click elsewhere
    assert window._preview._title.text() == "2쪽"
    width, height = shown(window)
    assert width == pytest.approx(height * 2, abs=2)           # landscape page

    window._view.rotate_selected(90)
    width, height = shown(window)
    assert height == pytest.approx(width * 2, abs=2)           # now shown upright

    window._view.delete_selected()                             # the next page takes its place
    assert window._preview._title.text() == "2쪽"
    width, height = shown(window)
    assert height == pytest.approx(width * 2, abs=2)


def test_zoom_enlarges_and_close_restores_the_grid(window, app):
    double_click(window, 0)
    fit_width, _ = shown(window)
    for _ in range(3):                                         # 100% -> 125% -> 150% -> 200%
        window._preview._zoom_in_button.click()
    assert window._preview._zoom_label.text() == "200%"
    width, _ = shown(window)
    assert width == pytest.approx(fit_width * 2, abs=8)

    window.close_preview()
    app.processEvents()
    assert window._preview.isHidden()
    assert window._view.width() > 900


def test_page_keys_step_through_pages_while_the_preview_has_focus(window, app):
    double_click(window, 0)
    shown(window)
    pane = window._preview._scroll
    pane.setFocus()

    QTest.keyClick(pane, Qt.Key.Key_PageDown)
    assert window._preview._title.text() == "2쪽"
    assert window._view.selected_rows() == [1]
    width, height = shown(window)
    assert width == pytest.approx(height * 2, abs=2)           # the landscape page
    assert pane.hasFocus()                                     # keeps the keyboard

    QTest.keyClick(pane, Qt.Key.Key_PageDown)
    QTest.keyClick(pane, Qt.Key.Key_PageDown)                  # already on the last page
    assert window._preview._title.text() == "3쪽"
    QTest.keyClick(pane, Qt.Key.Key_PageUp)
    assert window._preview._title.text() == "2쪽"


def test_preview_size_controls(window, app):
    double_click(window, 0)
    fit_width, _ = shown(window)
    preview = window._preview

    preview._zoom_out_button.click()
    assert preview._zoom_label.text() == "75%"
    width, _ = shown(window)
    assert width == pytest.approx(fit_width * 0.75, abs=6)

    QTest.keyClick(preview._scroll, Qt.Key.Key_Minus, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(preview._scroll, Qt.Key.Key_Minus, Qt.KeyboardModifier.ControlModifier)
    assert preview._zoom_label.text() == "25%"
    assert not preview._zoom_out_button.isEnabled()            # smallest size

    QTest.keyClick(preview._scroll, Qt.Key.Key_0, Qt.KeyboardModifier.ControlModifier)
    assert preview._zoom_label.text() == "100%"
    width, _ = shown(window)
    assert width == pytest.approx(fit_width, abs=6)


def test_fit_page_shows_the_whole_page(window, app):
    double_click(window, 0)                                    # portrait 200x400 page
    shown(window)
    preview = window._preview
    viewport = preview._scroll.viewport()

    preview._fit_page_button.click()
    width, height = shown(window)
    assert height == pytest.approx(viewport.height() - 16, abs=3)   # as tall as the pane
    QTest.keyClick(preview._scroll, Qt.Key.Key_0, Qt.KeyboardModifier.ControlModifier)
    assert shown(window)[1] > viewport.height()                # fit width: taller than the pane
    QTest.keyClick(preview._scroll, Qt.Key.Key_9, Qt.KeyboardModifier.ControlModifier)
    width, height = shown(window)
    assert height == pytest.approx(viewport.height() - 16, abs=3)   # Ctrl+9 fits the page again
    assert width < viewport.width()
    fitted_percent = preview._zoom_label.text()

    window._view.select_page(1)                                # landscape: limited by the width
    width, height = shown(window)
    assert width == pytest.approx(viewport.width() - 16, abs=3)
    assert height < viewport.height()
    assert preview._zoom_label.text() == "100%"

    window._view.select_page(2)                                # back to a portrait page
    shown(window)
    assert preview._zoom_label.text() == fitted_percent

    preview._zoom_in_button.click()                            # steps on from the fitted size
    fitted = int(fitted_percent.rstrip("%"))
    stepped = int(preview._zoom_label.text().rstrip("%"))
    assert stepped == min(step for step in (25, 50, 75, 100) if step > fitted)
