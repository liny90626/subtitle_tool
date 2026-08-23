"""桌面界面。拖入视频 → 选音轨与目标语言 → 生成字幕。"""

import os
import sys
import threading
import traceback

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .asr import MODEL_SIZES, Cancelled, default_model, pick_device
from .audio import probe_tracks
from .languages import FLORES_NAMES, describe_whisper, target_choices
from .pipeline import Engine, Options
from .subtitles import FORMATS
from .translate import DEFAULT_MODEL as DEFAULT_TRANSLATE_MODEL
from .translate import MODEL_REPOS

MEDIA_FILTER = (
    "视频/音频 (*.mp4 *.mkv *.mov *.avi *.flv *.wmv *.webm *.ts *.m4v"
    " *.mp3 *.wav *.flac *.m4a *.aac *.ogg *.opus);;全部文件 (*)"
)
LAYOUT_CHOICES = (
    ("只要译文", "target"),
    ("双语对照", "bilingual"),
    ("只要原文", "source"),
)


class Worker(QThread):
    """在后台线程里跑流水线，避免界面卡死。"""

    progress = Signal(int, str, float)
    finished_file = Signal(int, object, object)  # 行号, Result, 异常
    all_done = Signal(object)  # 把加载好的 Engine 交还主线程复用

    def __init__(self, jobs, engine, engine_factory):
        super().__init__()
        self.jobs = jobs  # [(行号, 文件路径, Options), ...]
        self.engine = engine
        self.engine_factory = engine_factory
        self.cancel = threading.Event()

    def run(self):
        if self.engine is None:
            self.engine = self.engine_factory()
        for row, path, options in self.jobs:
            if self.cancel.is_set():
                break
            try:
                result = self.engine.run(
                    path,
                    options,
                    progress=lambda stage, fraction, row=row: self.progress.emit(
                        row, stage, fraction
                    ),
                    cancel=self.cancel,
                )
                self.finished_file.emit(row, result, None)
            except Cancelled:
                break
            except Exception as error:
                # 一个文件失败不该中断整批；异常原样交给界面显示并打印堆栈，不吞
                self.finished_file.emit(row, None, error)
        self.all_done.emit(self.engine)


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("字幕生成工具")
        self.resize(940, 680)
        self.setAcceptDrops(True)
        self.worker = None
        self.engine = None
        self.engine_key = None
        self._build()

    # ---------- 界面 ----------

    def _build(self):
        layout = QVBoxLayout(self)
        layout.addWidget(self._build_files())
        layout.addWidget(self._build_settings())
        layout.addLayout(self._build_actions())
        layout.addWidget(self.log, 1)

    def _build_files(self):
        box = QGroupBox("① 选择视频（可直接把文件拖进来）")
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["文件", "音轨", "状态"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)

        remove = QAction("移除选中", self.table)
        remove.setShortcut(Qt.Key_Delete)
        remove.triggered.connect(self._remove_selected)
        self.table.addAction(remove)
        self.table.setContextMenuPolicy(Qt.ActionsContextMenu)

        add = QPushButton("添加文件…")
        add.clicked.connect(self._pick_files)
        clear = QPushButton("清空")
        clear.clicked.connect(lambda: self.table.setRowCount(0))

        buttons = QHBoxLayout()
        buttons.addWidget(add)
        buttons.addWidget(clear)
        buttons.addStretch(1)
        buttons.addWidget(QLabel("选中后按 Delete 可移除"))

        inner = QVBoxLayout(box)
        inner.addWidget(self.table)
        inner.addLayout(buttons)
        return box

    def _build_settings(self):
        box = QGroupBox("② 识别与翻译设置")
        form = QFormLayout(box)

        self.model = QComboBox()
        self.model.addItems(MODEL_SIZES)
        self.model.setCurrentText(default_model())
        self.device = QComboBox()
        self.device.addItems(["自动", "CPU", "GPU (CUDA)"])
        detected = "检测到 NVIDIA 显卡" if pick_device()[0] == "cuda" else "未检测到显卡，用 CPU"
        engine_row = QHBoxLayout()
        engine_row.addWidget(self.model, 1)
        engine_row.addWidget(QLabel("设备"))
        engine_row.addWidget(self.device, 1)
        engine_row.addWidget(QLabel(f"（{detected}）"))
        form.addRow("识别模型", engine_row)

        self.multi_language = QCheckBox("音轨里多种语言混说，逐段识别（会慢一些）")
        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("自动识别"))
        source_row.addSpacing(12)
        source_row.addWidget(self.multi_language)
        source_row.addStretch(1)
        form.addRow("源语言", source_row)

        self.target = QComboBox()
        self.target.setEditable(True)
        self.target.addItem("不翻译（只输出原文）", None)
        for flores, name in target_choices():
            self.target.addItem(f"{name}  [{flores}]", flores)
        self.target.setCurrentIndex(self.target.findData("zho_Hans"))
        self.target.currentIndexChanged.connect(self._sync_layout_enabled)

        self.layout_mode = QComboBox()
        for label, value in LAYOUT_CHOICES:
            self.layout_mode.addItem(label, value)
        target_row = QHBoxLayout()
        target_row.addWidget(self.target, 1)
        target_row.addWidget(QLabel("排版"))
        target_row.addWidget(self.layout_mode)
        form.addRow("字幕语言", target_row)

        self.translate_model = QComboBox()
        self.translate_model.addItems(MODEL_REPOS)
        self.translate_model.setCurrentText(DEFAULT_TRANSLATE_MODEL)
        form.addRow("翻译模型", self.translate_model)

        self.formats = {}
        format_row = QHBoxLayout()
        for fmt in FORMATS:
            check = QCheckBox(fmt.upper())
            check.setChecked(fmt == "srt")
            self.formats[fmt] = check
            format_row.addWidget(check)
        format_row.addStretch(1)
        form.addRow("输出格式", format_row)

        self.output_dir = QLineEdit()
        self.output_dir.setPlaceholderText("留空则与视频同目录")
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._pick_output_dir)
        output_row = QHBoxLayout()
        output_row.addWidget(self.output_dir, 1)
        output_row.addWidget(browse)
        form.addRow("输出目录", output_row)
        return box

    def _build_actions(self):
        self.start = QPushButton("开始生成")
        self.start.setMinimumHeight(36)
        self.start.clicked.connect(self._start)
        self.stop = QPushButton("取消")
        self.stop.setMinimumHeight(36)
        self.stop.setEnabled(False)
        self.stop.clicked.connect(self._stop)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setFormat("就绪")
        self.log = QTextEdit()
        self.log.setReadOnly(True)

        row = QHBoxLayout()
        row.addWidget(self.bar, 1)
        row.addWidget(self.start)
        row.addWidget(self.stop)
        return row

    # ---------- 文件管理 ----------

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self._add_files([url.toLocalFile() for url in event.mimeData().urls()])

    def _pick_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "选择视频", "", MEDIA_FILTER)
        self._add_files(paths)

    def _pick_output_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if path:
            self.output_dir.setText(path)

    def _add_files(self, paths):
        existing = {self.table.item(r, 0).data(Qt.UserRole) for r in range(self.table.rowCount())}
        for path in paths:
            if not os.path.isfile(path) or path in existing:
                continue
            try:
                tracks = probe_tracks(path)
            except Exception as error:
                # 拖进来的可能是任意文件，读不动就跳过并明确告知，不影响其他文件
                self._log(f"⚠ 无法读取 {os.path.basename(path)}：{error}")
                continue
            if not tracks:
                self._log(f"⚠ {os.path.basename(path)} 没有音轨，已跳过")
                continue
            self._add_row(path, tracks)

    def _add_row(self, path, tracks):
        row = self.table.rowCount()
        self.table.insertRow(row)
        name = QTableWidgetItem(os.path.basename(path))
        name.setToolTip(path)
        name.setData(Qt.UserRole, path)
        self.table.setItem(row, 0, name)

        picker = QComboBox()
        for track in tracks:
            picker.addItem(track.label, track.index)
        self.table.setCellWidget(row, 1, picker)
        self.table.setItem(row, 2, QTableWidgetItem("等待中"))

    def _remove_selected(self):
        for index in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(index)

    # ---------- 执行 ----------

    def _sync_layout_enabled(self):
        self.layout_mode.setEnabled(self.target.currentData() is not None)

    def _start(self):
        if self.table.rowCount() == 0:
            QMessageBox.information(self, "还没有文件", "请先添加或拖入要生成字幕的视频。")
            return
        formats = tuple(f for f, box in self.formats.items() if box.isChecked())
        if not formats:
            QMessageBox.information(self, "没有输出格式", "请至少勾选一种字幕格式。")
            return

        target = self.target.currentData()
        jobs = []
        for row in range(self.table.rowCount()):
            options = Options(
                track_index=self.table.cellWidget(row, 1).currentData(),
                multi_language=self.multi_language.isChecked(),
                target_language=target,
                layout=self.layout_mode.currentData() if target else "source",
                formats=formats,
                output_dir=self.output_dir.text().strip() or None,
            )
            jobs.append((row, self.table.item(row, 0).data(Qt.UserRole), options))
            self.table.item(row, 2).setText("等待中")

        key = (self.model.currentText(), self._device(), self.translate_model.currentText())
        if key != self.engine_key:
            self.engine, self.engine_key = None, key
            self._log(f"载入模型 {key[0]}（首次使用需要下载，请耐心等待）…")

        self.worker = Worker(jobs, self.engine, lambda: Engine(key[0], key[1], key[2]))
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_file.connect(self._on_file_done)
        self.worker.all_done.connect(self._on_all_done)
        self._set_running(True)
        self.worker.start()

    def _device(self):
        return {"自动": "auto", "CPU": "cpu", "GPU (CUDA)": "cuda"}[self.device.currentText()]

    def _stop(self):
        if self.worker:
            self.worker.cancel.set()
            self.stop.setEnabled(False)
            self.bar.setFormat("正在取消…")

    def _set_running(self, running):
        self.start.setEnabled(not running)
        self.stop.setEnabled(running)
        for widget in (
            self.model,
            self.device,
            self.target,
            self.layout_mode,
            self.translate_model,
            self.multi_language,
            self.output_dir,
        ):
            widget.setEnabled(not running)

    def _on_progress(self, row, stage, fraction):
        name = self.table.item(row, 0).text()
        self.table.item(row, 2).setText(f"{stage} {fraction * 100:.0f}%")
        self.bar.setValue(int(fraction * 100))
        self.bar.setFormat(f"{name} — {stage} %p%")

    def _on_file_done(self, row, result, error):
        name = self.table.item(row, 0).text()
        if error is not None:
            self.table.item(row, 2).setText("失败")
            self._log(f"✗ {name}：{error}")
            traceback.print_exception(type(error), error, error.__traceback__)
            return
        self.table.item(row, 2).setText("完成")
        languages = {span[2] for span in result.language_spans}
        detected = "、".join(describe_whisper(code) for code in sorted(languages))
        target = self.target.currentData()
        arrow = f" → {FLORES_NAMES[target]}" if target else ""
        self._log(f"✓ {name}：{detected}{arrow}，{len(result.cues)} 条字幕")
        for path in result.outputs:
            self._log(f"    {path}")

    def _on_all_done(self, engine):
        self.engine = engine
        self._set_running(False)
        self._sync_layout_enabled()
        self.bar.setValue(0)
        self.bar.setFormat("就绪")

    def _log(self, message):
        self.log.append(message)

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.cancel.set()
            self.worker.wait(5000)
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
