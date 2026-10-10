import pikepdf
import pytest

from chobopdf.model.document import PageRef
from chobopdf.pdfio.saver import write_pdf
from chobopdf.render.thumbnailer import Thumbnailer
from chobopdf.ui.main_window import MainWindow
from conftest import make_pdf, wait_for

PASSWORD = "열려라 참깨"
WIDTHS = [100, 110, 120]  # each page is identified by its width


@pytest.fixture
def locked(tmp_path):
    """A PDF that cannot be opened without PASSWORD."""
    plain = make_pdf(tmp_path / "plain.pdf", [(width, 200) for width in WIDTHS])
    path = tmp_path / "locked.pdf"
    with pikepdf.open(plain) as pdf:
        pdf.save(path, encryption=pikepdf.Encryption(user=PASSWORD, owner=PASSWORD))
    return path


def widths(path):
    with pikepdf.open(path) as pdf:  # no password: fails if the file is protected
        return [int(page.mediabox[2]) for page in pdf.pages]


@pytest.fixture
def thumbnailer(app):
    thumbnailer = Thumbnailer(render_px=100)
    yield thumbnailer
    thumbnailer.stop()


def test_protected_file_asks_for_its_password(thumbnailer, locked):
    thumbnailer.open(locked)
    assert wait_for(thumbnailer.passwordRequired) == (locked,)
    thumbnailer.open(locked, "wrong")
    assert wait_for(thumbnailer.passwordRequired) == (locked,)
    thumbnailer.open(locked, PASSWORD)
    assert wait_for(thumbnailer.opened) == (locked, len(WIDTHS))


def test_password_is_kept_for_reopening_after_close(thumbnailer, locked):
    thumbnailer.open(locked, PASSWORD)
    wait_for(thumbnailer.opened)
    thumbnailer.close(locked, wait=True)
    thumbnailer.set_wanted([(locked, 0)])
    wait_for(thumbnailer.thumbnailReady)
    assert not thumbnailer.get((locked, 0)).isNull()


def test_write_reads_protected_sources_and_saves_without_a_password(locked, tmp_path):
    dest = tmp_path / "out.pdf"
    write_pdf([PageRef(locked, 2), PageRef(locked, 0)], dest, passwords={locked: PASSWORD})
    assert widths(dest) == [120, 100]


@pytest.fixture
def window(app):
    window = MainWindow()
    window.show()
    yield window
    window._undo_stack.setClean()  # skip the unsaved-changes prompt
    window.close()


def answer(window, monkeypatch, replies):
    """Answer the password prompts with `replies` in turn; returns the prompts that were shown."""
    asked = []
    replies = iter(replies)
    monkeypatch.setattr(window, "_ask_password",
                        lambda path, retry: (asked.append((path.name, retry)), next(replies))[1])
    return asked


def load(window, start):
    start()
    while window._loading is not None:
        wait_for(window._thumbnailer.opened)


def test_window_opens_a_protected_file_after_a_wrong_password(window, locked, monkeypatch):
    asked = answer(window, monkeypatch, ["wrong", PASSWORD])
    load(window, lambda: window.open_file(locked))
    assert asked == [("locked.pdf", False), ("locked.pdf", True)]
    assert window._model.pages() == [PageRef(locked, i) for i in range(len(WIDTHS))]
    assert window._document == locked

    # Opening it again in the same window does not ask a second time.
    load(window, lambda: window.add_files([locked]))
    assert len(asked) == 2
    assert window._model.rowCount() == 2 * len(WIDTHS)


def test_giving_no_password_skips_the_file_and_merges_the_rest(window, locked, tmp_path, monkeypatch):
    other = make_pdf(tmp_path / "other.pdf", [(300, 300)])
    answer(window, monkeypatch, [None])
    warnings = []
    monkeypatch.setattr("chobopdf.ui.main_window.QMessageBox.warning",
                        lambda parent, title, text, *args: warnings.append(text))
    load(window, lambda: window.open_files([locked, other]))
    assert window._model.pages() == [PageRef(other, 0)]
    assert len(warnings) == 1 and "locked.pdf" in warnings[0]
    assert window._passwords == {}


def test_saving_over_a_protected_file_removes_the_password(window, locked, monkeypatch):
    asked = answer(window, monkeypatch, [PASSWORD])
    load(window, lambda: window.open_file(locked))
    window._view._select_rows([0])
    window._view.delete_selected()
    window.save_to(locked)
    assert wait_for(window._thumbnailer.opened) == (locked, 2)  # reopened without asking again
    assert len(asked) == 1
    assert widths(locked) == [110, 120]
    assert not window.isWindowModified()
    assert window._passwords == {}


def test_extracting_from_a_protected_file(window, locked, tmp_path, monkeypatch):
    answer(window, monkeypatch, [PASSWORD])
    load(window, lambda: window.open_file(locked))
    dest = tmp_path / "locked_추출.pdf"
    window.save_to(dest, rows=[1])
    wait_for(window._save_job.finished)
    assert widths(dest) == [110]
    assert window._passwords == {locked: PASSWORD}  # the open file is still protected
