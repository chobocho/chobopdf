import pytest

from chobopdf.model.document import PageListModel
from chobopdf.render.thumbnailer import Thumbnailer
from conftest import wait_for


@pytest.fixture
def thumbnailer(app):
    thumbnailer = Thumbnailer(render_px=100)
    yield thumbnailer
    thumbnailer.stop()


def test_open_reports_page_count(thumbnailer, pdf_path):
    thumbnailer.open(pdf_path)
    assert wait_for(thumbnailer.opened) == (pdf_path, 3)


def test_open_failure_is_reported(thumbnailer, tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    thumbnailer.open(bad)
    path, message = wait_for(thumbnailer.openFailed)
    assert path == bad and message


def test_thumbnail_fits_render_size(thumbnailer, pdf_path):
    thumbnailer.open(pdf_path)
    wait_for(thumbnailer.opened)
    assert thumbnailer.get((pdf_path, 1)) is None

    thumbnailer.set_wanted([(pdf_path, 1)])
    assert wait_for(thumbnailer.thumbnailReady) == ((pdf_path, 1),)
    image = thumbnailer.get((pdf_path, 1))
    assert (image.width(), image.height()) == (100, 50)


def test_close_drops_cached_thumbnails(thumbnailer, pdf_path):
    thumbnailer.open(pdf_path)
    wait_for(thumbnailer.opened)
    thumbnailer.set_wanted([(pdf_path, 0)])
    wait_for(thumbnailer.thumbnailReady)

    thumbnailer.close(pdf_path)
    thumbnailer.open(pdf_path)  # queued behind the close, so it has run by now
    wait_for(thumbnailer.opened)
    assert thumbnailer.get((pdf_path, 0)) is None


def test_model_lists_every_page(app, pdf_path):
    model = PageListModel()
    model.set_document(pdf_path, 3)
    assert model.rowCount() == 3
    assert [model.page(row).key for row in range(3)] == [(pdf_path, i) for i in range(3)]
