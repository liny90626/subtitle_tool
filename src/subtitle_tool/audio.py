"""音轨探测与解码。

依赖 PyAV（faster-whisper 的传递依赖，wheel 内置 FFmpeg 库），因此不需要用户
另外安装 ffmpeg.exe。faster-whisper 自带的 ``decode_audio`` 写死了第 0 条音轨，
这里自行实现以支持多音轨视频的按轨选择，其余帧处理沿用其经过验证的做法。
"""

import gc
import io
import itertools
from dataclasses import dataclass
from typing import Callable, Optional

import av
import numpy as np

from .languages import describe_tag

SAMPLE_RATE = 16000


@dataclass
class AudioTrack:
    """视频容器里的一条音轨。"""

    index: int  #: 在全部音轨中的序号，供 decode_track 选轨
    stream_index: int  #: 容器内的绝对流序号，仅用于展示
    codec: str
    channels: int
    sample_rate: int
    duration: float  #: 秒
    language_tag: Optional[str]  #: 容器标注的 ISO 639-2 语言码，未标注为 None
    title: Optional[str]

    @property
    def label(self) -> str:
        """下拉框里显示的一行描述。"""
        parts = [f"音轨 {self.index + 1}"]
        named = describe_tag(self.language_tag)
        if named:
            parts.append(named)
        elif self.language_tag:
            parts.append(self.language_tag)
        if self.title:
            parts.append(self.title)
        parts.append(f"{self.codec} {self.channels}ch {self.sample_rate}Hz")
        return " · ".join(parts)


def probe_tracks(path: str) -> list[AudioTrack]:
    """列出媒体文件的全部音轨。无音轨时返回空列表。"""
    with av.open(path, mode="r", metadata_errors="ignore") as container:
        return [_describe(container, i, s) for i, s in enumerate(container.streams.audio)]


def _describe(container, index, stream) -> AudioTrack:
    duration = 0.0
    if stream.duration is not None and stream.time_base:
        duration = float(stream.duration * stream.time_base)
    elif container.duration is not None:
        duration = container.duration / av.time_base
    return AudioTrack(
        index=index,
        stream_index=stream.index,
        codec=stream.codec_context.name,
        channels=stream.codec_context.channels or 0,
        sample_rate=stream.codec_context.sample_rate or 0,
        duration=duration,
        language_tag=stream.metadata.get("language"),
        title=stream.metadata.get("title"),
    )


def decode_track(
    path: str,
    track_index: int = 0,
    progress: Optional[Callable[[float], None]] = None,
) -> np.ndarray:
    """把指定音轨解码为 16kHz 单声道 float32 波形。

    ``progress`` 收到 0.0~1.0 的解码进度。返回的数组即 Whisper 的输入格式。
    """
    resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
    raw = io.BytesIO()
    dtype = None

    with av.open(path, mode="r", metadata_errors="ignore") as container:
        streams = container.streams.audio
        if track_index >= len(streams):
            raise ValueError(f"{path} 只有 {len(streams)} 条音轨，无法选择第 {track_index + 1} 条")
        stream = streams[track_index]
        stream.thread_type = "AUTO"
        total = float(stream.duration * stream.time_base) if stream.duration else 0.0

        frames = _skip_invalid(container.decode(stream))
        frames = _report(frames, total, progress)
        frames = _group(frames, 500000)
        for frame in _resample(frames, resampler):
            array = frame.to_ndarray()
            dtype = array.dtype
            raw.write(array)

    # 重采样器持有的缓冲不手动 GC 不会释放，长视频批处理时会累积
    # 见 https://github.com/SYSTRAN/faster-whisper/issues/390
    del resampler
    gc.collect()

    if progress:
        progress(1.0)
    if dtype is None:
        raise ValueError(f"{path} 第 {track_index + 1} 条音轨没有解出任何音频数据")
    return np.frombuffer(raw.getbuffer(), dtype=dtype).astype(np.float32) / 32768.0


def _skip_invalid(frames):
    """跳过损坏帧——网络下载/录制的视频常有局部损坏。"""
    iterator = iter(frames)
    while True:
        try:
            yield next(iterator)
        except StopIteration:
            return
        except av.error.InvalidDataError:
            continue


def _report(frames, total, progress):
    """在丢弃 pts 之前按帧时间戳汇报进度。"""
    for frame in frames:
        if progress and total and frame.time is not None:
            progress(min(frame.time / total, 1.0))
        yield frame


def _group(frames, num_samples):
    """攒够一批再重采样，减少调用次数。"""
    fifo = av.audio.fifo.AudioFifo()
    for frame in frames:
        frame.pts = None  # 时间戳跳变的容器很常见，交给 FIFO 按顺序拼接
        fifo.write(frame)
        if fifo.samples >= num_samples:
            yield fifo.read()
    if fifo.samples > 0:
        yield fifo.read()


def _resample(frames, resampler):
    for frame in itertools.chain(frames, [None]):  # None 用于冲出重采样器缓冲
        yield from resampler.resample(frame)
