import tomllib
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

import chobopdf
from chobopdf.ui.main_window import MainWindow


def test_f1_opens_the_help_with_the_version_and_shortcuts(app):
    window = MainWindow()
    window.show()
    QTest.qWaitForWindowExposed(window)
    QTest.keyClick(window, Qt.Key.Key_F1)
    app.processEvents()

    dialog = window._help
    assert dialog is not None and dialog.isVisible()
    text = dialog.browser.toPlainText()
    assert f"ChoboPDF {chobopdf.__version__}" in text
    for keys in ("Ctrl+O", "Ctrl+9", "Page Down", "F1"):
        assert keys in text

    QTest.keyClick(dialog, Qt.Key.Key_F1)                      # F1 again closes it
    assert not dialog.isVisible()
    window.close()


def test_version_is_0_1_0_and_comes_from_the_package():
    assert chobopdf.__version__ == "0.1.0"
    pyproject = tomllib.loads(
        (Path(chobopdf.__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["dynamic"] == ["version"]
    assert pyproject["tool"]["setuptools"]["dynamic"]["version"] == {"attr": "chobopdf.__version__"}
