"""任务编排：从视频文件到字幕文件的完整流程。"""

import os
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import runtime
from .asr import Transcriber, default_model
from .audio import AudioTrack, decode_track, probe_tracks
from .i18n import t
from .languages import describe_whisper, flores_of, short_code
from .subtitles import Cue, render, stretch_cues
from .translate import DEFAULT_MODEL as DEFAULT_TRANSLATE_MODEL
from .translate import Translator

#: 字幕排版方式
LAYOUTS = ("target", "source", "bilingual")


@dataclass
class Options:
    """单次任务的参数。"""

    track_index: int = 0
    source_language: Optional[str] = None  #: Whisper 码；None 表示自动识别
    multi_language: bool = False  #: 一条音轨里多语言混说时逐段识别语种
    target_language: Optional[str] = None  #: FLORES 码；None 表示不翻译
    layout: str = "target"
    formats: Sequence[str] = ("srt",)
    output_dir: Optional[str] = None  #: None 表示与视频同目录


@dataclass
class Result:
    """任务产物。"""

    source_path: str
    track: AudioTrack
    source_language: str  #: 主语种（Whisper 码）
    language_spans: list[tuple[float, float, str]] = field(default_factory=list)
    cues: list[Cue] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)


class Engine:
    """持有已加载的模型，跨任务复用以省去重复加载。"""

    def __init__(
        self,
        model_size: Optional[str] = None,
        device: str = "auto",
        translate_model: str = DEFAULT_TRANSLATE_MODEL,
        download_root: Optional[str] = None,
        notify: Optional[Callable[[str], None]] = None,
    ):
        self.device = device
        self.model_size = model_size or default_model(device)
        self.translate_model = translate_model
        self.download_root = download_root
        #: 首次下载模型这类「要等很久」的事情通过它告诉用户，None 表示不报
        self.notify = notify
        #: 本次 run() 的取消信号。模型是用到才加载的，几百 MB 的下载也得能中断
        self._cancel = None
        #: (窗口秒数, 批大小)。上一次跑崩了之后由外面写死成更保守的一档，不再自动挑
        self.force_profile = None
        self._transcriber = None
        self._translator = None

    @property
    def transcriber(self) -> Transcriber:
        if self._transcriber is None:
            self._transcriber = Transcriber(
                self.model_size, self.device, self.download_root, self.notify, self._cancel
            )
        return self._transcriber

    @property
    def translator(self) -> Translator:
        if self._translator is None:
            self._translator = Translator(
                self.translate_model, self.device, self.download_root, self.notify, self._cancel
            )
        return self._translator

    def run(
        self,
        path: str,
        options: Options,
        progress: Optional[Callable[[str, float], None]] = None,
        cancel=None,
    ) -> Result:
        """跑完整条流水线并写出字幕文件。

        内存不够时抛 :class:`MemoryError`，消息是给用户看的中文——上层照常当一条普通
        错误显示，不该让它演变成一次静默退出。
        """
        try:
            return self._run(path, options, progress, cancel)
        except MemoryError as error:
            message = str(error) or runtime.out_of_memory_message()
            runtime.trace(f"内存不足：{message}")
            raise MemoryError(message) from None

    def _run(
        self,
        path: str,
        options: Options,
        progress: Optional[Callable[[str, float], None]] = None,
        cancel=None,
    ) -> Result:
        self._cancel = cancel
        name = os.path.basename(path)
        tracks = probe_tracks(path)
        if not tracks:
            raise ValueError(t("{name} 里没有音轨，无法生成字幕", name=name))
        if not 0 <= options.track_index < len(tracks):
            raise ValueError(
                t(
                    "{name} 只有 {total} 条音轨，没有第 {wanted} 条",
                    name=name,
                    total=len(tracks),
                    wanted=options.track_index + 1,
                )
            )
        track = tracks[options.track_index]
        reporter = _Reporter(_plan(options), progress)
        runtime.trace(
            f"开始处理 {name}（音轨 {options.track_index + 1}/{len(tracks)}，"
            f"{track.duration / 60:.1f} 分钟）{runtime.memory_note()}"
        )

        audio = decode_track(path, options.track_index, reporter.stage("解码音轨"))
        runtime.trace(f"解码完成 {len(audio) / 16000 / 60:.1f} 分钟 {runtime.memory_note()}")

        source = options.source_language
        if source is None:
            source, _ = self.transcriber.detect_language(audio)
            reporter.done("识别语种")

        if self.force_profile:
            (window, batch), note = self.force_profile, None
        else:
            window, batch, note = runtime.plan_transcription(self.model_size, len(audio) / 16000)
        if note:
            runtime.trace(note)
            if self.notify:
                self.notify(note, None)
        if window is None:
            # 连最省的档位都摆不下。与其冲进去让原生层把整个进程干掉，不如好好说一句
            raise MemoryError(note)

        runtime.trace(f"转写开始，语种 {source}，窗口 {window:.0f}s 批 {batch}")
        segments = self.transcriber.transcribe(
            audio,
            # 多语种模式交给模型逐窗口重判，不锁定语种
            language=None if options.multi_language else source,
            multilingual=options.multi_language,
            batch_size=batch,
            progress=reporter.stage("语音转写"),
            cancel=cancel,
            window_seconds=window,
        )
        if not segments:
            # 只有音乐/环境音的音轨会走到这里。写个空字幕文件出去等于让用户白等，直接报错。
            raise ValueError(
                t(
                    "{name} 的第 {number} 条音轨里没有检测到语音",
                    name=name,
                    number=options.track_index + 1,
                )
            )
        for seg in segments:
            seg.language = seg.language or source

        if options.multi_language:
            self.transcriber.label_languages(
                audio, segments, progress=reporter.stage("标注语种"), cancel=cancel
            )

        translations = None
        if options.target_language:
            translations = self._translate(
                segments, options.target_language, reporter.stage("翻译字幕"), cancel
            )

        cues = _build_cues(segments, translations, options.layout)
        outputs = _write(path, cues, options, source)
        reporter.done("写出文件")
        runtime.trace(f"完成 {name}，{len(cues)} 条字幕")
        return Result(path, track, source, _spans(segments), cues, outputs)

    def _translate(self, segments, target, progress, cancel):
        """按源语种分组翻译——多语种音轨里每组的源语言码不同。"""
        groups = defaultdict(list)
        for i, seg in enumerate(segments):
            groups[seg.language].append(i)

        results = [""] * len(segments)
        finished = 0
        for language, indexes in groups.items():
            source = flores_of(language)
            if source is None:
                raise ValueError(
                    t("翻译模型不支持源语种 {language}", language=describe_whisper(language))
                )
            texts = self.translator.translate(
                [segments[i].text for i in indexes], source, target, cancel=cancel
            )
            for i, text in zip(indexes, texts):
                results[i] = text
            finished += len(indexes)
            if progress:
                progress(finished / len(segments))
        return results


def _plan(options: Options) -> list[tuple[str, float]]:
    """按本次任务实际会跑的阶段给出进度权重，权重是各阶段耗时的经验占比。"""
    stages = [("解码音轨", 8.0)]
    if options.source_language is None:
        stages.append(("识别语种", 2.0))
    stages.append(("语音转写", 60.0))
    if options.multi_language:
        stages.append(("标注语种", 10.0))
    if options.target_language:
        stages.append(("翻译字幕", 30.0))
    stages.append(("写出文件", 1.0))
    return stages


class _Reporter:
    """把各阶段的局部进度折算成整体百分比。"""

    #: 进度至少推进这么多才回调一次——解码是逐帧回调的，不节流会打爆 UI 事件队列
    STEP = 0.005

    def __init__(self, stages, callback):
        self.callback = callback
        self.last = -1.0
        total = sum(weight for _, weight in stages)
        self.weights = {label: weight / total for label, weight in stages}
        self.offsets = {}
        offset = 0.0
        for label, weight in stages:
            self.offsets[label] = offset
            offset += weight / total

    def stage(self, label):
        if self.callback is None:
            return None

        def report(fraction):
            self._emit(label, self.offsets[label] + self.weights[label] * fraction)

        return report

    def done(self, label):
        if self.callback:
            self._emit(label, self.offsets[label] + self.weights[label], force=True)

    def _emit(self, label, overall, force=False):
        if force or overall >= self.last + self.STEP:
            self.last = overall
            self.callback(label, overall)


def _build_cues(segments, translations, layout) -> list[Cue]:
    if translations is None:
        layout = "source"
    cues = []
    for i, seg in enumerate(segments):
        if layout == "source":
            text = seg.text
        elif layout == "target":
            text = translations[i]
        else:
            text = f"{seg.text}\n{translations[i]}"
        cues.append(Cue(seg.start, seg.end, text))
    return stretch_cues(cues)


def _write(path, cues, options: Options, source) -> list[str]:
    directory = options.output_dir or os.path.dirname(os.path.abspath(path))
    stem = os.path.splitext(os.path.basename(path))[0]
    target = short_code(options.target_language) if options.target_language else None
    if target is None or options.layout == "source":
        tag = source
    elif options.layout == "bilingual":
        tag = f"{source}-{target}"
    else:
        tag = target

    os.makedirs(directory, exist_ok=True)
    outputs = []
    for fmt in options.formats:
        out = os.path.join(directory, f"{stem}.{tag}.{fmt}")
        # SRT 带 BOM：Windows 上不少播放器靠它才认出 UTF-8，否则中文变乱码。
        # VTT/TXT 不带，避免严格解析器把 BOM 当正文首字符。
        encoding = "utf-8-sig" if fmt == "srt" else "utf-8"
        with open(out, "w", encoding=encoding, newline="\n") as handle:
            handle.write(render(cues, fmt))
        outputs.append(out)
    return outputs


def _spans(segments) -> list[tuple[float, float, str]]:
    """合并相邻同语种的段，得到语言时间轴。"""
    spans = []
    for seg in segments:
        if spans and spans[-1][2] == seg.language:
            spans[-1] = (spans[-1][0], seg.end, seg.language)
        else:
            spans.append((seg.start, seg.end, seg.language))
    return spans
