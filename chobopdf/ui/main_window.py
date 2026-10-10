import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QUndoStack
from PySide6.QtWidgets import (QFileDialog, QLabel, QMainWindow, QMessageBox, QProgressDialog,
                               QSlider)

from chobopdf.model.commands import InsertPages
from chobopdf.model.document import PageListModel, PageRef
from chobopdf.pdfio.saver import SaveJob
from chobopdf.render.thumbnailer import Thumbnailer
from chobopdf.ui.page_delegate import THUMB_SIZE
from chobopdf.ui.page_view import MAX_ZOOM, MIN_ZOOM, PageView, pdf_paths

APP_NAME = "ChoboPDF"
MERGED_NAME = "병합 문서"
_PDF_FILTER = "PDF 파일 (*.pdf)"


def natural_sorted(paths: list[Path]) -> list[Path]:
    """Sort by file name with numbers compared as numbers, so 2.pdf comes before 10.pdf."""
    def key(path: Path):
        return [int(part) if part.isdigit() else part.lower()
                for part in re.split(r"(\d+)", path.name)]
    return sorted(paths, key=key)


@dataclass
class _Load:
    """A batch of files being opened by the thumbnailer."""

    paths: list[Path]
    insert_row: int | None  # None: replace the document; otherwise add the pages at this row
    remaining: int
    counts: dict[Path, int] = field(default_factory=dict)
    failures: list[tuple[Path, str]] = field(default_factory=list)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._document: Path | None = None  # file that Save writes to; None for a merged document
        self._name: str | None = None  # shown in the title; None while nothing is open
        self._sources: set[Path] = set()  # files the thumbnailer holds open
        self._loading: _Load | None = None
        self._merge_folder: Path | None = None  # where Save As starts for a merged document
        self._save_job: SaveJob | None = None
        self._save_dest: Path | None = None
        self._scroll_after_open: int | None = None
        self._thumbnailer = Thumbnailer(round(THUMB_SIZE * self.devicePixelRatioF()), parent=self)
        self._thumbnailer.opened.connect(self._on_opened)
        self._thumbnailer.openFailed.connect(self._on_open_failed)
        self._model = PageListModel(self)
        self._undo_stack = QUndoStack(self)
        self._view = PageView(self._model, self._thumbnailer, self._undo_stack, self)
        self._view.filesDropped.connect(self._on_files_dropped)

        self.setCentralWidget(self._view)
        self.setWindowTitle(APP_NAME)
        self.resize(1100, 800)
        self.setAcceptDrops(True)

        file_menu = self.menuBar().addMenu("파일(&F)")
        self._add_action(file_menu, "열기(&O)…", QKeySequence.StandardKey.Open,
                         lambda: self._choose_files("PDF 열기"))
        self._add_action(file_menu, "여러 파일 병합(&M)…", "Ctrl+M",
                         lambda: self._choose_files("병합할 PDF 선택 (여러 개 선택)"))
        self._add_pages_action = self._add_action(
            file_menu, "PDF 추가(&I)…", "Ctrl+I", self._choose_files_to_add)
        file_menu.addSeparator()
        self._save_action = self._add_action(
            file_menu, "저장(&S)", QKeySequence.StandardKey.Save, self._save)
        self._save_as_action = self._add_action(
            file_menu, "다른 이름으로 저장(&A)…", "Ctrl+Shift+S", self._save_as)
        file_menu.addSeparator()
        self._add_action(file_menu, "끝내기(&X)", "Ctrl+Q", self.close)

        edit_menu = self.menuBar().addMenu("편집(&E)")
        undo_action = self._undo_stack.createUndoAction(self, "실행 취소")
        undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        redo_action = self._undo_stack.createRedoAction(self, "다시 실행")
        redo_action.setShortcuts([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
        edit_menu.addActions([undo_action, redo_action])
        edit_menu.addSeparator()
        view = self._view
        self._selection_actions = [
            self._add_action(edit_menu, "잘라내기(&T)", QKeySequence.StandardKey.Cut, view.cut_selected),
            self._add_action(edit_menu, "복사(&C)", QKeySequence.StandardKey.Copy, view.copy_selected),
        ]
        self._paste_action = self._add_action(
            edit_menu, "붙여넣기(&P)", QKeySequence.StandardKey.Paste, view.paste)
        self._selection_actions += [
            self._add_action(edit_menu, "복제(&D)", "Ctrl+D", view.duplicate_selected),
            self._add_action(edit_menu, "삭제(&L)", QKeySequence.StandardKey.Delete, view.delete_selected),
        ]
        edit_menu.addSeparator()
        self._selection_actions += [
            self._add_action(edit_menu, "오른쪽으로 회전(&R)", "R", lambda: view.rotate_selected(90)),
            self._add_action(edit_menu, "왼쪽으로 회전(&E)", "Shift+R", lambda: view.rotate_selected(-90)),
        ]
        edit_menu.addSeparator()
        self._add_action(edit_menu, "모두 선택(&A)", QKeySequence.StandardKey.SelectAll, view.selectAll)
        view.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        view.addActions(edit_menu.actions())

        # Thumbnail zoom: slider in the status bar, or Ctrl+wheel over the pages.
        zoom_slider = QSlider(Qt.Orientation.Horizontal, minimum=MIN_ZOOM, maximum=MAX_ZOOM,
                              singleStep=10, pageStep=25, fixedWidth=140, toolTip="썸네일 크기")
        zoom_label = QLabel(f"{MIN_ZOOM}%")
        zoom_slider.valueChanged.connect(view.set_zoom)
        view.zoomChanged.connect(zoom_slider.setValue)
        view.zoomChanged.connect(lambda percent: zoom_label.setText(f"{percent}%"))
        self.statusBar().addPermanentWidget(zoom_slider)
        self.statusBar().addPermanentWidget(zoom_label)

        self._undo_stack.cleanChanged.connect(self._on_clean_changed)
        view.selectionModel().selectionChanged.connect(self._update_state)
        for signal in (self._model.modelReset, self._model.rowsInserted, self._model.rowsRemoved):
            signal.connect(self._update_state)
        self._update_state()

    def _add_action(self, menu, text: str, shortcut, slot) -> QAction:
        action = QAction(text, self, shortcut=QKeySequence(shortcut))
        action.triggered.connect(lambda: (slot(), self._update_state()))
        menu.addAction(action)
        return action

    def _on_clean_changed(self, clean: bool) -> None:
        self.setWindowModified(not clean)
        self._update_state()

    def _busy(self) -> bool:
        return self._save_job is not None or self._loading is not None

    def _update_state(self, *_) -> None:
        selected = len(self._view.selected_rows())
        for action in self._selection_actions:
            action.setEnabled(selected > 0)
        self._paste_action.setEnabled(self._view.can_paste())
        self._add_pages_action.setEnabled(self._name is not None and not self._busy())
        can_save = self._model.rowCount() > 0 and not self._busy()
        self._save_action.setEnabled(can_save and self.isWindowModified())
        self._save_as_action.setEnabled(can_save)
        if self._loading is not None:
            return  # keep the "opening" message
        if self._name is None:
            self.statusBar().showMessage("PDF 파일을 열거나 창에 끌어다 놓으세요.")
            return
        message = f"{self._name} · {self._model.rowCount()}쪽"
        if selected:
            message += f" · {selected}쪽 선택"
        self.statusBar().showMessage(message)

    # --- opening ---------------------------------------------------------

    def open_file(self, path: Path) -> None:
        self.open_files([path])

    def open_files(self, paths: list[Path]) -> None:
        """Open one file, or merge several, in the given order, into a new unsaved document."""
        if paths and not self._busy() and self._confirm_discard():
            self._load(paths)

    def add_files(self, paths: list[Path], row: int | None = None) -> None:
        """Insert every page of `paths` before `row` (default: after the selection, else at the end)."""
        if not paths or self._busy() or self._name is None:
            return
        if row is None:
            selected = self._view.selected_rows()
            row = selected[-1] + 1 if selected else self._model.rowCount()
        self._load(paths, insert_row=row)

    def _load(self, paths: list[Path], insert_row: int | None = None) -> None:
        # One spelling per file, so it compares equal to a save target.
        paths = [path.resolve() for path in paths]
        self._loading = _Load(paths, insert_row, remaining=len(paths))
        self._update_state()
        self.statusBar().showMessage(f"여는 중… {paths[0].name}")
        for path in paths:
            self._thumbnailer.open(path)

    def _on_opened(self, path: Path, page_count: int) -> None:
        if self._loading is not None:
            self._loading.counts[path] = page_count
            self._on_load_progress()

    def _on_open_failed(self, path: Path, message: str) -> None:
        if self._loading is not None:
            self._loading.failures.append((path, message))
            self._on_load_progress()

    def _on_load_progress(self) -> None:
        load = self._loading
        load.remaining -= 1
        if load.remaining:
            return
        self._loading = None
        pages = [PageRef(path, index)
                 for path in load.paths for index in range(load.counts.get(path, 0))]
        if pages and load.insert_row is not None:
            self._sources |= load.counts.keys()
            row = min(load.insert_row, self._model.rowCount())
            self._undo_stack.push(InsertPages(self._model, row, pages, "PDF 추가"))
        elif pages:
            self._show_document(load, pages)
        self._update_state()
        if load.failures:
            details = "\n\n".join(f"{path}\n{message}" for path, message in load.failures)
            QMessageBox.warning(self, APP_NAME, f"파일을 열 수 없습니다.\n\n{details}")

    def _show_document(self, load: _Load, pages: list[PageRef]) -> None:
        previous, self._sources = self._sources, set(load.counts)
        self._undo_stack.clear()
        self._view.clear_clipboard()  # its pages may belong to a file being closed
        self._model.set_pages(pages)
        self._view.scroll_to_row(self._scroll_after_open or 0)
        self._scroll_after_open = None
        for path in previous - self._sources:
            self._thumbnailer.close(path)
        if len(load.paths) == 1:
            self._document = load.paths[0]
            self._name = self._document.name
            self._undo_stack.setClean()  # clear() alone does not undo an earlier resetClean()
        else:
            # A merge has no file of its own yet: Save asks for a name, and
            # the document counts as unsaved from the start.
            self._document = None
            self._name = MERGED_NAME
            self._merge_folder = load.paths[0].parent
            self._undo_stack.resetClean()
        self.setWindowTitle(f"{self._name}[*] - {APP_NAME}")

    def _choose_files(self, title: str) -> None:
        names, _ = QFileDialog.getOpenFileNames(self, title, "", _PDF_FILTER)
        self.open_files(natural_sorted([Path(name) for name in names]))

    def _choose_files_to_add(self) -> None:
        names, _ = QFileDialog.getOpenFileNames(self, "추가할 PDF 선택", "", _PDF_FILTER)
        self.add_files(natural_sorted([Path(name) for name in names]))

    def _on_files_dropped(self, paths: list[Path], row: int) -> None:
        self.add_files(natural_sorted(paths), row)

    def _confirm_discard(self) -> bool:
        if not self.isWindowModified():
            return True
        answer = QMessageBox.warning(
            self, APP_NAME, "저장하지 않은 변경 내용이 있습니다. 버리고 계속할까요?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        return answer == QMessageBox.StandardButton.Discard

    # --- saving ----------------------------------------------------------

    def _save(self) -> None:
        if self._document is None:
            self._save_as()
            return
        answer = QMessageBox.question(
            self, APP_NAME, f"원본 파일을 덮어씁니다. 계속할까요?\n{self._document}",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Save:
            self.save_to(self._document)

    def _save_as(self) -> None:
        if self._document is None:
            suggested = self._merge_folder / "병합.pdf"
        else:
            suggested = self._document.with_name(f"{self._document.stem}_편집.pdf")
        name, _ = QFileDialog.getSaveFileName(self, "다른 이름으로 저장", str(suggested), _PDF_FILTER)
        if name:
            path = Path(name)
            self.save_to(path if path.suffix else path.with_suffix(".pdf"))

    def save_to(self, dest: Path) -> None:
        """Write the edited document to `dest` in the background, then switch to it."""
        if self._busy():
            return
        self._save_dest = dest.resolve()
        # Written next to the target and swapped in at the end, so a failed
        # or cancelled save never damages an existing file.
        temp = self._save_dest.with_name(self._save_dest.name + ".tmp")
        job = self._save_job = SaveJob(self._model.pages(), temp, self)

        dialog = QProgressDialog(f"저장 중… {dest.name}", "취소", 0, 100, self)
        dialog.setWindowTitle(APP_NAME)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(300)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.canceled.connect(job.cancel)
        job.progress.connect(dialog.setValue)
        for signal in (job.finished, job.cancelled, job.failed):
            signal.connect(dialog.deleteLater)
        job.finished.connect(self._on_save_finished)
        job.cancelled.connect(self._on_save_cancelled)
        job.failed.connect(self._on_save_failed)
        job.start()
        self._update_state()

    def _end_save(self) -> Path:
        self._save_job.wait()
        self._save_job.deleteLater()
        self._save_job = None
        self._update_state()
        return self._save_dest

    def _on_save_finished(self) -> None:
        if self._save_job is None:  # window closed meanwhile
            return
        dest = self._end_save()
        temp = dest.with_name(dest.name + ".tmp")
        # Windows cannot replace a file that is open, and the target may be one we are showing.
        self._thumbnailer.close(dest, wait=True)
        try:
            os.replace(temp, dest)
        except OSError as e:
            temp.unlink(missing_ok=True)
            self._show_save_error(str(e))
            return
        # Continue from the saved file: its pages are now in the edited order.
        self._scroll_after_open = self._view.top_row()
        self._load([dest])

    def _on_save_cancelled(self) -> None:
        if self._save_job is None:
            return
        self._end_save()
        self.statusBar().showMessage("저장을 취소했습니다.", 5000)

    def _on_save_failed(self, message: str) -> None:
        if self._save_job is None:
            return
        self._end_save()
        self._show_save_error(message)

    def _show_save_error(self, message: str) -> None:
        QMessageBox.warning(self, APP_NAME, f"저장하지 못했습니다.\n{self._save_dest}\n\n{message}")

    # --- files dropped outside the page grid, or before anything is open ---

    def dragEnterEvent(self, event) -> None:
        if pdf_paths(event.mimeData()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = pdf_paths(event.mimeData())
        if paths:
            event.acceptProposedAction()
            # Deferred: a confirmation dialog must not open while the drop is still in progress.
            QTimer.singleShot(0, lambda: self.open_files(natural_sorted(paths)))

    def closeEvent(self, event) -> None:
        if not self._confirm_discard():
            event.ignore()
            return
        if self._save_job is not None:
            self._save_job.cancel()
            self._save_job.wait()
            self._save_job = None
        self._thumbnailer.stop()
        super().closeEvent(event)
