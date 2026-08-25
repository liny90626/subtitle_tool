# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：产出免安装的 Windows 单目录程序。

用单目录（onedir）而不是单文件（onefile）：单文件每次启动都要把几百 MB 解压到临时
目录，冷启动要十几秒，且杀毒软件误报率高。
"""

import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

# Silero VAD 的 onnx 权重随 faster-whisper 一起分发，不打进去运行时会找不到；
# 图标既要给 exe 用，也要程序自己 setWindowIcon，所以还得作为数据文件带上
datas = collect_data_files("faster_whisper") + [
    ("src/subtitle_tool/assets/icon.ico", "subtitle_tool/assets"),
]

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
    # Xet 是 huggingface_hub 的加速下载后端，11MB 的原生扩展。没有它会自动退回普通
    # HTTP，实测下模型一样快；顺带也省掉了它从自己的线程回调进 Python 这条路
    "hf_xet",
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

# PySide6 的钩子会把整套 Qt 收进来，光按模块名排除拦不住——Qt 的动态库是按依赖关系
# 抓的。QML/Quick 那一整套是被虚拟键盘输入法插件顺带拖进来的，界面只用 QtWidgets 根本
# 用不上；opengl32sw 是 Qt 的软件 OpenGL 兜底，widgets 走光栅渲染也用不到。
# 删错了 CI 的冒烟测试会当场暴露——那一步真的把界面拉起来并跑完整条流水线。
UNUSED = (
    "qt6quick",
    "qt6qml",
    "qt6virtualkeyboard",
    "qt6pdf",
    "platforminputcontexts",
    "opengl32sw",
)


def wanted(entry):
    name = entry[0].replace("\\", "/").lower()
    return not any(marker in name for marker in UNUSED)


a = Analysis(
    ["scripts/launch_gui.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)

dropped = len(a.binaries) + len(a.datas)
a.binaries = [entry for entry in a.binaries if wanted(entry)]
a.datas = [entry for entry in a.datas if wanted(entry)]
print(f"dropped {dropped - len(a.binaries) - len(a.datas)} unused Qt/Xet files")

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
    icon="src/subtitle_tool/assets/icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="subtitle-tool",
)

# Windows 上线程默认栈只有 1.91MB（PyInstaller 引导器写死在 PE 头里），Linux 是 8MB。
# 转写长片时 CTranslate2 的工作线程会踩爆它，表现为进程以 0xC00000FD 直接消失——同一份
# 代码在 Linux 上永远复现不出来。这里把 PE 头里的栈保留改到 16MB。
sys.path.insert(0, os.path.join(SPECPATH, "scripts"))
import patch_stack

_exe = os.path.join(DISTPATH, coll.name, "SubtitleTool.exe")
if os.path.exists(_exe):
    _was = patch_stack.patch(_exe)
    print(f"stack reserve {_was / 1048576:.2f}MB -> {patch_stack.STACK_RESERVE / 1048576:.0f}MB")

# 发布清单：免安装包是解压即用的，用户升级时习惯直接覆盖到原目录，旧版多出来的
# DLL / .pyd 会留在那儿白占地方，甚至被 Python 抢先加载。程序启动时按这份清单把
# 不属于本次发布的文件清掉（见 subtitle_tool/runtime.py）。

internal = os.path.join(DISTPATH, coll.name, "_internal")
shipped = sorted(
    os.path.relpath(os.path.join(current, name), internal).replace(os.sep, "/")
    for current, _, files in os.walk(internal)
    for name in files
)
with open(os.path.join(internal, "shipped.txt"), "w", encoding="utf-8") as handle:
    handle.write("\n".join([*shipped, "shipped.txt"]))
print(f"shipped.txt lists {len(shipped) + 1} files")
