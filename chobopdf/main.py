import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from chobopdf.ui.main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    arguments = app.arguments()[1:]
    if arguments:
        window.open_files([Path(argument) for argument in arguments])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
