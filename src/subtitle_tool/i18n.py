"""界面文案的中英切换。

中文原文直接当查表的键：源码里 ``t("开始生成")`` 一眼就看得出会显示什么，不用另
发明一套 key，缺翻译时自动退回中文原文。文案里的变量一律写成 ``{名字}`` 占位符交给
``t()`` 去 format——不要在外面先拼好 f-string，那样查不到表。

英文文案集中在本模块末尾的 ``_ENGLISH`` 里；``tests/test_i18n.py`` 会扫一遍源码，
保证每一处 ``t()`` 的原文都有对应译文。
"""

import os
import sys

from .settings import AUTO

#: 界面语言的可选值
LANGUAGES = (AUTO, "zh", "en")

_language = "zh"


def use(language: str = AUTO) -> None:
    """设定界面语言。``AUTO``（或不认识的值）表示跟随系统。"""
    global _language
    _language = language if language in ("zh", "en") else _system_language()


def language() -> str:
    """当前实际使用的语言，``zh`` 或 ``en``。"""
    return _language


def t(text: str, **fields) -> str:
    """取当前语言下的文案。``fields`` 用于填 ``{名字}`` 占位符。"""
    translated = _ENGLISH.get(text, text) if _language == "en" else text
    return translated.format(**fields) if fields else translated


def _system_language() -> str:
    """判定系统语言。判不出来时按中文——这个工具本来就是中文优先的。"""
    if sys.platform == "win32":
        try:
            import ctypes

            # 主语言 ID 0x04 是中文（简体 0x0804、繁体 0x0404 等都归它）
            return (
                "zh" if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x04 else "en"
            )
        except Exception:
            return "zh"
    tag = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or ""
    if not tag or tag.upper() in ("C", "POSIX", "C.UTF-8"):
        return "zh"
    return "zh" if tag.lower().startswith("zh") else "en"


#: 中文原文 -> 英文。改左边的中文时记得同步这里，否则英文界面会退回中文。
_ENGLISH = {
    "字幕生成工具": "Subtitle Tool",
    "① 选择视频（可直接把文件拖进来）": "① Choose videos (you can drop files here)",
    "② 识别与翻译设置": "② Recognition and translation settings",
    "文件": "File",
    "音轨": "Track",
    "状态": "Status",
    "添加文件…": "Add files…",
    "清空": "Clear",
    "移除选中": "Remove selected",
    "选中后按 Delete 可移除": "Select a row and press Delete to remove it",
    "开始生成": "Start",
    "取消": "Cancel",
    "浏览…": "Browse…",
    "就绪": "Ready",
    "正在取消…": "Cancelling…",
    "识别模型": "Speech model",
    "设备": "Device",
    "（检测到 NVIDIA 显卡）": "(NVIDIA GPU detected)",
    "（未检测到显卡，用 CPU）": "(no GPU detected, using CPU)",
    "源语言": "Source language",
    "自动识别": "Detected automatically",
    "音轨里多种语言混说，逐段识别（会慢一些）": (
        "The track mixes languages; detect per segment (slower)"
    ),
    "字幕语言": "Subtitle language",
    "不翻译（只输出原文）": "No translation (source text only)",
    "排版": "Layout",
    "只要译文": "Translation only",
    "双语对照": "Bilingual",
    "只要原文": "Source only",
    "翻译模型": "Translation model",
    "模型下载": "Model download",
    "自动": "Auto",
    "自动选源": "Pick automatically",
    "官方 huggingface.co": "Official huggingface.co",
    "镜像 hf-mirror.com": "Mirror hf-mirror.com",
    "代理，如 http://127.0.0.1:7890；留空表示不用": (
        "Proxy, e.g. http://127.0.0.1:7890; leave empty for none"
    ),
    "界面语言": "Interface language",
    "跟随系统": "Follow system",
    "输出格式": "Output formats",
    "输出目录": "Output folder",
    "留空则与视频同目录": "Leave empty to use the video folder",
    "选择视频": "Choose videos",
    "选择输出目录": "Choose an output folder",
    "还没有文件": "No files yet",
    "请先添加或拖入要生成字幕的视频。": "Add or drop in the videos you want subtitles for first.",
    "没有输出格式": "No output format",
    "请至少勾选一种字幕格式。": "Tick at least one subtitle format.",
    "视频/音频": "Video/audio",
    "全部文件": "All files",
    "模型加载失败": "Model loading failed",
    "首次使用需要联网下载模型。": "The models are downloaded from the internet on first use.",
    "等待中": "Waiting",
    "完成": "Done",
    "失败": "Failed",
    "未开始": "Not started",
    "载入模型 {model}…": "Loading model {model}…",
    "识别模型 {model}": "speech model {model}",
    "翻译模型 {model}": "translation model {model}",
    "解码音轨": "Decoding audio",
    "识别语种": "Detecting language",
    "语音转写": "Transcribing",
    "标注语种": "Labelling languages",
    "翻译字幕": "Translating",
    "写出文件": "Writing files",
    "✓ {name}：{languages}": "✓ {name}: {languages}",
    "✗ {name}：{error}": "✗ {name}: {error}",
    "✗ 模型加载失败：{error}": "✗ Could not load the model: {error}",
    "⚠ 无法读取 {name}：{error}": "⚠ Could not read {name}: {error}",
    "⚠ {name} 没有音轨，已跳过": "⚠ {name} has no audio track, skipped",
    "⚠ 设置没能存下来（{error}），本次运行仍然生效": (
        "⚠ Could not save the settings ({error}); they still apply to this run"
    ),
    "源语种 {language}": "Source language {language}",
    "，共 {count} 种语言": ", {count} languages",
    "，{count} 条字幕": ", {count} subtitle lines",
    "{name}({code})": "{name} ({code})",
    "音轨 {number}": "Track {number}",
    "{label} | 时长 {duration:.1f}s": "{label} | duration {duration:.1f}s",
    "{name} 里没有音轨，无法生成字幕": "{name} has no audio track, cannot make subtitles",
    "{name} 只有 {total} 条音轨，没有第 {wanted} 条": (
        "{name} has only {total} audio track(s); there is no track {wanted}"
    ),
    "{path} 只有 {total} 条音轨，无法选择第 {wanted} 条": (
        "{path} has only {total} audio track(s); track {wanted} cannot be selected"
    ),
    "{path} 第 {number} 条音轨没有解出任何音频数据": (
        "No audio data could be decoded from track {number} of {path}"
    ),
    "{name} 的第 {number} 条音轨里没有检测到语音": "No speech detected in track {number} of {name}",
    "翻译模型不支持源语种 {language}": (
        "The translation model does not support the source language {language}"
    ),
    "不支持的字幕格式：{format}": "Unsupported subtitle format: {format}",
    "无法识别的目标语种：{value}（用 --list-languages 查看可选值）": (
        "Unknown target language: {value} (run --list-languages to see the choices)"
    ),
    "正在从 {source} 下载{what}，首次使用需要等一会儿，之后一直复用本地缓存。": (
        "Downloading {what} from {source}. The first run takes a while; after that the local "
        "cache is reused."
    ),
    "{what} 下载失败，通常是连不上下载源 {source}。可以试试：\n{steps}\n原始错误：{error}": (
        "Could not download {what}, usually because {source} is unreachable. Things to try: "
        "{steps} Original error: {error}"
    ),
    "把「模型下载源」改成「镜像 hf-mirror.com」（命令行加 --model-source mirror）": (
        'Set "Model download" to the hf-mirror.com mirror (or pass --model-source mirror)'
    ),
    "把「模型下载源」改回「自动选源」（命令行加 --model-source auto）": (
        'Set "Model download" back to "Pick automatically" (or pass --model-source auto)'
    ),
    "有代理/VPN 就填上「代理」，例如 http://127.0.0.1:7890（命令行加 --proxy 代理地址）": (
        'If you have a proxy or VPN, fill in "Proxy", e.g. http://127.0.0.1:7890 (or pass --proxy)'
    ),
    "在能联网的机器上下好模型，把整个 {cache} 目录复制过来": (
        "Download the models on a machine that has access, then copy the whole {cache} folder over"
    ),
    "从视频音轨生成字幕：自动识别语种，可翻译为指定目标语言。": (
        "Generate subtitles from a video soundtrack: the language is detected automatically and "
        "can be translated into a target language."
    ),
    "视频/音频文件，可传多个": "Video/audio files; several may be given",
    "只列出音轨信息后退出": "List the audio tracks and exit",
    "列出可选目标语种后退出": "List the available target languages and exit",
    "使用第几条音轨，从 1 开始（默认 1）": "Which audio track to use, starting at 1 (default 1)",
    "识别模型（按当前设备默认 {default}）": "Speech model ({default} by default on this device)",
    "推理设备（默认自动）": "Inference device (auto by default)",
    "指定源语种的 Whisper 码，默认自动识别": (
        "Whisper code of the source language; detected automatically by default"
    ),
    "一条音轨内多语言混说时逐段识别语种": (
        "Detect the language per segment when one track mixes several languages"
    ),
    "字幕目标语种，接受短码、FLORES 码或语种名": (
        "Target language: short code, FLORES code or language name"
    ),
    "译文/原文/双语排版（默认 target）": "Translation / source / bilingual layout (default target)",
    "输出格式，逗号分隔，可选 {formats}（默认 srt）": (
        "Output formats, comma separated, chosen from {formats} (default srt)"
    ),
    "输出目录，默认与视频同目录": "Output directory; defaults to the video folder",
    "翻译模型（默认 {default}）": "Translation model (default {default})",
    "模型缓存目录，默认用 HuggingFace 默认缓存": (
        "Model cache directory; defaults to the HuggingFace cache"
    ),
    "模型下载源：auto（默认，官方源连不上自动换镜像）/ official / mirror / 自建源地址": (
        "Model download source: auto (default, falls back to the mirror when the official host "
        "is unreachable) / official / mirror, or your own endpoint"
    ),
    "下载模型走的代理，例如 http://127.0.0.1:7890": (
        "Proxy used to download the models, e.g. http://127.0.0.1:7890"
    ),
    "界面语言：auto（跟随系统）/ zh / en": "Interface language: auto (follow the system) / zh / en",
}
