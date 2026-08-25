"""画程序图标，输出 src/subtitle_tool/assets/icon.ico（多尺寸）。

图标要在 16×16 下还认得出来：一块屏幕、底部一条压暗的字幕条、条上两行长短不一的白杠。
字幕条是关键——没有它就只是个普通播放器图标。播放三角只在大尺寸下画，小尺寸上
再加东西就糊成一团。

ICO 用的是 Vista 之后支持的「内嵌 PNG」写法：一个目录头 + 每个尺寸一段 PNG。
Qt 不一定带 ico 的写插件，所以容器自己拼，只借它写 PNG。
"""

import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6.QtCore import QBuffer, QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
)
from PySide6.QtWidgets import QApplication

SIZES = (16, 24, 32, 48, 64, 128, 256)
OUTPUT = os.path.join(os.path.dirname(__file__), "..", "src", "subtitle_tool", "assets")


def draw(size: int) -> QImage:
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    unit = size / 100.0
    small = size < 32

    # 屏幕：整块圆角矩形，深蓝到亮蓝的渐变
    screen = QRectF(7 * unit, 12 * unit, 86 * unit, 76 * unit)
    radius = 16 * unit
    gradient = QLinearGradient(screen.topLeft(), screen.bottomRight())
    gradient.setColorAt(0.0, QColor("#4b82e8"))
    gradient.setColorAt(1.0, QColor("#2649a8"))
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(gradient))
    painter.drawRoundedRect(screen, radius, radius)

    # 底部压一条深色字幕条：有了这条，图标才不像个普通播放器
    band = QRectF(screen.left(), screen.top() + 48 * unit, screen.width(), 28 * unit)
    painter.save()
    clip = QPainterPath()
    clip.addRoundedRect(screen, radius, radius)
    painter.setClipPath(clip)
    painter.setBrush(QColor(0, 0, 0, 62))
    painter.drawRect(band)
    painter.restore()

    # 播放三角，放在字幕条上方；小尺寸挤不下就省掉
    if not small:
        painter.setBrush(QColor(255, 255, 255, 235))
        painter.drawPolygon(
            [
                QPointF(41 * unit, 22 * unit),
                QPointF(62 * unit, 34 * unit),
                QPointF(41 * unit, 46 * unit),
            ]
        )

    # 两行字幕：长短不一才像字幕，也是整个图标的辨识点
    painter.setBrush(QColor("#ffffff"))
    height = (9 if small else 7) * unit
    top = (58 if small else 55) * unit
    painter.drawRoundedRect(QRectF(17 * unit, top, 66 * unit, height), height / 2, height / 2)
    painter.setBrush(QColor(255, 255, 255, 170))
    painter.drawRoundedRect(
        QRectF(17 * unit, top + height + 5 * unit, 42 * unit, height), height / 2, height / 2
    )
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
