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

# 明确排掉体积大又用不到的东西。界面只用到 QtCore / QtGui / QtWidgets，
# Qt 其余那几十个模块一个都不需要，排掉能省下几百 MB。
# 排错了会在 CI 的冒烟测试里当场暴露——那一步真的把窗口拉起来。
excludes = [
    "tkinter",
    "matplotlib",
    "scipy",
    "pandas",
    "IPython",
    "pytest",
    "PIL",
    "torch",
] + [
    f"PySide6.{module}"
    for module in (
        "Qt3DAnimation",
        "Qt3DCore",
        "Qt3DExtras",
        "Qt3DInput",
        "Qt3DLogic",
        "Qt3DRender",
        "QtBluetooth",
        "QtCharts",
        "QtDataVisualization",
        "QtDBus",
        "QtDesigner",
        "QtGraphs",
        "QtHelp",
        "QtHttpServer",
        "QtLocation",
        "QtMultimedia",
        "QtMultimediaWidgets",
        "QtNetwork",
        "QtNetworkAuth",
        "QtNfc",
        "QtOpenGL",
        "QtOpenGLWidgets",
        "QtPdf",
        "QtPdfWidgets",
        "QtPositioning",
        "QtPrintSupport",
        "QtQml",
        "QtQuick",
        "QtQuick3D",
        "QtQuickControls2",
        "QtQuickWidgets",
        "QtRemoteObjects",
        "QtScxml",
        "QtSensors",
        "QtSerialPort",
        "QtSpatialAudio",
        "QtSql",
        "QtStateMachine",
        "QtSvg",
        "QtSvgWidgets",
        "QtTest",
        "QtTextToSpeech",
        "QtUiTools",
        "QtWebChannel",
        "QtWebEngineCore",
        "QtWebEngineWidgets",
        "QtWebSockets",
        "QtXml",
    )
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

# 发布清单：免安装包是解压即用的，用户升级时习惯直接覆盖到原目录，旧版多出来的
# DLL / .pyd 会留在那儿白占地方，甚至被 Python 抢先加载。程序启动时按这份清单把
# 不属于本次发布的文件清掉（见 subtitle_tool/runtime.py）。
import os

internal = os.path.join(DISTPATH, coll.name, "_internal")
shipped = sorted(
    os.path.relpath(os.path.join(current, name), internal).replace(os.sep, "/")
    for current, _, files in os.walk(internal)
    for name in files
)
with open(os.path.join(internal, "shipped.txt"), "w", encoding="utf-8") as handle:
    handle.write("\n".join([*shipped, "shipped.txt"]))
print(f"发布清单：{len(shipped) + 1} 个文件")
