import pytest

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
    window._preview._zoom(3)                                   # 100% -> 200%
    assert window._preview._zoom_label.text() == "200%"
    width, _ = shown(window)
    assert width == pytest.approx(fit_width * 2, abs=8)

    window.close_preview()
    app.processEvents()
    assert window._preview.isHidden()
    assert window._view.width() > 900
