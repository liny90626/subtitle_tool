"""重新生成 README 里的界面截图（中英各一张）。

界面一改截图就过期，所以留成脚本而不是手工截：

    QT_QPA_PLATFORM=offscreen python scripts/make_screenshot.py

文件列表和音轨描述用的是 tests/data 里的真素材，不编造。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6.QtWidgets import QApplication

from subtitle_tool import gui, i18n
from subtitle_tool.audio import probe_tracks
from subtitle_tool.i18n import t
from subtitle_tool.pipeline import Result

ROOT = os.path.join(os.path.dirname(__file__), "..")
DATA = os.path.join(ROOT, "tests", "data")
SIZE = (1020, 827)


def compose(language: str, path: str):
    i18n.use(language)
    window = gui.MainWindow()
    window.resize(*SIZE)
    window._retranslate()

    for name in ("multitrack.mkv", "jfk.flac"):
        window._add_row(os.path.join(DATA, name), probe_tracks(os.path.join(DATA, name)))
    window.table.cellWidget(0, 1).setCurrentIndex(1)  # 多音轨片源选第 2 条
    window._set_status(0, "{stage} {percent:.0f}%", stage=t("语音转写"), percent=62)

    # 显示的界面语言要和这张图本身的语言一致；signal 一响就会去写 settings.json，挡掉
    window.ui_language.blockSignals(True)
    window.ui_language.setCurrentIndex(window.ui_language.findData(language))
    window.ui_language.blockSignals(False)

    window.source_language.setCurrentIndex(window.source_language.findData("ja"))
    window.target.setCurrentIndex(window.target.findData("zho_Hans"))
    window.layout_mode.setCurrentIndex(window.layout_mode.findData("bilingual"))
    window.formats["vtt"].setChecked(True)

    window.bar.setValue(62)
    window.bar.setFormat(f"multitrack.mkv — {t('语音转写')} %p%")
    tracks = probe_tracks(os.path.join(DATA, "jfk.flac"))
    window._on_file_done(
        1,
        Result(
            "jfk.flac",
            tracks[0],
            "ja",
            [(0.0, 11.0, "ja")],
            [None] * 3,
            ["jfk.ja-zh.srt"],
            ["jfk.en-zh.srt"],
        ),
        None,
    )

    window.show()
    QApplication.processEvents()
    window.grab().save(path)
    print(f"{path} 已更新")


def main():
    app = QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(gui.STYLE)
    compose("zh", os.path.join(ROOT, "docs", "screenshot.png"))
    compose("en", os.path.join(ROOT, "docs", "screenshot.en.png"))


if __name__ == "__main__":
    main()
