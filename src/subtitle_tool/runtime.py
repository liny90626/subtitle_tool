"""打包成窗口程序之后才会碰到的两件事：没有标准流、覆盖安装留下的旧文件。

两个函数都要在别的东西之前跑，所以只用标准库，且任何情况下都不抛异常——它们
是来兜底的，不该自己变成新的故障点。
"""

import os
import sys

#: 清理记录，内容是清理过的版本号。不在发布清单里，得手动放过
_MARKER = "cleaned.txt"
#: 发布清单，打包时由 subtitle_tool.spec 写出
_MANIFEST = "shipped.txt"


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

    def write(self, text):
        return len(text)

    def flush(self):
        pass

    def isatty(self):
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

    removed = 0
    for current, _, files in os.walk(root, topdown=False):
        for name in files:
            path = os.path.join(current, name)
            relative = os.path.relpath(path, root).replace(os.sep, "/")
            if relative in shipped:
                continue
            try:
                os.remove(path)
                removed += 1
            except OSError:
                pass  # 正在被加载的 DLL 删不掉，留着就留着
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
