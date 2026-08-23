"""语音识别：faster-whisper(CTranslate2) 封装。

选型理由见 docs/design.md：相同精度下比 openai-whisper 快约 4 倍、显存/内存占用更低，
且不依赖 PyTorch，Windows 打包体积可控。
"""

import threading
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

import ctranslate2
from faster_whisper import BatchedInferencePipeline, WhisperModel

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


class Cancelled(Exception):
    """用户中途取消任务。"""


@dataclass
class Segment:
    """一条字幕对应的识别结果。"""

    start: float
    end: float
    text: str
    language: Optional[str] = None  #: 该段的语种；多语种模式下逐段可能不同


def pick_device(preference: str = "auto") -> Tuple[str, str]:
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

    def detect_language(self, audio, segments: int = 8) -> Tuple[str, float]:
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
    ) -> List[Segment]:
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
            # 关掉「以上文为条件」：长视频里一旦出现幻觉会自我强化成复读，
            # 牺牲少量上下文连贯性换取稳定性。
            condition_on_previous_text=False,
        )

        duration = info.duration or 0.0
        results = []
        for seg in raw_segments:
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            text = seg.text.strip()
            if text:
                results.append(
                    Segment(
                        start=seg.start,
                        end=seg.end,
                        text=text,
                        language=getattr(seg, "language", None) or info.language,
                    )
                )
            if progress and duration:
                progress(min(seg.end / duration, 1.0))
        if progress:
            progress(1.0)
        return results
