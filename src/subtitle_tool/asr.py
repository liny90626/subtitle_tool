"""语音识别：faster-whisper(CTranslate2) 封装。

选型理由见 docs/design.md：相同精度下比 openai-whisper 快约 4 倍、显存/内存占用更低，
且不依赖 PyTorch，Windows 打包体积可控。
"""

import threading
from dataclasses import dataclass
from typing import Callable, Optional

import ctranslate2
from faster_whisper import BatchedInferencePipeline, WhisperModel

from .audio import SAMPLE_RATE

#: 可选模型，按「体积 / 速度 / 精度」从轻到重排列
MODEL_SIZES = (
    "tiny",
    "base",
    "small",
    "medium",
    "large-v3",
    "distil-large-v3",
    "large-v3-turbo",
)
DEFAULT_MODEL = "large-v3-turbo"

#: 单条字幕的上限。时长取通行的 7 秒；字数按两行算，CJK 字宽是拉丁字母两倍所以减半。
MAX_CUE_SECONDS = 7.0
_LATIN_CUE_CHARS = 84
_CJK_CUE_CHARS = 40
_WIDE_LANGUAGES = frozenset({"zh", "ja", "yue", "ko"})
#: 词间静音超过这个长度就断开——说话人换气/换句的天然分界
_PAUSE_BREAK = 0.7
#: 句末标点断句时的最小字数，免得切出「是。」这种碎片
_MIN_CUE_CHARS = 12
_SENTENCE_ENDS = (".", "!", "?", "。", "！", "？", "…")
#: 限长断句时可以回退到的标点
_CLAUSE_ENDS = (*_SENTENCE_ENDS, ",", ";", ":", "，", "、", "；", "：")


class Cancelled(Exception):
    """用户中途取消任务。"""


@dataclass
class Segment:
    """一条字幕对应的识别结果。"""

    start: float
    end: float
    text: str
    language: Optional[str] = None  #: 该段的语种；多语种模式下逐段可能不同


def pick_device(preference: str = "auto") -> tuple[str, str]:
    """选定推理设备与量化精度，返回 ``(device, compute_type)``。

    GPU 用 float16（精度损失可忽略、速度最快），CPU 用 int8（比 float32 快 2~3 倍）。
    """
    if preference == "cpu":
        return "cpu", "int8"
    if preference == "cuda" or ctranslate2.get_cuda_device_count() > 0:
        return "cuda", "float16"
    return "cpu", "int8"


class Transcriber:
    """加载一次模型，反复转写。GUI 里跨任务复用以省去重复加载。"""

    def __init__(
        self,
        model_size: str = DEFAULT_MODEL,
        device: str = "auto",
        download_root: Optional[str] = None,
    ):
        self.device, self.compute_type = pick_device(device)
        self.model = WhisperModel(
            model_size,
            device=self.device,
            compute_type=self.compute_type,
            download_root=download_root,
        )
        self.batched = BatchedInferencePipeline(model=self.model)
        self.model_size = model_size

    def detect_language(self, audio, segments: int = 8) -> tuple[str, float]:
        """在整条音轨上采样若干片段判定主语种，返回 ``(whisper 码, 置信度)``。

        只看开头 30 秒容易被片头音乐、外语问候语带偏，因此取多段投票；
        ``vad_filter`` 先剔除静音，避免拿空白片段去猜语种。
        """
        language, probability, _ = self.model.detect_language(
            audio=audio,
            vad_filter=True,
            language_detection_segments=segments,
        )
        return language, probability

    def transcribe(
        self,
        audio,
        language: Optional[str] = None,
        multilingual: bool = False,
        batch_size: int = 8,
        progress: Optional[Callable[[float], None]] = None,
        cancel: Optional[threading.Event] = None,
    ) -> list[Segment]:
        """转写音频。

        ``language`` 为 None 时由模型自行判定；``multilingual=True`` 时逐段重新判定
        语种，用于一条音轨内多语言混说的场景。
        """
        raw_segments, info = self.batched.transcribe(
            audio,
            language=language,
            multilingual=multilingual,
            batch_size=batch_size,
            vad_filter=True,
            beam_size=5,
            # 要词级时间戳才能把 VAD 切出的整块语音重新切成字幕大小的条目
            word_timestamps=True,
            # 关掉「以上文为条件」：长视频里一旦出现幻觉会自我强化成复读，
            # 牺牲少量上下文连贯性换取稳定性。
            condition_on_previous_text=False,
        )

        duration = info.duration or 0.0
        results = []
        for seg in raw_segments:
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            results.extend(_to_cues(seg, info.language))
            if progress and duration:
                progress(min(seg.end / duration, 1.0))
        if progress:
            progress(1.0)
        return results

    def label_languages(
        self,
        audio,
        segments: list[Segment],
        window: float = 30.0,
        progress: Optional[Callable[[float], None]] = None,
        cancel: Optional[threading.Event] = None,
    ) -> list[Segment]:
        """逐段标注语种，用于一条音轨里多语言混说的情况。

        Whisper 的 ``Segment`` 不带语种字段（``multilingual=True`` 只在内部切换解码
        提示词），所以这里按 ~30 秒一组回看原始波形补测：组内各段共享同一语种。
        分组而非逐段检测是为了控制开销——检测一次要跑一遍编码器，
        而字幕段常常只有几秒。
        """
        for start, stop in _group_by_window(segments, window):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            clip = audio[
                int(segments[start].start * SAMPLE_RATE) : int(segments[stop - 1].end * SAMPLE_RATE)
            ]
            # 组内已确定是语音，无需再过 VAD
            language, _, _ = self.model.detect_language(audio=clip, vad_filter=False)
            for seg in segments[start:stop]:
                seg.language = language
            if progress:
                progress(min(stop / len(segments), 1.0))
        return segments


def _group_by_window(segments: list[Segment], window: float):
    """把相邻字幕段按累计时长切成不超过 ``window`` 秒的组，返回下标区间。"""
    start = 0
    while start < len(segments):
        stop = start + 1
        while stop < len(segments) and segments[stop].end - segments[start].start <= window:
            stop += 1
        yield start, stop
        start = stop


def _to_cues(raw, language: str) -> list[Segment]:
    """把一段识别结果切成字幕大小的条目。

    VAD 会把一整段连续语音（讲座、新闻）交给模型，出来就是一条 30 秒、几百字的
    结果，直接写进 SRT 没法看。这里按词级时间戳重新切分：优先断在停顿和句末标点上，
    再用时长/字数兜底。
    """
    if not raw.words:
        text = raw.text.strip()
        return [Segment(raw.start, raw.end, text, language)] if text else []

    limit = _CJK_CUE_CHARS if language in _WIDE_LANGUAGES else _LATIN_CUE_CHARS
    cues, buffer = [], []
    for index, word in enumerate(raw.words):
        buffer.append(word)
        following = raw.words[index + 1] if index + 1 < len(raw.words) else None
        if following is None:
            continue
        text = _join(buffer)
        if following.start - word.end > _PAUSE_BREAK or (
            text.endswith(_SENTENCE_ENDS) and len(text) >= _MIN_CUE_CHARS
        ):
            cues.append(_cue(buffer, language))
            buffer = []
        elif (
            len(text) + len(following.word) > limit
            or following.end - buffer[0].start > MAX_CUE_SECONDS
        ):
            cut = _limit_break(buffer)
            cues.append(_cue(buffer[:cut], language))
            buffer = buffer[cut:]
    if buffer:
        cues.append(_cue(buffer, language))
    return [cue for cue in cues if cue.text]


def _limit_break(words) -> int:
    """被字数/时长逼停时，回退到后半段最近的标点处断开。

    否则「…can do for you, ask what you can do for your | country.」会把最后一个词
    甩成单独一条字幕；回退到逗号则切成两条长度相当、语义完整的字幕。
    """
    for i in range(len(words) - 1, len(words) // 2 - 1, -1):
        if _join(words[: i + 1]).endswith(_CLAUSE_ENDS):
            return i + 1
    return len(words)


def _join(words) -> str:
    return "".join(word.word for word in words).strip()


def _cue(words, language) -> Segment:
    return Segment(words[0].start, words[-1].end, _join(words), language)
