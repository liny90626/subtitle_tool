"""视频字幕生成工具：自动识别音轨语言，转写并翻译为目标语言字幕。"""

from . import hub, i18n, settings

__version__ = "0.7.0"


def _apply_saved_settings():
    """启动时套用上次存下的设置。

    下载源与代理必须在 huggingface_hub 被导入之前写进环境变量——它在 import 时就把
    HF_ENDPOINT 读成了模块常量。包一被导入就生效是唯一稳妥的时机。
    """
    saved = settings.load()
    hub.apply(saved)
    i18n.use(saved.language)


_apply_saved_settings()
