"""字幕文件生成：SRT / WebVTT / 纯文本。"""

from dataclasses import dataclass

from .i18n import t

FORMATS = ("srt", "vtt", "txt")

#: 单行最大字符数。拉丁字母按通行的 42 字符，CJK 因字宽是两倍取 20。
_LATIN_LIMIT = 42
_CJK_LIMIT = 20
#: 单条字幕的最短停留时长，低于此值来不及看清
MIN_CUE_SECONDS = 1.2


@dataclass
class Cue:
    """一条字幕。``text`` 内的换行用于分隔双语的原文与译文。"""

    start: float
    end: float
    text: str


def stretch_cues(cues: list[Cue]) -> list[Cue]:
    """把过短的字幕延长到看得清，最多顶到下一条开始，不改动文本。

    停顿处断句会切出「to publish,」这类不到半秒的短条，按每秒约 15 字符的阅读速度
    根本来不及看。延长而不是合并，是为了保住与语音对齐的起始时间。
    """
    for index, cue in enumerate(cues):
        ceiling = cues[index + 1].start if index + 1 < len(cues) else cue.end + MIN_CUE_SECONDS
        cue.end = min(max(cue.end, cue.start + MIN_CUE_SECONDS), max(ceiling, cue.end))
    return cues


def render(cues: list[Cue], fmt: str) -> str:
    """把字幕渲染成指定格式的文本内容。"""
    if fmt == "srt":
        return _render_srt(cues)
    if fmt == "vtt":
        return _render_vtt(cues)
    if fmt == "txt":
        return "\n".join(cue.text.replace("\n", " ") for cue in cues) + "\n"
    raise ValueError(t("不支持的字幕格式：{format}", format=fmt))


def _render_srt(cues: list[Cue]) -> str:
    blocks = []
    for i, cue in enumerate(cues, 1):
        start, end = _sane_range(cue)
        blocks.append(f"{i}\n{_stamp(start, ',')} --> {_stamp(end, ',')}\n{_layout(cue.text)}\n")
    return "\n".join(blocks)


def _render_vtt(cues: list[Cue]) -> str:
    blocks = ["WEBVTT\n"]
    for cue in cues:
        start, end = _sane_range(cue)
        blocks.append(f"{_stamp(start, '.')} --> {_stamp(end, '.')}\n{_layout(cue.text)}\n")
    return "\n".join(blocks)


def _sane_range(cue: Cue):
    """Whisper 偶尔给出零长甚至倒挂的时间轴，会让播放器直接跳过该条。"""
    return cue.start, max(cue.end, cue.start + 0.1)


def _stamp(seconds: float, decimal: str) -> str:
    ms = round(max(seconds, 0.0) * 1000)
    hours, ms = divmod(ms, 3600_000)
    minutes, ms = divmod(ms, 60_000)
    secs, ms = divmod(ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{decimal}{ms:03d}"


def _layout(text: str) -> str:
    """逐条（双语时逐语言）折行，保证每条字幕不超过两行。"""
    return "\n".join(_wrap(line) for line in text.split("\n") if line)


def _wrap(line: str) -> str:
    limit = _CJK_LIMIT if _is_cjk(line) else _LATIN_LIMIT
    if len(line) <= limit:
        return line
    cut = _split_point(line, limit)
    return f"{line[:cut].rstrip()}\n{line[cut:].lstrip()}" if cut else line


#: CJK 折行优先断在这些标点之后，避免把词拆散
_BREAK_AFTER = "，。、；：？！,.;:?!"


def _split_point(line: str, limit: int) -> int:
    """找最接近正中的断点，让两行长度尽量均衡；找不到就不折行。"""
    middle = len(line) // 2
    if _is_cjk(line):
        marks = [i + 1 for i, ch in enumerate(line[:-1]) if ch in _BREAK_AFTER]
        # 标点离正中太远的话，硬断在正中反而更均衡
        near = [i for i in marks if abs(i - middle) <= limit // 2]
        return min(near, key=lambda i: abs(i - middle)) if near else middle
    spaces = [i for i, ch in enumerate(line) if ch == " "]
    if not spaces:
        return 0
    return min(spaces, key=lambda i: abs(i - middle))


def _is_cjk(text: str) -> bool:
    han = sum(1 for ch in text if "぀" <= ch <= "鿿" or "가" <= ch <= "힯")
    return han * 2 > len(text)
