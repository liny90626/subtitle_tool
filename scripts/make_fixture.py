"""生成多音轨测试视频：一路黑场视频 + 两条不同语言的音轨。

真实的多语言片源不便入库，用现成的公共领域语音素材拼一个最小样本，
用于验证「探测音轨 / 按轨解码 / 逐轨识别语种」这条链路。
"""

import sys
from fractions import Fraction

import av
import numpy as np

sys.path.insert(0, "src")
from subtitle_tool.audio import SAMPLE_RATE, decode_track

SOURCES = [("tests/data/jfk.flac", "eng"), ("tests/data/multilingual.mp3", "mul")]
OUTPUT = "tests/data/multitrack.mkv"


def main():
    waves = [decode_track(path) for path, _ in SOURCES]
    duration = max(len(w) for w in waves) / SAMPLE_RATE

    with av.open(OUTPUT, mode="w") as container:
        video = container.add_stream("libx264", rate=1)
        video.width, video.height, video.pix_fmt = 320, 180, "yuv420p"

        streams = []
        for (_, tag), wave in zip(SOURCES, waves):
            stream = container.add_stream("aac", rate=SAMPLE_RATE)
            stream.layout = "mono"
            stream.metadata["language"] = tag
            streams.append((stream, wave))

        for i in range(int(duration) + 1):
            frame = av.VideoFrame.from_ndarray(
                np.zeros((180, 320, 3), dtype=np.uint8), format="rgb24"
            )
            frame.pts = i
            frame.time_base = Fraction(1, 1)
            container.mux(video.encode(frame))
        container.mux(video.encode(None))

        for stream, wave in streams:
            for offset in range(0, len(wave), 1024):
                chunk = wave[offset : offset + 1024]
                samples = (chunk * 32768.0).astype(np.int16).reshape(1, -1)
                frame = av.AudioFrame.from_ndarray(samples, format="s16", layout="mono")
                frame.sample_rate = SAMPLE_RATE
                frame.pts = offset
                frame.time_base = Fraction(1, SAMPLE_RATE)
                container.mux(stream.encode(frame))
            container.mux(stream.encode(None))

    print(f"已生成 {OUTPUT}")


if __name__ == "__main__":
    main()
