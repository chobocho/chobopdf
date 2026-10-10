import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from chobopdf.ui.main_window import MainWindow

ICON_PATH = Path(__file__).resolve().parent / "resources" / "icon.png"


def main() -> None:
    if sys.platform == "win32":
        # Without its own ID the taskbar shows the Python icon when run from source.
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("chobocho.chobopdf")
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(ICON_PATH)))
    window = MainWindow()
    window.show()
    arguments = app.arguments()[1:]
    if arguments:
        window.open_files([Path(argument) for argument in arguments])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
