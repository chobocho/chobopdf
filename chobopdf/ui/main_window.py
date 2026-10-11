import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QShortcut, QUndoStack
from PySide6.QtWidgets import (QFileDialog, QInputDialog, QLabel, QLineEdit, QMainWindow,
                               QMessageBox, QProgressDialog, QSlider, QSplitter)

from chobopdf import __version__
from chobopdf.model.commands import InsertPages
from chobopdf.model.document import PageListModel, PageRef
from chobopdf.pdfio.saver import SaveJob
from chobopdf.render.thumbnailer import Thumbnailer
from chobopdf.ui.help_dialog import HelpDialog
from chobopdf.ui.page_delegate import THUMB_SIZE
from chobopdf.ui.page_view import MAX_ZOOM, MIN_ZOOM, PageView, pdf_paths
from chobopdf.ui.preview_pane import FOCUS_FRAME, PreviewPane

APP_NAME = "ChoboPDF"
APP_TITLE = f"{APP_NAME} V{__version__}"  # shown in the title bar
MERGED_NAME = "병합 문서"
_PDF_FILTER = "PDF 파일 (*.pdf)"
_JPG_FILTER = "JPEG 이미지 (*.jpg)"


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
    locked: list[Path] = field(default_factory=list)  # files waiting for their password
    asking: bool = False  # a password prompt is open


@dataclass
class _Export:
    """A batch of pages being saved as images by the thumbnailer."""

    total: int
    folder: Path
    remaining: int
    failures: list[Path] = field(default_factory=list)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._document: Path | None = None  # file that Save writes to; None for a merged document
        self._name: str | None = None  # shown in the title; None while nothing is open
        self._sources: set[Path] = set()  # files the thumbnailer holds open
        self._passwords: dict[Path, str] = {}  # of the protected files among them
        self._loading: _Load | None = None
        self._merge_folder: Path | None = None  # where Save As starts for a merged document
        self._save_job: SaveJob | None = None
        self._save_dest: Path | None = None
        self._save_is_copy = False  # the running save leaves the open document as it is
        self._close_after_save = False  # the running save was chosen when closing the window
        self._save_extracted = 0  # pages the running save extracts; 0 when it writes the document
        self._exporting: _Export | None = None
        self._scroll_after_open: int | None = None
        self._marks_after_open: list[int] = []  # rows to mark again once a saved file is reopened
        self._help: HelpDialog | None = None
        self._thumbnailer = Thumbnailer(round(THUMB_SIZE * self.devicePixelRatioF()), parent=self)
        self._thumbnailer.opened.connect(self._on_opened)
        self._thumbnailer.openFailed.connect(self._on_open_failed)
        self._thumbnailer.passwordRequired.connect(self._on_password_required)
        self._thumbnailer.exported.connect(self._on_exported)
        self._model = PageListModel(self)
        self._undo_stack = QUndoStack(self)
        self._view = PageView(self._model, self._thumbnailer, self._undo_stack, self)
        self._view.filesDropped.connect(self._on_files_dropped)

        # Double-clicking a page splits the window and shows that page large on the right.
        self._preview = PreviewPane(self._thumbnailer, self)
        self._preview.hide()
        self._preview.closeRequested.connect(self.close_preview)
        self._preview.pageStepRequested.connect(self._step_preview)
        self._splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self._splitter.addWidget(self._view)
        self._splitter.addWidget(self._preview)
        self._splitter.setChildrenCollapsible(False)
        self._view.doubleClicked.connect(self.open_preview)
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            QShortcut(QKeySequence(key), self._view, self._enter_preview,
                      context=Qt.ShortcutContext.WidgetShortcut)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self.close_preview)
        # Sizing works wherever the focus is, also right after the preview has been opened.
        for keys, slot in (("Ctrl++", self._preview.zoom_in), ("Ctrl+=", self._preview.zoom_in),
                           ("Ctrl+-", self._preview.zoom_out),
                           ("Ctrl+0", self._preview.fit_to_width),
                           ("Ctrl+9", self._preview.fit_to_page)):
            QShortcut(QKeySequence(keys), self, slot)

        self.setCentralWidget(self._splitter)
        self.setWindowTitle(APP_TITLE)
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
        self._save_copy_action = self._add_action(
            file_menu, "사본으로 저장(&C)…", "Ctrl+Alt+S", self._save_copy)
        file_menu.addSeparator()
        self._extract_action = self._add_action(
            file_menu, "선택한 페이지를 PDF로 추출(&E)…", "Ctrl+E", self._extract)
        self._export_action = self._add_action(
            file_menu, "선택한 페이지를 JPG로 저장(&J)…", "Ctrl+J", self._choose_jpg_target)
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
        # Marks: a bookmark ribbon on the pages to keep track of while moving and deleting others.
        self._selection_actions.append(
            self._add_action(edit_menu, "표시 추가/삭제(&M)", "M", view.toggle_mark_selected))
        self._mark_actions = [
            self._add_action(edit_menu, "다음 표시로 이동(&N)", "N", lambda: view.go_to_mark(1)),
            self._add_action(edit_menu, "이전 표시로 이동(&B)", "Shift+N", lambda: view.go_to_mark(-1)),
            self._add_action(edit_menu, "표시 모두 지우기(&K)", "Ctrl+Shift+M", view.clear_marks),
        ]
        edit_menu.addSeparator()
        self._add_action(edit_menu, "모두 선택(&A)", QKeySequence.StandardKey.SelectAll, view.selectAll)
        view.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        view.addActions(edit_menu.actions())
        separator = QAction(self)
        separator.setSeparator(True)
        view.addActions([separator, self._extract_action, self._export_action])

        help_menu = self.menuBar().addMenu("도움말(&H)")
        self._add_action(help_menu, "도움말(&H)", "F1", self.show_help)

        # Thumbnail zoom: slider in the status bar, or Ctrl+wheel over the pages.
        # Focus by click only, so Tab goes straight between the page grid and the preview.
        zoom_slider = QSlider(Qt.Orientation.Horizontal, minimum=MIN_ZOOM, maximum=MAX_ZOOM,
                              singleStep=10, pageStep=25, fixedWidth=140, toolTip="썸네일 크기",
                              focusPolicy=Qt.FocusPolicy.ClickFocus)
        zoom_label = QLabel(f"{MIN_ZOOM}%")
        zoom_slider.valueChanged.connect(view.set_zoom)
        view.zoomChanged.connect(zoom_slider.setValue)
        view.zoomChanged.connect(lambda percent: zoom_label.setText(f"{percent}%"))
        self.statusBar().addPermanentWidget(zoom_slider)
        self.statusBar().addPermanentWidget(zoom_label)

        view.selectionModel().currentChanged.connect(self._update_preview)
        for signal in (self._model.modelReset, self._model.rowsInserted, self._model.rowsRemoved,
                       self._model.dataChanged):
            signal.connect(self._update_preview)

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
        return (self._save_job is not None or self._loading is not None
                or self._exporting is not None)

    def _update_state(self, *_) -> None:
        selected = len(self._view.selected_rows())
        for action in self._selection_actions:
            action.setEnabled(selected > 0)
        self._paste_action.setEnabled(self._view.can_paste())
        marked = len(self._model.marked_rows())
        for action in self._mark_actions:
            action.setEnabled(marked > 0)
        self._add_pages_action.setEnabled(self._name is not None and not self._busy())
        can_save = self._model.rowCount() > 0 and not self._busy()
        self._save_action.setEnabled(can_save and self.isWindowModified())
        self._save_as_action.setEnabled(can_save)
        self._save_copy_action.setEnabled(can_save)
        self._extract_action.setEnabled(selected > 0 and not self._busy())
        self._export_action.setEnabled(selected > 0 and not self._busy())
        if self._loading is not None or self._exporting is not None:
            return  # keep the "opening" or "saving images" message
        if self._name is None:
            self.statusBar().showMessage("PDF 파일을 열거나 창에 끌어다 놓으세요.")
            return
        message = f"{self._name} · {self._model.rowCount()}쪽"
        if selected:
            message += f" · {selected}쪽 선택"
        if marked:
            message += f" · 표시 {marked}쪽"
        self.statusBar().showMessage(message)

    def show_help(self) -> None:
        if self._help is None:
            self._help = HelpDialog(self)
        self._help.show()
        self._help.raise_()
        self._help.activateWindow()

    # --- preview ---------------------------------------------------------

    def open_preview(self, *_) -> None:
        if not self._view.currentIndex().isValid():
            return
        if self._preview.isHidden():
            self._preview.show()
            self._view.setStyleSheet(FOCUS_FRAME)  # with two panes, show which one has the keyboard
            half = self._splitter.width() // 2
            self._splitter.setSizes([half, half])
        self._update_preview()

    def _enter_preview(self) -> None:
        """Enter on a page: open the preview and hand it the keyboard."""
        self.open_preview()
        if self._preview.isVisible():
            self._preview.setFocus()

    def close_preview(self) -> None:
        self._preview.hide()
        self._preview.show_page(None, 0)
        self._view.setStyleSheet("")

    def _step_preview(self, step: int) -> None:
        current = self._view.currentIndex()
        row = current.row() + step if current.isValid() else 0
        if 0 <= row < self._model.rowCount():
            self._view.select_page(row)  # the preview follows the current page

    def _update_preview(self, *_) -> None:
        """Keep the preview on the current page while it is open."""
        if self._preview.isHidden():
            return
        current = self._view.currentIndex()
        if current.isValid():
            self._preview.show_page(self._model.page(current.row()), current.row() + 1)
        else:
            self._preview.show_page(None, 0)

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
            self._thumbnailer.open(path, self._passwords.get(path))

    def _on_opened(self, path: Path, page_count: int) -> None:
        if self._loading is not None:
            self._loading.counts[path] = page_count
            self._on_load_progress()

    def _on_open_failed(self, path: Path, message: str) -> None:
        if self._loading is not None:
            self._loading.failures.append((path, message))
            self._on_load_progress()

    def _on_password_required(self, path: Path) -> None:
        load = self._loading
        if load is None:
            return
        load.locked.append(path)
        if load.asking:  # one prompt at a time; this file is asked about next
            return
        load.asking = True
        while load.locked:
            path = load.locked.pop(0)
            # A password we already have was the one just refused.
            password = self._ask_password(path, retry=self._passwords.pop(path, None) is not None)
            if password is None:
                load.failures.append((path, "암호를 입력하지 않아 열지 않았습니다."))
                self._on_load_progress()
            else:
                self._passwords[path] = password
                self._thumbnailer.open(path, password)
        load.asking = False

    def _ask_password(self, path: Path, retry: bool) -> str | None:
        """Ask for the password of a protected file; None if the user gives up."""
        prompt = "암호가 맞지 않습니다. 다시 입력하세요." if retry else "암호가 걸린 PDF입니다. 암호를 입력하세요."
        password, ok = QInputDialog.getText(self, APP_NAME, f"{prompt}\n{path.name}",
                                            QLineEdit.EchoMode.Password)
        return password if ok else None

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
        marks, self._marks_after_open = set(self._marks_after_open), []
        self._model.set_pages([replace(page, marked=row in marks)
                               for row, page in enumerate(pages)])
        self._view.scroll_to_row(self._scroll_after_open or 0)
        self._scroll_after_open = None
        for path in previous - self._sources:
            self._thumbnailer.close(path)
        self._passwords = {path: password for path, password in self._passwords.items()
                           if path in self._sources}
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
        self.setWindowTitle(f"{self._name}[*] - {APP_TITLE}")

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

    def _ask_save_before_close(self) -> str | None:
        """Ask what to do with unsaved changes: "save", "save_as", "discard", or None to stay."""
        target = f"\n{self._document}" if self._document else ""
        box = QMessageBox(QMessageBox.Icon.Warning, APP_NAME,
                          f"저장하지 않은 변경 내용이 있습니다. 저장하고 끝낼까요?{target}",
                          parent=self)
        save = box.addButton("저장(&S)", QMessageBox.ButtonRole.AcceptRole)
        save_as = box.addButton("다른 이름으로 저장(&A)…", QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton("저장 안 함(&N)", QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(save_as)  # Enter never overwrites the original
        box.setEscapeButton(cancel)
        box.exec()
        clicked = box.clickedButton()
        return ("save" if clicked is save else "save_as" if clicked is save_as
                else "discard" if clicked is discard else None)

    # --- saving ----------------------------------------------------------

    def _save(self) -> None:
        if self._document is None:
            self._save_as()
            return
        choice = self._ask_overwrite_or_copy()
        if choice == "overwrite":
            self.save_to(self._document)
        elif choice == "copy":
            self._save_copy()

    def _ask_overwrite_or_copy(self) -> str | None:
        """Ask how to save an opened file: "overwrite", "copy", or None to cancel."""
        box = QMessageBox(QMessageBox.Icon.Question, APP_NAME,
                          f"원본 파일을 덮어쓸까요, 사본으로 저장할까요?\n{self._document}",
                          parent=self)
        overwrite = box.addButton("덮어쓰기(&O)", QMessageBox.ButtonRole.DestructiveRole)
        copy = box.addButton("사본으로 저장(&C)…", QMessageBox.ButtonRole.AcceptRole)
        cancel = box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(copy)  # Enter never overwrites the original
        box.setEscapeButton(cancel)
        box.exec()
        clicked = box.clickedButton()
        return "overwrite" if clicked is overwrite else "copy" if clicked is copy else None

    def _suggested_pdf(self, suffix: str) -> Path:
        if self._document is None:
            return self._merge_folder / f"병합{suffix}.pdf"
        return self._document.with_name(f"{self._document.stem}{suffix}.pdf")

    def _choose_pdf_target(self, title: str, suggested: Path) -> Path | None:
        name, _ = QFileDialog.getSaveFileName(self, title, str(suggested), _PDF_FILTER)
        if not name:
            return None
        path = Path(name)
        return path if path.suffix else path.with_suffix(".pdf")

    def _save_as(self) -> None:
        suggested = self._suggested_pdf("" if self._document is None else "_편집")
        path = self._choose_pdf_target("다른 이름으로 저장", suggested)
        if path:
            self.save_to(path)

    def _save_before_close(self) -> None:
        # The close prompt has already asked, so the original is overwritten without a second question.
        if self._document is None:
            self._save_as()
        else:
            self.save_to(self._document)

    def _save_copy(self) -> None:
        path = self._choose_pdf_target("사본으로 저장", self._suggested_pdf("_사본"))
        if path:
            self.save_to(path, copy=True)

    def _extract(self) -> None:
        rows = self._view.selected_rows()
        if not rows or self._busy():
            return
        path = self._choose_pdf_target(f"선택한 {len(rows)}쪽을 PDF로 추출",
                                       self._suggested_pdf("_추출"))
        if path:
            self.save_to(path, rows=rows)

    def save_to(self, dest: Path, copy: bool = False, rows: list[int] | None = None) -> None:
        """Write the edited document to `dest` in the background, then switch to it.

        With `copy`, the open document stays as it is, unsaved changes included.
        With `rows`, only those pages are written, and always as a copy.
        """
        if self._busy():
            return
        copy = copy or rows is not None
        if copy and dest.resolve() in self._sources:
            # The pages on screen are read from that file; replacing it would scramble them.
            QMessageBox.warning(
                self, APP_NAME,
                f"열려 있는 파일 위에는 저장할 수 없습니다. 다른 이름을 선택하세요.\n{dest}")
            return
        pages = self._model.pages() if rows is None else [self._model.page(row) for row in rows]
        self._save_is_copy = copy
        self._save_extracted = 0 if rows is None else len(pages)
        self._save_dest = dest.resolve()
        # Written next to the target and swapped in at the end, so a failed
        # or cancelled save never damages an existing file.
        temp = self._save_dest.with_name(self._save_dest.name + ".tmp")
        job = self._save_job = SaveJob(pages, temp, self, self._passwords)

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
        self._close_after_save = False
        self._update_state()
        return self._save_dest

    def _on_save_finished(self) -> None:
        if self._save_job is None:  # window closed meanwhile
            return
        closing = self._close_after_save
        dest = self._end_save()
        temp = dest.with_name(dest.name + ".tmp")
        if not self._save_is_copy:
            # Windows cannot replace a file that is open, and the target may be one we are showing.
            self._thumbnailer.close(dest, wait=True)
        try:
            os.replace(temp, dest)
        except OSError as e:
            temp.unlink(missing_ok=True)
            self._show_save_error(str(e))
            return
        self._passwords.pop(dest, None)  # the file just written has no password
        if self._save_extracted:
            self.statusBar().showMessage(f"{self._save_extracted}쪽을 추출했습니다: {dest}", 5000)
            return
        if self._save_is_copy:
            self.statusBar().showMessage(f"사본을 저장했습니다: {dest}", 5000)
            return
        if closing:
            self._undo_stack.setClean()  # saved, so the window closes without asking again
            self.close()
            return
        # Continue from the saved file: its pages are now in the edited order.
        self._scroll_after_open = self._view.top_row()
        self._marks_after_open = self._model.marked_rows()  # same rows: the file is in this order
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

    # --- pages as images -------------------------------------------------

    def _choose_jpg_target(self) -> None:
        rows = self._view.selected_rows()
        if not rows or self._busy():
            return
        folder = self._merge_folder if self._document is None else self._document.parent
        stem = "병합" if self._document is None else self._document.stem
        digits = len(str(self._model.rowCount()))
        names = {row: f"{stem}_{row + 1:0{digits}}.jpg" for row in rows}
        if len(rows) == 1:
            name, _ = QFileDialog.getSaveFileName(
                self, "JPG로 저장", str(folder / names[rows[0]]), _JPG_FILTER)
            if not name:
                return
            path = Path(name)
            targets = {rows[0]: path if path.suffix else path.with_suffix(".jpg")}
        else:
            name = QFileDialog.getExistingDirectory(
                self, f"JPG {len(rows)}개를 저장할 폴더 선택", str(folder))
            if not name:
                return
            targets = {row: Path(name) / names[row] for row in rows}
            existing = [path.name for path in targets.values() if path.exists()]
            if existing:
                listed = "\n".join(existing[:10]) + ("\n…" if len(existing) > 10 else "")
                answer = QMessageBox.question(
                    self, APP_NAME,
                    f"이미 있는 파일 {len(existing)}개를 덮어씁니다. 계속할까요?\n{listed}",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel)
                if answer != QMessageBox.StandardButton.Yes:
                    return
        self.export_jpg(targets)

    def export_jpg(self, targets: dict[int, Path]) -> None:
        """Save each page (by row) to its image file as it is shown, rotation included."""
        if not targets or self._busy():
            return
        paths = list(targets.values())
        self._exporting = _Export(len(paths), paths[0].parent, remaining=len(paths))
        self._update_state()
        self.statusBar().showMessage(f"JPG 저장 중… {len(paths)}쪽")
        for row, path in targets.items():
            page = self._model.page(row)
            self._thumbnailer.export_jpg(page.source, page.index, page.rotation, path)

    def _on_exported(self, path: Path, ok: bool) -> None:
        export = self._exporting
        if export is None:
            return
        if not ok:
            export.failures.append(path)
        export.remaining -= 1
        if export.remaining:
            return
        self._exporting = None
        self._update_state()
        saved = export.total - len(export.failures)
        if saved:
            self.statusBar().showMessage(f"JPG {saved}개를 저장했습니다: {export.folder}", 5000)
        if export.failures:
            details = "\n".join(str(path) for path in export.failures)
            QMessageBox.warning(self, APP_NAME, f"JPG로 저장하지 못했습니다.\n\n{details}")

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
        if self.isWindowModified() and not self._busy():
            choice = self._ask_save_before_close()
            if choice != "discard":
                event.ignore()
                if choice == "save":
                    self._save_before_close()
                elif choice == "save_as":
                    self._save_as()
                # The save runs in the background; the window closes once the file is written.
                self._close_after_save = self._save_job is not None
                return
        elif not self._confirm_discard():
            event.ignore()
            return
        if self._save_job is not None:
            self._save_job.cancel()
            self._save_job.wait()
            self._save_job = None
        self._thumbnailer.stop()
        super().closeEvent(event)
