"""打包成窗口程序之后才会碰到的几件事：没有标准流、崩溃没人看见、覆盖安装的残留。

这里的函数都要在别的东西之前跑，所以只用标准库，且任何情况下都不抛异常——它们
是来兜底的，不该自己变成新的故障点。
"""

import inspect
import math
import os
import sys
import threading
import time
import traceback

#: 清理记录，内容是清理过的版本号。不在发布清单里，得手动放过
_MARKER = "cleaned.txt"
#: 发布清单，打包时由 subtitle_tool.spec 写出
_MANIFEST = "shipped.txt"
#: 要删的文件超过发布清单的这个比例就整个放弃——清单对不上时宁可不动，
#: 也不能把用户的安装目录清空
_MAX_LEFTOVER_RATIO = 0.5
#: 日志留最近这么多字节，超了就重开一个
_LOG_LIMIT = 1_000_000
#: 整轨按 int16 常驻，每秒 16000 个样本、每个 2 字节
SAMPLE_BYTES = 16000 * 2


def log_path() -> str:
    """日志位置：和设置放在一起，也就是打包版 exe 的同级目录。"""
    from .settings import directory

    return os.path.join(directory(), "subtitle-tool.log")


def log(text: str) -> None:
    """往日志里追加一段。写不进去就算了，绝不抛异常。"""
    path = log_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.getsize(path) > _LOG_LIMIT:
            os.remove(path)
    except OSError:
        pass
    try:
        with open(path, "a", encoding="utf-8", errors="replace") as handle:
            handle.write(text)
    except OSError:
        pass


def trace(step: str) -> None:
    """记一步「走到哪儿了」，每条都落盘。

    进程要是被系统直接干掉（C++ 里内存分配失败是 abort，连 Python 异常都没有），
    事后唯一能拿到的线索就是这份流水账的最后一行。所以宁可多写几行。
    """
    log(f"[{time.strftime('%H:%M:%S')}] {step}\n")


#: 正常收尾时写的最后一行，用来判断上次是不是被中途干掉的
_FINISHED = "程序退出"


def finished() -> None:
    """正常结束时记一笔，下次启动据此判断上次有没有出事。"""
    trace(_FINISHED)


def last_unfinished():
    """上次运行没收尾的话，返回它停在哪一步；正常结束返回 None。"""
    try:
        with open(log_path(), encoding="utf-8", errors="replace") as handle:
            lines = [line.strip() for line in handle if line.strip()]
    except OSError:
        return None
    if not lines or _FINISHED in lines[-1]:
        return None
    return lines[-1]


def memory_note() -> str:
    """当前可用内存，写进流水账用。取不到就空着。"""
    try:
        if sys.platform == "win32":
            import ctypes

            class _Status(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = _Status()
            status.dwLength = ctypes.sizeof(_Status)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            free = status.ullAvailPhys / 1073741824
            total = status.ullTotalPhys / 1073741824
            return f"内存可用 {free:.1f}/{total:.1f}GB"
        with open("/proc/meminfo") as handle:
            values = {}
            for line in handle:
                name, _, rest = line.partition(":")
                values[name] = int(rest.split()[0]) / 1048576
        return f"内存可用 {values['MemAvailable']:.1f}/{values['MemTotal']:.1f}GB"
    except Exception:
        return ""


#: 各识别模型加载后大致占多少内存（GB，int8 量化）
_MODEL_MEMORY = {
    "tiny": 0.2,
    "base": 0.3,
    "small": 0.8,
    "medium": 1.8,
    "distil-large-v3": 1.8,
    "large-v3-turbo": 2.0,
    "large-v3": 3.5,
}

#: 转写档位，从阔绰到拮据：(窗口秒数, 批大小, 该档位的工作内存基准 GB)。
#:
#: 基准值来自实测：tiny + 10 分钟窗口 + 批 8，转写开头的峰值比模型本身多约 0.67GB。
#: 大模型的中间张量更大，按模型自身占用缩放（见 _work）。窗口和批都调小之后内存跟着降，
#: 代价只是慢一点——比直接崩掉强得多。
_PROFILES = (
    (600.0, 8, 0.90),
    (300.0, 4, 0.55),
    (150.0, 2, 0.35),
    (60.0, 1, 0.22),
)
#: 留一成余量给系统和其它程序，别掐着线跑
_HEADROOM = 0.9


def available_memory() -> float:
    """当前可用物理内存（GB）。取不到返回 0。"""
    note = memory_note()
    try:
        return float(note.split()[1].split("/")[0])
    except (IndexError, ValueError):
        return 0.0


def _work(base: float, model: str) -> float:
    """某个档位在某个模型下的工作内存估计。"""
    return base * (0.6 + _MODEL_MEMORY.get(model, 1.0))


def plan_transcription(model: str, seconds: float) -> tuple:
    """按当前可用内存挑一个跑得动的转写档位。

    返回 ``(窗口秒数, 批大小, 提示)``：提示为 None 表示宽裕；否则是一句给用户看的话。
    实在连最省的档位都摆不下时，窗口/批返回 None——调用方据此友好地拒绝，
    而不是冲进去让原生层把进程干掉。

    读不到内存信息（非 Windows/Linux）时按最阔绰的档位走，行为和以前一致。
    """
    free = available_memory()
    if not free:
        return _PROFILES[0][0], _PROFILES[0][1], None

    fixed = _MODEL_MEMORY.get(model, 1.0) + seconds * SAMPLE_BYTES / 1073741824
    for index, (window, batch, base) in enumerate(_PROFILES):
        if fixed + _work(base, model) <= free * _HEADROOM:
            if index == 0:
                return window, batch, None
            from .i18n import t

            return (
                window,
                batch,
                t(
                    "内存偏紧（可用 {free:.1f}GB），已自动把处理粒度调小，会慢一些但能跑完",
                    free=free,
                ),
            )

    from .i18n import t

    # 两个数都保留一位小数时很容易看着一样大（0.4 与 0.4），可用的往下取、
    # 需要的往上取，读起来才是「不够」
    least = (fixed + _work(_PROFILES[-1][2], model)) / _HEADROOM
    return (
        None,
        None,
        t(
            "内存不够：可用 {free:.1f}GB，至少要 {need:.1f}GB。请关掉些程序或换更小的识别模型",
            free=math.floor(free * 10) / 10,
            need=math.ceil(least * 10) / 10,
        ),
    )


def out_of_memory_message() -> str:
    """真的分配失败时给用户看的话。"""
    from .i18n import t

    return t("内存不足，没能跑完这个文件。换更小的识别模型，或关掉些占内存的程序再试")


def report_crashes() -> None:
    """未捕获的异常记进日志，别让进程一声不吭地消失。

    窗口模式下 PySide6 碰到槽函数里的异常会直接结束进程，用户看到的就是「闪退」，
    什么线索都不留。至少得留下一份能贴给我们看的东西。
    """
    previous = sys.excepthook

    def hook(kind, value, tb):
        log("".join(traceback.format_exception(kind, value, tb)))
        previous(kind, value, tb)  # 有控制台时照旧打出来

    sys.excepthook = hook
    if hasattr(threading, "excepthook"):
        threading.excepthook = lambda args: hook(args.exc_type, args.exc_value, args.exc_traceback)


def guarded(slot, report=None):
    """包一层再接到 Qt 信号上。

    槽函数里抛出去的异常会让 PySide6 直接结束进程——用户看到的就是「闪退」，一点线索
    都不留。兜住，记进崩溃日志，界面继续能用。

    只把槽函数吃得下的那几个参数传过去：Qt 会给 clicked 发 checked、给
    currentIndexChanged 发下标。直接接 bound method 时 Qt 按签名截断，包一层之后
    得自己来，否则每个按钮都会 TypeError。
    """
    wanted = len(inspect.signature(slot).parameters)

    def call(*args):
        try:
            return slot(*args[:wanted])
        except Exception:
            text = traceback.format_exc()
            log(text)
            if report is not None:
                report(text)
            return None

    return call


class _Sink:
    """吞掉一切输出。

    Windows 上以窗口模式（无控制台）启动时 ``sys.stdout`` / ``sys.stderr`` 是 None，
    任何 print、tqdm 进度条、traceback 写过去都会抛
    ``AttributeError: 'NoneType' object has no attribute 'write'``。v0.1.4 里翻译模型
    下载到一半整个界面失去响应，就是这条链子：huggingface_hub 的进度条往 None 上写 →
    异常冒进 Qt 槽函数 → 打印这个异常又要用 stderr → 进程卡死。
    """

    encoding = "utf-8"
    errors = "replace"
    closed = False
    #: 有些库会走 sys.stdout.buffer 写字节，别让它撞上 AttributeError
    buffer = None

    def write(self, text):
        return len(text)

    def writelines(self, lines):
        pass

    def flush(self):
        pass

    def isatty(self):
        return False

    def readable(self):
        return False

    def writable(self):
        return True

    def seekable(self):
        return False

    def fileno(self):
        raise OSError("窗口模式下没有标准流")

    def close(self):
        pass


def silence_missing_streams() -> None:
    """标准流缺席时换成不会炸的替身。有控制台时原样不动。"""
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            setattr(sys, name, _Sink())


def clean_leftovers() -> int:
    """删掉安装目录里不属于本次发布的文件，返回删掉的个数。

    免安装包是解压即用的，用户升级时习惯直接把新版覆盖上去。旧版多出来的 DLL / .pyd
    会留在原地，轻则白占几百 MB，重则被 Python 抢先加载到旧版本上。因此打包时写一份
    发布清单，启动时按清单把多余的文件清掉。

    只动 PyInstaller 自己的 ``_internal`` 目录——那里 100% 是我们放的东西；模型缓存在
    用户目录下，不在这个范围内，升级不会碰它。
    """
    root = _internal_dir()
    if root is None:
        return 0
    try:
        with open(os.path.join(root, _MANIFEST), encoding="utf-8") as handle:
            shipped = {line.strip() for line in handle if line.strip()}
    except OSError:
        return 0  # 没有清单（源码运行或旧版打的包）就什么都别删
    shipped.update((_MANIFEST, _MARKER))

    marker = os.path.join(root, _MARKER)
    version = _version()
    if _read(marker) == version:
        return 0  # 这个版本已经清过，别每次启动都扫一遍上万个文件

    extra = [
        os.path.join(current, name)
        for current, _, files in os.walk(root)
        for name in files
        if os.path.relpath(os.path.join(current, name), root).replace(os.sep, "/") not in shipped
    ]
    if len(extra) > len(shipped) * _MAX_LEFTOVER_RATIO:
        # 要删的比该留的还多一半，多半是清单跟目录对不上（解压不全、清单写坏）。
        # 这种时候删下去就是把用户的安装目录毁掉，宁可什么都不做。
        log(f"发布清单与安装目录对不上（清单 {len(shipped)} 项，多出 {len(extra)} 项），跳过清理\n")
        return 0

    removed = 0
    for path in extra:
        try:
            os.remove(path)
            removed += 1
        except OSError:
            pass  # 正在被加载的 DLL 删不掉，留着就留着
    for current, _, _ in os.walk(root, topdown=False):
        try:
            if current != root and not os.listdir(current):
                os.rmdir(current)
        except OSError:
            pass
    _write(marker, version)
    return removed


def _internal_dir():
    """打包后的 ``_internal`` 目录；源码运行时返回 None。"""
    if not getattr(sys, "frozen", False):
        return None
    root = getattr(sys, "_MEIPASS", None)
    return root if root and os.path.isdir(root) else None


def _version() -> str:
    from . import __version__

    return __version__


def _read(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return None


def _write(path, text):
    try:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
    except OSError:
        pass
