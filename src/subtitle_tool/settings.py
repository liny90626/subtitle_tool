"""程序设置：模型下载源、代理、界面语言。图形界面与命令行共用一份。

存在 ``%APPDATA%\\subtitle-tool\\settings.json``（其它平台放 ``~/.config``）。
读坏了一律退回默认值——一个设置文件不该让程序起不来。
"""

import json
import os
from dataclasses import asdict, dataclass

#: 「跟着环境走」：下载源指自动选源，界面语言指跟随系统
AUTO = "auto"


@dataclass
class Settings:
    """全部可持久化的设置。"""

    source: str = AUTO  #: 模型下载源：AUTO，或某个下载源地址
    proxy: str = ""  #: 形如 http://127.0.0.1:7890，留空表示不用代理
    language: str = AUTO  #: 界面语言：AUTO / zh / en


def path() -> str:
    """设置文件路径。Windows 放 %APPDATA%，其它平台放 ~/.config。"""
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "subtitle-tool", "settings.json")


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
