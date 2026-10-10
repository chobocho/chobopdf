from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout

from chobopdf import __version__

_SECTIONS = [
    ("파일", [
        ("Ctrl+O", "PDF 열기 (여러 개를 선택하면 병합)"),
        ("Ctrl+M", "여러 파일 병합"),
        ("Ctrl+I", "열린 문서에 PDF 추가 (선택한 페이지 뒤, 없으면 맨 끝)"),
        ("Ctrl+S", "저장 (덮어쓸지 사본으로 저장할지 물어봄)"),
        ("Ctrl+Shift+S", "다른 이름으로 저장"),
        ("Ctrl+Alt+S", "사본으로 저장 (열린 문서는 그대로 유지)"),
        ("Ctrl+J", "선택한 페이지를 JPG로 저장 (우클릭 메뉴에도 있음)"),
        ("Ctrl+Q", "끝내기"),
    ]),
    ("페이지 편집", [
        ("드래그", "선택한 페이지를 놓은 위치로 이동"),
        ("Ctrl+Z / Ctrl+Y", "실행 취소 / 다시 실행"),
        ("Ctrl+X / Ctrl+C / Ctrl+V", "잘라내기 / 복사 / 붙여넣기"),
        ("Ctrl+D", "복제"),
        ("Del", "삭제"),
        ("R / Shift+R", "오른쪽 / 왼쪽으로 회전"),
        ("Ctrl+A", "모두 선택"),
        ("Ctrl+휠", "썸네일 크기 (100~200%)"),
    ]),
    ("미리보기", [
        ("더블 클릭", "미리보기 열기"),
        ("Esc", "미리보기 닫기"),
        ("Ctrl++ / Ctrl+-", "확대 / 축소 (Ctrl+휠도 가능)"),
        ("Ctrl+0", "폭 맞춤"),
        ("Ctrl+9", "쪽 맞춤 (페이지 전체가 한 화면에)"),
        ("Page Down / Page Up", "다음 / 이전 페이지"),
    ]),
    ("도움말", [
        ("F1", "이 도움말"),
    ]),
]

_NOTES = [
    "PDF 파일을 창에 끌어다 놓으면 열리고, 썸네일 사이에 놓으면 그 위치에 추가됩니다.",
    "미리보기의 확대/축소와 페이지 이동 키는 미리보기를 한 번 클릭한 뒤에 동작합니다.",
    "저장한 파일에는 책갈피(목차)와 양식 필드가 유지되지 않습니다.",
]

_KEY_COLUMN_WIDTH = 190  # the same in every table, so the descriptions line up


def help_html() -> str:
    parts = [f"<h2>ChoboPDF {__version__}</h2>",
             "<p>대용량 PDF의 페이지를 썸네일로 보면서 옮기고, 돌리고, 지우고, 합칩니다.</p>"]
    for title, rows in _SECTIONS:
        parts.append(f"<h3>{title}</h3><table cellspacing='0' cellpadding='3'>")
        parts += [f"<tr><td width='{_KEY_COLUMN_WIDTH}'><b>{keys}</b></td><td>{text}</td></tr>"
                  for keys, text in rows]
        parts.append("</table>")
    parts.append("<h3>참고</h3><ul>")
    parts += [f"<li>{note}</li>" for note in _NOTES]
    parts.append("</ul>")
    return "".join(parts)


class HelpDialog(QDialog):
    """Shortcut reference and version. Not modal, so it can stay open while working."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ChoboPDF 도움말")
        self.resize(520, 640)
        self.browser = QTextBrowser()
        self.browser.setHtml(help_html())
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("닫기")
        buttons.rejected.connect(self.close)
        layout = QVBoxLayout(self)
        layout.addWidget(self.browser)
        layout.addWidget(buttons)
        QShortcut(QKeySequence(Qt.Key.Key_F1), self, self.close)  # F1 again closes it
