import pytest
from PySide6.QtGui import QImage

from chobopdf.render.thumbnailer import EXPORT_DPI
from chobopdf.ui.main_window import MainWindow
from conftest import make_pdf, wait_for


@pytest.fixture
def window(app, tmp_path):
    # 72 points to the inch: page 0 is 2 x 4 inches, page 1 is 4 x 2.
    path = make_pdf(tmp_path / "pages.pdf", [(144, 288), (288, 144), (144, 288)])
    window = MainWindow()
    window.show()
    window.open_file(path)
    wait_for(window._thumbnailer.opened)
    app.processEvents()
    yield window
    window._undo_stack.setClean()  # skip the unsaved-changes prompt
    window.close()


def export(window, targets):
    window.export_jpg(targets)
    while window._exporting is not None:
        wait_for(window._thumbnailer.exported)


def size(path):
    image = QImage(str(path))
    assert not image.isNull()
    return image.width(), image.height()


def test_pages_are_saved_as_jpg_at_export_resolution(window, tmp_path):
    first, second = tmp_path / "one.jpg", tmp_path / "two.jpg"
    export(window, {0: first, 1: second})

    assert first.read_bytes()[:2] == b"\xff\xd8"                    # JPEG signature
    assert size(first) == pytest.approx((2 * EXPORT_DPI, 4 * EXPORT_DPI), abs=1)
    assert size(second) == pytest.approx((4 * EXPORT_DPI, 2 * EXPORT_DPI), abs=1)
    assert not (tmp_path / "pages_3.jpg").exists()                 # only the pages asked for


def test_a_rotated_page_is_saved_as_it_is_shown(window, tmp_path):
    window._view.select_page(0)
    window._view.rotate_selected(90)
    dest = tmp_path / "turned.jpg"
    export(window, {0: dest})
    assert size(dest) == pytest.approx((4 * EXPORT_DPI, 2 * EXPORT_DPI), abs=1)


def test_one_selected_page_asks_for_a_file_and_several_for_a_folder(window, tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    suggested = []
    monkeypatch.setattr(
        "chobopdf.ui.main_window.QFileDialog.getSaveFileName",
        lambda parent, title, path, filter: (suggested.append(path), (str(out / "picked"), ""))[1])
    monkeypatch.setattr("chobopdf.ui.main_window.QFileDialog.getExistingDirectory",
                        lambda parent, title, path: str(out))

    assert not window._export_action.isEnabled()                   # nothing selected yet
    window._view.select_page(1)
    assert window._export_action.isEnabled()
    assert window._export_action in window._view.actions()         # offered on right-click
    window._export_action.trigger()
    while window._exporting is not None:
        wait_for(window._thumbnailer.exported)
    assert suggested[0].endswith("pages_2.jpg")
    assert (out / "picked.jpg").exists()                           # extension added

    window._view._select_rows([0, 2])
    window._export_action.trigger()
    while window._exporting is not None:
        wait_for(window._thumbnailer.exported)
    assert sorted(path.name for path in out.iterdir()) == ["pages_1.jpg", "pages_3.jpg", "picked.jpg"]


def test_a_file_that_cannot_be_written_is_reported(window, tmp_path, monkeypatch):
    warnings = []
    monkeypatch.setattr("chobopdf.ui.main_window.QMessageBox.warning",
                        lambda *args: warnings.append(args[2]))
    export(window, {0: tmp_path / "missing folder" / "page.jpg", 1: tmp_path / "ok.jpg"})
    assert (tmp_path / "ok.jpg").exists()
    assert len(warnings) == 1 and "page.jpg" in warnings[0]
