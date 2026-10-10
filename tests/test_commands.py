from pathlib import Path

import pytest
from PySide6.QtGui import QUndoStack

from chobopdf.model.commands import DeletePages, InsertPages, MovePages, RotatePages
from chobopdf.model.document import PageListModel, PageRef

SOURCE = Path("doc.pdf")


@pytest.fixture
def model(app):
    model = PageListModel()
    model.set_document(SOURCE, 6)
    return model


def order(model):
    return [model.page(row).index for row in range(model.rowCount())]


def test_delete_and_undo(model):
    stack = QUndoStack()
    stack.push(DeletePages(model, [4, 0, 1]))
    assert order(model) == [2, 3, 5]
    stack.undo()
    assert order(model) == [0, 1, 2, 3, 4, 5]


@pytest.mark.parametrize("rows, dest, expected", [
    ([0], 3, [1, 2, 0, 3, 4, 5]),        # forward
    ([4], 1, [0, 4, 1, 2, 3, 5]),        # backward
    ([1, 4], 3, [0, 2, 1, 4, 3, 5]),     # scattered rows gather at the drop point
    ([0, 1], 6, [2, 3, 4, 5, 0, 1]),     # to the end
    ([2, 3], 3, [0, 1, 2, 3, 4, 5]),     # dropped inside itself
])
def test_move_and_undo(model, rows, dest, expected):
    placed = []
    model.placed.connect(placed.append)
    stack = QUndoStack()
    stack.push(MovePages(model, rows, dest))
    assert order(model) == expected
    assert [model.page(row).index for row in placed[-1]] == rows
    stack.undo()
    assert order(model) == [0, 1, 2, 3, 4, 5]


def test_move_onto_itself_is_noop(model):
    assert MovePages(model, [2, 3], 2).is_noop()
    assert MovePages(model, [2, 3], 4).is_noop()
    assert not MovePages(model, [2, 4], 3).is_noop()


def test_insert_copy_and_undo(model):
    stack = QUndoStack()
    stack.push(InsertPages(model, 2, [model.page(0), model.page(5)], "붙여넣기"))
    assert order(model) == [0, 1, 0, 5, 2, 3, 4, 5]
    stack.undo()
    assert order(model) == [0, 1, 2, 3, 4, 5]


def test_rotate_wraps_and_undoes(model):
    stack = QUndoStack()
    stack.push(RotatePages(model, [1], -90))
    assert model.page(1) == PageRef(SOURCE, 1, 270)
    stack.push(RotatePages(model, [1], 180))
    assert model.page(1).rotation == 90
    stack.undo()
    stack.undo()
    assert model.page(1).rotation == 0
    assert model.page(0).rotation == 0
