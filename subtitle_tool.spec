# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：产出免安装的 Windows 单目录程序。

用单目录（onedir）而不是单文件（onefile）：单文件每次启动都要把几百 MB 解压到临时
目录，冷启动要十几秒，且杀毒软件误报率高。
"""

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

# Silero VAD 的 onnx 权重随 faster-whisper 一起分发，不打进去运行时会找不到
datas = collect_data_files("faster_whisper")

# 推理运行时的原生库，PyInstaller 的自动扫描抓不全
binaries = (
    collect_dynamic_libs("ctranslate2")
    + collect_dynamic_libs("onnxruntime")
    + collect_dynamic_libs("av")
)

# 这些包没被直接 import，靠运行时动态加载
hiddenimports = ["ctranslate2", "onnxruntime", "av"]

# 明确排掉体积大又用不到的东西，装机包能小一半
excludes = [
    "tkinter",
    "matplotlib",
    "scipy",
    "pandas",
    "IPython",
    "pytest",
    "PIL",
    "torch",
    "PySide6.Qt3DCore",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia",
    "PySide6.QtQuick",
    "PySide6.QtQml",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtOpenGL",
    "PySide6.QtNetwork",
    "PySide6.QtSql",
    "PySide6.QtTest",
]

a = Analysis(
    ["scripts/launch_gui.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SubtitleTool",  # 用 ASCII 名，免得打包/压缩/快捷方式在非 UTF-8 代码页下出问题
    debug=False,
    strip=False,
    upx=False,  # UPX 压缩过的原生库在部分杀毒软件下会被拦
    console=False,  # GUI 程序，不弹黑框
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="subtitle-tool",
)
