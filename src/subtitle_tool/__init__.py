"""视频字幕生成工具：自动识别音轨语言，转写并翻译为目标语言字幕。"""

from . import hub

__version__ = "0.1.2"

# 下载源与代理必须在 huggingface_hub 被导入之前写进环境变量——它在 import 时就把
# HF_ENDPOINT 读成模块常量了。包一被导入就生效是唯一稳妥的时机。
hub.apply(hub.load())
