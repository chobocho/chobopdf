from dataclasses import replace

from PySide6.QtGui import QUndoCommand

from chobopdf.model.document import PageListModel, PageRef


def _runs(rows: list[int]) -> list[tuple[int, int]]:
    """Group sorted rows into (first, count) runs of consecutive rows."""
    runs: list[tuple[int, int]] = []
    for row in rows:
        if runs and runs[-1][0] + runs[-1][1] == row:
            runs[-1] = (runs[-1][0], runs[-1][1] + 1)
        else:
            runs.append((row, 1))
    return runs


def _remove_rows(model: PageListModel, rows: list[int]) -> None:
    for first, count in reversed(_runs(rows)):
        model.remove(first, count)


def _restore_rows(model: PageListModel, rows: list[int], pages: list[PageRef]) -> None:
    """Put `pages` back at their original `rows` (sorted ascending)."""
    done = 0
    for first, count in _runs(rows):
        model.insert(first, pages[done:done + count])
        done += count
    model.placed.emit(rows)


class InsertPages(QUndoCommand):
    def __init__(self, model: PageListModel, row: int, pages: list[PageRef], text: str):
        super().__init__(text)
        self._model = model
        self._row = row
        self._pages = pages

    def redo(self) -> None:
        self._model.insert(self._row, self._pages)
        self._model.placed.emit(list(range(self._row, self._row + len(self._pages))))

    def undo(self) -> None:
        self._model.remove(self._row, len(self._pages))


class DeletePages(QUndoCommand):
    def __init__(self, model: PageListModel, rows: list[int], text: str = "삭제"):
        super().__init__(text)
        self._model = model
        self._rows = sorted(rows)
        self._pages = [model.page(row) for row in self._rows]

    def redo(self) -> None:
        _remove_rows(self._model, self._rows)

    def undo(self) -> None:
        _restore_rows(self._model, self._rows, self._pages)


class MovePages(QUndoCommand):
    """Move `rows` so they sit together in front of the page currently at `dest`."""

    def __init__(self, model: PageListModel, rows: list[int], dest: int):
        super().__init__("이동")
        self._model = model
        self._rows = sorted(rows)
        self._pages = [model.page(row) for row in self._rows]
        self._dest = dest - sum(1 for row in self._rows if row < dest)

    def is_noop(self) -> bool:
        return self._rows == list(range(self._dest, self._dest + len(self._rows)))

    def redo(self) -> None:
        _remove_rows(self._model, self._rows)
        self._model.insert(self._dest, self._pages)
        self._model.placed.emit(list(range(self._dest, self._dest + len(self._pages))))

    def undo(self) -> None:
        self._model.remove(self._dest, len(self._pages))
        _restore_rows(self._model, self._rows, self._pages)


class RotatePages(QUndoCommand):
    def __init__(self, model: PageListModel, rows: list[int], degrees: int):
        super().__init__("회전")
        self._model = model
        self._rows = rows
        self._degrees = degrees

    def redo(self) -> None:
        self._rotate(self._degrees)

    def undo(self) -> None:
        self._rotate(-self._degrees)

    def _rotate(self, degrees: int) -> None:
        for row in self._rows:
            page = self._model.page(row)
            self._model.replace(row, replace(page, rotation=(page.rotation + degrees) % 360))
