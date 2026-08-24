"""画程序图标，输出 src/subtitle_tool/assets/icon.ico（多尺寸）。

图标要在 16×16 下还认得出来，所以只用两个元素：一块屏幕，加两行字幕。
播放三角只在大尺寸下画——小尺寸上再加东西就糊成一团了。

ICO 用的是 Vista 之后支持的「内嵌 PNG」写法：一个目录头 + 每个尺寸一段 PNG。
Qt 不一定带 ico 的写插件，所以容器自己拼，只借它写 PNG。
"""

import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6.QtCore import QBuffer, QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QLinearGradient, QPainter
from PySide6.QtWidgets import QApplication

SIZES = (16, 24, 32, 48, 64, 128, 256)
OUTPUT = os.path.join(os.path.dirname(__file__), "..", "src", "subtitle_tool", "assets")


def draw(size: int) -> QImage:
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    unit = size / 100.0

    # 屏幕：留一点边，圆角，深蓝到亮蓝的渐变
    screen = QRectF(6 * unit, 14 * unit, 88 * unit, 72 * unit)
    gradient = QLinearGradient(screen.topLeft(), screen.bottomRight())
    gradient.setColorAt(0.0, QColor("#3b6fd4"))
    gradient.setColorAt(1.0, QColor("#2547a0"))
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(gradient))
    painter.drawRoundedRect(screen, 14 * unit, 14 * unit)

    # 播放三角：小尺寸下省掉，挤在一起反而看不清
    if size >= 32:
        painter.setBrush(QColor(255, 255, 255, 70))
        painter.drawPolygon(
            [
                QPointF(42 * unit, 28 * unit),
                QPointF(64 * unit, 41 * unit),
                QPointF(42 * unit, 54 * unit),
            ]
        )

    # 两行字幕：长短不一才像字幕，也是整个图标的辨识点
    painter.setBrush(QColor("#ffffff"))
    bar = 8 * unit
    painter.drawRoundedRect(QRectF(18 * unit, 62 * unit, 64 * unit, bar), bar / 2, bar / 2)
    painter.setBrush(QColor(255, 255, 255, 190))
    painter.drawRoundedRect(QRectF(30 * unit, 74 * unit, 40 * unit, bar), bar / 2, bar / 2)
    painter.end()
    return image


def png_bytes(image: QImage) -> bytes:
    storage = QByteArray()  # 得留着引用，传临时对象进 QBuffer 会段错误
    buffer = QBuffer(storage)
    buffer.open(QBuffer.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(storage)


def main() -> int:
    app = QApplication(sys.argv)  # 必须留着引用，被回收了后面画图就段错误
    frames = [(size, png_bytes(draw(size))) for size in SIZES]

    header = struct.pack("<HHH", 0, 1, len(frames))
    offset = len(header) + 16 * len(frames)
    entries, blobs = b"", b""
    for size, data in frames:
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)

    os.makedirs(OUTPUT, exist_ok=True)
    icon = os.path.join(OUTPUT, "icon.ico")
    with open(icon, "wb") as handle:
        handle.write(header + entries + blobs)
    draw(256).save(os.path.join(OUTPUT, "..", "..", "..", "docs", "icon.png"), "PNG")
    print(f"{icon}  {len(header + entries + blobs)} 字节，{len(frames)} 个尺寸")
    del app
    return 0


if __name__ == "__main__":
    sys.exit(main())
