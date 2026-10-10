import pikepdf
import pytest

from chobopdf.model.document import PageRef
from chobopdf.pdfio.saver import SaveCancelled, write_pdf
from chobopdf.ui.main_window import MainWindow
from conftest import make_pdf, wait_for

WIDTHS = [100, 110, 120, 130, 140]  # each page is identified by its width


@pytest.fixture
def source(tmp_path):
    return make_pdf(tmp_path / "source.pdf", [(width, 200) for width in WIDTHS])


def read_pages(path):
    """(width, rotation) of every page in the file."""
    with pikepdf.open(path) as pdf:
        return [(int(page.mediabox[2]), int(page.obj.get("/Rotate", 0))) for page in pdf.pages]


def test_write_reorders_rotates_and_duplicates(source, tmp_path):
    pages = [
        PageRef(source, 4),
        PageRef(source, 0, 90),
        PageRef(source, 0),       # same page again, unrotated
        PageRef(source, 2, 270),
    ]
    dest = tmp_path / "out.pdf"
    seen = []
    write_pdf(pages, dest, progress=seen.append)
    assert read_pages(dest) == [(140, 0), (100, 90), (100, 0), (120, 270)]
    assert seen == sorted(seen) and seen[-1] == 100


def test_write_combines_several_sources(source, tmp_path):
    other = make_pdf(tmp_path / "other.pdf", [(300, 300)])
    dest = tmp_path / "out.pdf"
    write_pdf([PageRef(other, 0), PageRef(source, 1), PageRef(other, 0)], dest)
    assert read_pages(dest) == [(300, 0), (110, 0), (300, 0)]


def test_cancel_writes_nothing(source, tmp_path):
    dest = tmp_path / "out.pdf"
    with pytest.raises(SaveCancelled):
        write_pdf([PageRef(source, 0)], dest, is_cancelled=lambda: True)
    assert not dest.exists()


def test_cancel_while_writing_the_file(source, tmp_path):
    dest = tmp_path / "out.pdf"
    seen = []
    with pytest.raises(SaveCancelled):
        write_pdf([PageRef(source, i) for i in range(len(WIDTHS))], dest,
                  progress=seen.append, is_cancelled=lambda: bool(seen) and seen[-1] >= 50)
    assert seen[-1] < 100
    assert not dest.exists()


@pytest.fixture
def window(app, source):
    window = MainWindow()
    window.show()
    window.open_file(source)
    wait_for(window._thumbnailer.opened)
    yield window
    window._undo_stack.setClean()  # skip the unsaved-changes prompt
    window.close()


def edit(window):
    """Move the first page to the end and rotate the new first page."""
    view = window._view
    view._select_rows([0])
    view.move_selected_to(len(WIDTHS))
    view._select_rows([0])
    view.rotate_selected(90)
    return [(110, 90), (120, 0), (130, 0), (140, 0), (100, 0)]


def test_save_as_switches_to_the_new_file(window, source, tmp_path):
    expected = edit(window)
    dest = tmp_path / "copy.pdf"
    window.save_to(dest)
    assert wait_for(window._thumbnailer.opened) == (dest, len(WIDTHS))

    assert read_pages(dest) == expected
    assert read_pages(source) == [(width, 0) for width in WIDTHS]  # original untouched
    assert not dest.with_name("copy.pdf.tmp").exists()
    assert window._document == dest
    assert not window.isWindowModified()
    assert window._model.pages() == [PageRef(dest, i) for i in range(len(WIDTHS))]


def test_save_overwrites_the_open_source(window, source):
    # Have a thumbnail rendered first, so the source is really held open.
    while window._thumbnailer.get((source, 0)) is None:
        wait_for(window._thumbnailer.thumbnailReady)
    expected = edit(window)
    window.save_to(source)
    wait_for(window._thumbnailer.opened)

    assert read_pages(source) == expected
    assert not window.isWindowModified()
    # Thumbnails come from the rewritten file: page 0 is now the 110-wide page.
    while window._thumbnailer.get((source, 0)) is None:
        wait_for(window._thumbnailer.thumbnailReady)
    image = window._thumbnailer.get((source, 0))
    assert image.width() > image.height()  # 110x200 page rotated by 90
