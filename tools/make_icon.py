"""Draws the application icon and writes chobopdf/resources/icon.png and icon.ico.

Run from the repository root:  .venv\\Scripts\\python tools\\make_icon.py
"""
import struct
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QImage, QLinearGradient, QPainter,
                           QPainterPath, QPolygonF)

OUT_DIR = Path(__file__).resolve().parent.parent / "chobopdf" / "resources"
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]

PAGE = QRectF(88, 44, 118, 160)
FOLD = 34  # size of the folded corner
RED = QColor("#C4203A")


def page_path(rect: QRectF, radius: float, fold: float) -> QPainterPath:
    """A sheet of paper with rounded corners and the top-right corner cut for the fold."""
    path = QPainterPath()
    path.moveTo(rect.left() + radius, rect.top())
    path.lineTo(rect.right() - fold, rect.top())
    path.lineTo(rect.right(), rect.top() + fold)
    path.lineTo(rect.right(), rect.bottom() - radius)
    path.quadTo(rect.right(), rect.bottom(), rect.right() - radius, rect.bottom())
    path.lineTo(rect.left() + radius, rect.bottom())
    path.quadTo(rect.left(), rect.bottom(), rect.left(), rect.bottom() - radius)
    path.lineTo(rect.left(), rect.top() + radius)
    path.quadTo(rect.left(), rect.top(), rect.left() + radius, rect.top())
    return path


def draw(size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
    p.scale(size / 256, size / 256)  # everything below is drawn on a 256x256 canvas
    p.setPen(Qt.PenStyle.NoPen)
    small = size < 48  # fine detail turns to mush, so leave it out

    background = QLinearGradient(0, 0, 256, 256)
    background.setColorAt(0, QColor("#FF7A52"))
    background.setColorAt(1, QColor("#D81F45"))
    p.setBrush(background)
    p.drawRoundedRect(QRectF(8, 8, 240, 240), 56, 56)

    # The page behind, tilted: "several pages" is what the app is about.
    p.save()
    p.translate(PAGE.center())
    p.rotate(-13)
    p.translate(-PAGE.center() - QPointF(22, -4))
    p.setBrush(QColor(255, 255, 255, 120))
    p.drawPath(page_path(PAGE, 10, FOLD))
    p.restore()

    # Front page with a soft shadow.
    p.setBrush(QColor(90, 0, 20, 50))
    p.drawPath(page_path(PAGE.translated(4, 7), 10, FOLD))
    p.setBrush(QColor("#FFFFFF"))
    p.drawPath(page_path(PAGE, 10, FOLD))
    p.setBrush(QColor("#F3C9CF"))
    p.drawPolygon(QPolygonF([
        QPointF(PAGE.right() - FOLD, PAGE.top()),
        QPointF(PAGE.right(), PAGE.top() + FOLD),
        QPointF(PAGE.right() - FOLD, PAGE.top() + FOLD),
    ]))

    if not small:
        p.setBrush(QColor("#D9DEE6"))
        for y, width in ((96, 60), (116, 82), (136, 70)):
            p.drawRoundedRect(QRectF(PAGE.left() + 18, y, width, 9), 4.5, 4.5)

    # The label overlaps the page's left edge, like a tab.
    label = QRectF(48, 156, 124, 46) if not small else QRectF(48, 150, 124, 52)
    p.setBrush(QColor(90, 0, 20, 60))
    p.drawRoundedRect(label.translated(3, 5), 12, 12)
    p.setBrush(RED)
    p.drawRoundedRect(label, 12, 12)
    if not small:
        font = QFont("Segoe UI", 1, QFont.Weight.Black)
        font.setPixelSize(34)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
        p.setFont(font)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(label.adjusted(2, -2, 0, 0), Qt.AlignmentFlag.AlignCenter, "PDF")
    p.end()
    return image


def png_bytes(image: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data.data())


def write_ico(path: Path, images: list[QImage]) -> None:
    """ICO container with one PNG-compressed entry per size."""
    blobs = [png_bytes(image) for image in images]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries = b""
    for image, blob in zip(images, blobs):
        edge = image.width() % 256  # 256 is stored as 0
        entries += struct.pack("<BBBBHHII", edge, edge, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    path.write_bytes(header + entries + b"".join(blobs))


def main() -> None:
    app = QGuiApplication([])  # needed for fonts
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    draw(256).save(str(OUT_DIR / "icon.png"))
    write_ico(OUT_DIR / "icon.ico", [draw(size) for size in ICO_SIZES])
    print(f"wrote {OUT_DIR / 'icon.png'} and icon.ico")


if __name__ == "__main__":
    main()
