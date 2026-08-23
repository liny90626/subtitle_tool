"""打包成窗口程序之后才会碰到的几件事：没有标准流、崩溃没人看见、覆盖安装的残留。

这里的函数都要在别的东西之前跑，所以只用标准库，且任何情况下都不抛异常——它们
是来兜底的，不该自己变成新的故障点。
"""

import inspect
import os
import sys
import threading
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


def log_path() -> str:
    """崩溃日志的位置。窗口模式下没有控制台，出了事只能往这儿写。"""
    from .settings import path as settings_path

    return os.path.join(os.path.dirname(settings_path()), "subtitle-tool.log")


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
