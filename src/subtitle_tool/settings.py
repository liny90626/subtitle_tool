"""程序设置：模型下载源、代理、界面语言。图形界面与命令行共用一份。

免安装包是解压即用的，设置和日志就放在 exe 同级目录——拷走整个文件夹就带走了全部状态，
不用去 %APPDATA% 里翻。装在只读目录（Program Files 之类）时退回用户目录，免得连设置都
存不下来。源码运行时没有 exe，同样放用户目录。

读坏了一律退回默认值——一个设置文件不该让程序起不来。
"""

import json
import os
import sys
from dataclasses import asdict, dataclass

#: 「跟着环境走」：下载源指自动选源，界面语言指跟随系统
AUTO = "auto"


@dataclass
class Settings:
    """全部可持久化的设置。"""

    source: str = AUTO  #: 模型下载源：AUTO，或某个下载源地址
    proxy: str = ""  #: 形如 http://127.0.0.1:7890，留空表示不用代理
    language: str = AUTO  #: 界面语言：AUTO / zh / en


_directory = None


def directory() -> str:
    """设置和日志所在的目录。打包版就在 exe 旁边。"""
    global _directory
    if _directory is None:
        _directory = _writable(_beside_executable()) or _user_directory()
    return _directory


def path() -> str:
    """设置文件路径。"""
    return os.path.join(directory(), "settings.json")


def _beside_executable():
    """打包版的 exe 同级目录；源码运行时返回 None。"""
    return os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else None


def _user_directory() -> str:
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "subtitle-tool")


def _writable(candidate):
    """能写才用它。装在 Program Files 下时这里会失败，那就退回用户目录。"""
    if candidate is None:
        return None
    probe = os.path.join(candidate, ".write-test")
    try:
        os.makedirs(candidate, exist_ok=True)
        with open(probe, "w"):
            pass
        os.remove(probe)
        return candidate
    except OSError:
        return None


def load() -> Settings:
    """读设置。文件不存在或读坏了都退回默认值。"""
    try:
        with open(path(), encoding="utf-8") as handle:
            data = json.load(handle)
        return Settings(
            source=str(data.get("source") or AUTO),
            proxy=str(data.get("proxy") or ""),
            language=str(data.get("language") or AUTO),
        )
    except (OSError, ValueError, AttributeError):
        return Settings()


def save(settings: Settings) -> None:
    """写设置。写不进去（目录只读等）会抛 OSError，由调用方决定怎么提示。"""
    target = path()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(asdict(settings), handle, ensure_ascii=False, indent=2)
