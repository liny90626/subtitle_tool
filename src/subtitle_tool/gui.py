"""桌面界面。拖入视频 → 选音轨与目标语言 → 生成字幕。

界面语言可以随时切换：每处文案在创建时都用 ``_text`` / ``_live`` 登记一次，切语言
时把登记过的重新渲染一遍，不用重开窗口，文件列表和已选设置都留着。
"""

import os
import sys
import threading
import traceback

from PySide6.QtCore import Qt, QThread, QTimer, Signal
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

from . import hub, i18n, runtime, settings
from .asr import MODEL_SIZES, default_model, pick_device
from .audio import probe_tracks
from .errors import Cancelled, DownloadError
from .i18n import t
from .languages import describe_whisper, flores_name, target_choices
from .pipeline import Engine, Options
from .subtitles import FORMATS
from .translate import DEFAULT_MODEL as DEFAULT_TRANSLATE_MODEL
from .translate import MODEL_REPOS

#: 文件选择框认的后缀
MEDIA_SUFFIXES = (
    "*.mp4 *.mkv *.mov *.avi *.flv *.wmv *.webm *.ts *.m4v"
    " *.mp3 *.wav *.flac *.m4a *.aac *.ogg *.opus"
)
LAYOUT_CHOICES = (
    ("只要译文", "target"),
    ("双语对照", "bilingual"),
    ("只要原文", "source"),
)
DEVICE_CHOICES = (("自动", "auto"), ("CPU", "cpu"), ("GPU (CUDA)", "cuda"))
SOURCE_CHOICES = (
    ("自动选源", settings.AUTO),
    ("官方 huggingface.co", hub.OFFICIAL),
    ("镜像 hf-mirror.com", hub.MIRROR),
)


class Worker(QThread):
    """在后台线程里跑流水线，避免界面卡死。"""

    progress = Signal(int, str, float)
    finished_file = Signal(int, object, object)  # 行号, Result, 异常
    note = Signal(str, object)  # (提示, 进度)；进度为 None 表示只是一条消息
    load_failed = Signal(object)
    all_done = Signal(object)  # 把加载好的 Engine 交还主线程复用

    def __init__(self, jobs, engine, engine_factory):
        super().__init__()
        self.jobs = jobs  # [(行号, 文件路径, Options), ...]
        self.engine = engine
        self.engine_factory = engine_factory  # 收一个提示回调，返回加载好的 Engine
        self.cancel = threading.Event()

    def run(self):
        try:
            if self.engine is None:
                # 在这个线程里加载，下载/初始化模型都不卡界面
                self.engine = self.engine_factory(self.note.emit)
        except Exception as error:
            # 模型下载/加载失败（断网、磁盘不够）。不报出来的话线程直接死掉，
            # all_done 永远不发，界面会一直卡在「运行中」，开始按钮再也点不动
            self.load_failed.emit(error)
            self.all_done.emit(None)
            return
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
            except DownloadError as error:
                # 模型下不下来跟具体文件无关，后面的文件只会一模一样再失败一遍
                self.load_failed.emit(error)
                break
            except Exception as error:
                # 一个文件失败不该中断整批；异常原样交给界面显示并记下堆栈，不吞
                self.finished_file.emit(row, None, error)
        self.all_done.emit(self.engine)


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.resize(940, 680)
        self.setAcceptDrops(True)
        self.worker = None
        self.engine = None
        self.engine_key = None
        self._texts = []  # 切语言时要重新渲染的文案
        self._build()

    # ---------- 文案跟着语言走 ----------

    def _live(self, render):
        """登记一处会跟着界面语言变的文案，并立刻渲染一次。"""
        self._texts.append(render)
        render()

    def _text(self, setter, source):
        """``setter`` 是 setText/setTitle 之类，``source`` 是中文原文。"""
        self._live(lambda: setter(t(source)))

    def _choices(self, combo, options, initial=None):
        """下拉框的选项跟着语言重建，选中项保持不变。"""

        def rebuild():
            selected = combo.currentData() if combo.count() else initial
            combo.blockSignals(True)
            combo.clear()
            for label, value in options():
                combo.addItem(label, value)
            index = combo.findData(selected)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)

        self._live(rebuild)

    def _retranslate(self):
        for render in self._texts:
            render()

    # ---------- 界面 ----------

    def _build(self):
        self._text(self.setWindowTitle, "字幕生成工具")
        layout = QVBoxLayout(self)
        layout.addWidget(self._build_files())
        layout.addWidget(self._build_settings())
        layout.addLayout(self._build_actions())
        layout.addWidget(self.log, 1)

    def _build_files(self):
        box = QGroupBox()
        self._text(box.setTitle, "① 选择视频（可直接把文件拖进来）")
        self.table = QTableWidget(0, 3)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._live(lambda: self.table.setHorizontalHeaderLabels([t("文件"), t("音轨"), t("状态")]))
        self._live(self._retranslate_statuses)
        self._live(self._retranslate_tracks)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)

        remove = QAction(self.table)
        self._text(remove.setText, "移除选中")
        remove.setShortcut(Qt.Key_Delete)
        remove.triggered.connect(self._remove_selected)
        self.table.addAction(remove)
        self.table.setContextMenuPolicy(Qt.ActionsContextMenu)

        add = QPushButton()
        self._text(add.setText, "添加文件…")
        add.clicked.connect(self._pick_files)
        clear = QPushButton()
        self._text(clear.setText, "清空")
        clear.clicked.connect(lambda: self.table.setRowCount(0))
        hint = QLabel()
        self._text(hint.setText, "选中后按 Delete 可移除")

        buttons = QHBoxLayout()
        buttons.addWidget(add)
        buttons.addWidget(clear)
        buttons.addStretch(1)
        buttons.addWidget(hint)

        inner = QVBoxLayout(box)
        inner.addWidget(self.table)
        inner.addLayout(buttons)
        return box

    def _build_settings(self):
        box = QGroupBox()
        self._text(box.setTitle, "② 识别与翻译设置")
        form = QFormLayout(box)
        saved = settings.load()

        self.model = QComboBox()
        self.model.addItems(MODEL_SIZES)
        self.device = QComboBox()
        self._choices(self.device, lambda: [(t(label), value) for label, value in DEVICE_CHOICES])
        # 探显卡要把 CTranslate2 整个加载进来，几百毫秒起步。先让窗口显示出来，
        # detect_device() 在事件循环转起来之后再补上结果
        self.gpu = None
        self.detected = QLabel()
        self._live(self._show_device)
        engine_row = QHBoxLayout()
        engine_row.addWidget(self.model, 1)
        engine_row.addWidget(self._label("设备"))
        engine_row.addWidget(self.device, 1)
        engine_row.addWidget(self.detected)
        form.addRow(self._label("识别模型"), engine_row)

        self.multi_language = QCheckBox()
        self._text(self.multi_language.setText, "音轨里多种语言混说，逐段识别（会慢一些）")
        source_row = QHBoxLayout()
        source_row.addWidget(self._label("自动识别"))
        source_row.addSpacing(12)
        source_row.addWidget(self.multi_language)
        source_row.addStretch(1)
        form.addRow(self._label("源语言"), source_row)

        self.target = QComboBox()
        self.target.setEditable(True)
        self._choices(self.target, self._target_options, initial="zho_Hans")
        self.target.currentIndexChanged.connect(self._sync_layout_enabled)

        self.layout_mode = QComboBox()
        # 英文选项比中文长得多，让它按最长的一项撑开，别把字截掉
        self.layout_mode.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self._choices(
            self.layout_mode, lambda: [(t(label), value) for label, value in LAYOUT_CHOICES]
        )
        target_row = QHBoxLayout()
        target_row.addWidget(self.target, 1)
        target_row.addWidget(self._label("排版"))
        target_row.addWidget(self.layout_mode)
        form.addRow(self._label("字幕语言"), target_row)

        self.translate_model = QComboBox()
        self.translate_model.addItems(MODEL_REPOS)
        self.translate_model.setCurrentText(DEFAULT_TRANSLATE_MODEL)
        form.addRow(self._label("翻译模型"), self.translate_model)

        self.model_source = QComboBox()
        self._choices(self.model_source, self._source_options, initial=saved.source)
        self.proxy = QLineEdit(saved.proxy)
        self._text(self.proxy.setPlaceholderText, "代理，如 http://127.0.0.1:7890；留空表示不用")
        download_row = QHBoxLayout()
        download_row.addWidget(self.model_source)
        download_row.addWidget(self.proxy, 1)
        form.addRow(self._label("模型下载"), download_row)

        self.ui_language = QComboBox()
        self._choices(self.ui_language, self._language_options, initial=saved.language)
        self.ui_language.currentIndexChanged.connect(self._on_language_changed)
        form.addRow(self._label("界面语言"), self.ui_language)

        self.formats = {}
        format_row = QHBoxLayout()
        for fmt in FORMATS:
            check = QCheckBox(fmt.upper())
            check.setChecked(fmt == "srt")
            self.formats[fmt] = check
            format_row.addWidget(check)
        format_row.addStretch(1)
        form.addRow(self._label("输出格式"), format_row)

        self.output_dir = QLineEdit()
        self._text(self.output_dir.setPlaceholderText, "留空则与视频同目录")
        browse = QPushButton()
        self._text(browse.setText, "浏览…")
        browse.clicked.connect(self._pick_output_dir)
        output_row = QHBoxLayout()
        output_row.addWidget(self.output_dir, 1)
        output_row.addWidget(browse)
        form.addRow(self._label("输出目录"), output_row)
        return box

    def _label(self, source):
        label = QLabel()
        self._text(label.setText, source)
        return label

    def _target_options(self):
        return [(t("不翻译（只输出原文）"), None)] + [
            (f"{name}  [{flores}]", flores) for flores, name in target_choices()
        ]

    def _show_device(self):
        if self.gpu is None:
            self.detected.setText(t("（正在检测显卡…）"))
        else:
            self.detected.setText(
                t("（检测到 NVIDIA 显卡）") if self.gpu else t("（未检测到显卡，用 CPU）")
            )

    def detect_device(self):
        """窗口显示之后再探显卡，并按结果挑默认识别模型。"""
        self.gpu = pick_device()[0] == "cuda"
        self._show_device()
        self.model.setCurrentText(default_model())

    def _language_options(self):
        # 中文 / English 用各语言自己的写法，谁都认得出自己那一项
        return [(t("跟随系统"), settings.AUTO), ("中文", "zh"), ("English", "en")]

    def _source_options(self):
        options = [(t(label), value) for label, value in SOURCE_CHOICES]
        chosen = self.model_source.currentData()
        if chosen and all(value != chosen for _, value in options):
            options.append((chosen, chosen))  # 设置里存的是个自建源地址
        return options

    def _build_actions(self):
        self.start = QPushButton()
        self._text(self.start.setText, "开始生成")
        self.start.setMinimumHeight(36)
        self.start.clicked.connect(self._start)
        self.stop = QPushButton()
        self._text(self.stop.setText, "取消")
        self.stop.setMinimumHeight(36)
        self.stop.setEnabled(False)
        self.stop.clicked.connect(self._stop)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self._live(self._reset_bar)
        self.log = QTextEdit()
        self.log.setReadOnly(True)

        row = QHBoxLayout()
        row.addWidget(self.bar, 1)
        row.addWidget(self.start)
        row.addWidget(self.stop)
        return row

    def _reset_bar(self):
        if self.worker is None or not self.worker.isRunning():
            self.bar.setFormat(t("就绪"))

    # ---------- 文件管理 ----------

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self._add_files([url.toLocalFile() for url in event.mimeData().urls()])

    def _pick_files(self):
        media = f"{t('视频/音频')} ({MEDIA_SUFFIXES});;{t('全部文件')} (*)"
        paths, _ = QFileDialog.getOpenFileNames(self, t("选择视频"), "", media)
        self._add_files(paths)

    def _pick_output_dir(self):
        path = QFileDialog.getExistingDirectory(self, t("选择输出目录"))
        if path:
            self.output_dir.setText(path)

    def _add_files(self, paths):
        existing = {self.table.item(r, 0).data(Qt.UserRole) for r in range(self.table.rowCount())}
        for path in paths:
            if not os.path.isfile(path) or path in existing:
                continue
            name = os.path.basename(path)
            try:
                tracks = probe_tracks(path)
            except Exception as error:
                # 拖进来的可能是任意文件，读不动就跳过并明确告知，不影响其他文件
                self._log(t("⚠ 无法读取 {name}：{error}", name=name, error=error))
                continue
            if not tracks:
                self._log(t("⚠ {name} 没有音轨，已跳过", name=name))
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
        picker.tracks = tracks  # 音轨描述里有语种名，切语言时要重刷
        for track in tracks:
            picker.addItem(track.label, track.index)
        self.table.setCellWidget(row, 1, picker)
        self.table.setItem(row, 2, QTableWidgetItem())
        self._set_status(row, "等待中")

    def _remove_selected(self):
        for index in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(index)

    def _set_status(self, row, source, **fields):
        """状态列存下原文和参数，切语言时能重新渲染。"""
        item = self.table.item(row, 2)
        item.setData(Qt.UserRole, (source, fields))
        item.setText(t(source, **fields))

    def _retranslate_tracks(self):
        for row in range(self.table.rowCount()):
            picker = self.table.cellWidget(row, 1)
            for index, track in enumerate(picker.tracks):
                picker.setItemText(index, track.label)

    def _retranslate_statuses(self):
        for row in range(self.table.rowCount()):
            stored = self.table.item(row, 2).data(Qt.UserRole)
            if stored:
                source, fields = stored
                self.table.item(row, 2).setText(t(source, **fields))

    # ---------- 执行 ----------

    def _sync_layout_enabled(self):
        self.layout_mode.setEnabled(self.target.currentData() is not None)

    def _on_language_changed(self):
        i18n.use(self.ui_language.currentData())
        self._retranslate()
        self._save_settings()

    def _start(self):
        if self.table.rowCount() == 0:
            QMessageBox.information(self, t("还没有文件"), t("请先添加或拖入要生成字幕的视频。"))
            return
        formats = tuple(f for f, box in self.formats.items() if box.isChecked())
        if not formats:
            QMessageBox.information(self, t("没有输出格式"), t("请至少勾选一种字幕格式。"))
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
            self._set_status(row, "等待中")

        self._save_settings()

        key = (
            self.model.currentText(),
            self.device.currentData(),
            self.translate_model.currentText(),
        )
        if key != self.engine_key:
            self.engine, self.engine_key = None, key
            self._log(t("载入模型 {model}…", model=key[0]))

        self.worker = Worker(
            jobs, self.engine, lambda notify: Engine(key[0], key[1], key[2], notify=notify)
        )
        self.worker.note.connect(self._on_note)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_file.connect(self._on_file_done)
        self.worker.load_failed.connect(self._on_load_failed)
        self.worker.all_done.connect(self._on_all_done)
        self._set_running(True)
        self.worker.start()

    def _save_settings(self):
        """下载源、代理、界面语言立刻生效并存下来，命令行下次也用这一份。"""
        current = settings.Settings(
            source=self.model_source.currentData(),
            proxy=self.proxy.text().strip(),
            language=self.ui_language.currentData(),
        )
        hub.apply(current)
        try:
            settings.save(current)
        except OSError as error:
            self._log(t("⚠ 设置没能存下来（{error}），本次运行仍然生效", error=error))

    def _stop(self):
        if self.worker:
            self.worker.cancel.set()
            self.stop.setEnabled(False)
            self.bar.setFormat(t("正在取消…"))

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
            self.model_source,
            self.proxy,
            self.ui_language,
            self.output_dir,
        ):
            widget.setEnabled(not running)

    def _on_note(self, message, fraction):
        """模型下载的提示与进度。带进度就只刷进度条，别把日志刷成一片。"""
        if fraction is None:
            self._log(message)
            return
        self.bar.setValue(int(fraction * 100))
        self.bar.setFormat(f"{message} %p%")

    def _on_progress(self, row, stage, fraction):
        name = self.table.item(row, 0).text()
        self._set_status(row, "{stage} {percent:.0f}%", stage=t(stage), percent=fraction * 100)
        self.bar.setValue(int(fraction * 100))
        self.bar.setFormat(f"{name} — {t(stage)} %p%")

    def _on_file_done(self, row, result, error):
        name = self.table.item(row, 0).text()
        if error is not None:
            self._set_status(row, "失败")
            self._log(t("✗ {name}：{error}", name=name, error=error))
            # 打包成窗口程序后 stderr 是 None，往那儿打堆栈会把界面拖垮，写进日志框
            self._log("".join(traceback.format_exception(type(error), error, error.__traceback__)))
            return
        self._set_status(row, "完成")
        languages = {span[2] for span in result.language_spans}
        detected = "、".join(describe_whisper(code) for code in sorted(languages))
        summary = t("✓ {name}：{languages}", name=name, languages=detected)
        target = self.target.currentData()
        if target:
            summary += f" → {flores_name(target)}"
        self._log(summary + t("，{count} 条字幕", count=len(result.cues)))
        for path in result.outputs:
            self._log(f"    {path}")

    def _on_load_failed(self, error):
        self._log(t("✗ 模型加载失败：{error}", error=error))
        for row in range(self.table.rowCount()):
            stored = self.table.item(row, 2).data(Qt.UserRole)
            if stored and stored[0] == "等待中":  # 已经跑完的行别改掉
                self._set_status(row, "未开始")
        # 下载失败的提示里已经写了怎么办，别再叠一句正确的废话
        hint = (
            "" if isinstance(error, hub.DownloadError) else "\n\n" + t("首次使用需要联网下载模型。")
        )
        QMessageBox.critical(self, t("模型加载失败"), f"{error}{hint}")

    def _on_all_done(self, engine):
        self.engine = engine
        self._set_running(False)
        self._sync_layout_enabled()
        self.bar.setValue(0)
        self._reset_bar()

    def _log(self, message):
        self.log.append(message)

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.cancel.set()
            self.worker.wait(5000)
        event.accept()


def main():
    # 窗口模式下没有标准流，先换成不会炸的替身再说
    runtime.silence_missing_streams()
    runtime.clean_leftovers()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    # 排在事件循环的第一件事：窗口已经画出来了，再去加载 CTranslate2 探显卡
    QTimer.singleShot(0, window.detect_device)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
