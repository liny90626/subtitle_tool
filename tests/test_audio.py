import os

import pytest
from conftest import DATA

from subtitle_tool.audio import SAMPLE_RATE, decode_track, probe_tracks

MULTITRACK = os.path.join(DATA, "multitrack.mkv")


def test_probes_single_track_file():
    tracks = probe_tracks(os.path.join(DATA, "jfk.flac"))
    assert len(tracks) == 1
    assert tracks[0].codec == "flac"


@pytest.mark.skipif(not os.path.exists(MULTITRACK), reason="需先运行 scripts/make_fixture.py")
def test_probes_every_track_and_reads_language_tag():
    tracks = probe_tracks(MULTITRACK)
    assert len(tracks) == 2
    assert tracks[0].language_tag == "eng"
    assert "英语" in tracks[0].label


def test_decodes_to_16k_mono_int16():
    # 整轨用 int16 存：两个多小时的片子这就是 0.28GB 与 0.56GB 的差别，
    # 模型要的 float32 在窗口边界上按需转
    audio = decode_track(os.path.join(DATA, "jfk.flac"))
    assert audio.dtype.name == "int16"
    assert audio.ndim == 1
    assert 10.5 < len(audio) / SAMPLE_RATE < 11.5


def test_decoded_samples_convert_to_the_range_the_model_wants():
    from subtitle_tool.asr import _to_float

    audio = _to_float(decode_track(os.path.join(DATA, "jfk.flac")))
    assert audio.dtype.name == "float32"
    assert 0.05 < abs(audio).max() <= 1.0  # 有声音，且没有溢出


def test_no_capacity_is_left_dangling_behind_the_result():
    # 预开的那块如果比实际长很多，切片会把整块内存吊住
    audio = decode_track(os.path.join(DATA, "jfk.flac"))
    owner = audio.base if audio.base is not None else audio
    assert owner.size <= len(audio) * 1.1


@pytest.mark.skipif(not os.path.exists(MULTITRACK), reason="需先运行 scripts/make_fixture.py")
def test_selects_the_requested_track():
    # 两条音轨内容不同，选轨生效的话解出的波形也应不同
    first = decode_track(MULTITRACK, 0)
    second = decode_track(MULTITRACK, 1)
    assert len(first) != len(second) or not (first[:16000] == second[:16000]).all()


def test_reports_decode_progress_monotonically():
    seen = []
    decode_track(os.path.join(DATA, "jfk.flac"), progress=seen.append)
    assert seen[-1] == 1.0
    assert seen == sorted(seen)


def test_missing_track_fails_loudly():
    with pytest.raises(ValueError, match="音轨"):
        decode_track(os.path.join(DATA, "jfk.flac"), 5)


def test_growing_the_buffer_keeps_what_was_already_decoded():
    """容器不报时长时预开的块会不够用，扩容不能把已解出的样本弄丢。"""
    import numpy as np

    from subtitle_tool.audio import _grow

    buffer = np.arange(10, dtype=np.int16)
    bigger = _grow(buffer, 4, 12)
    assert bigger.size >= 12
    assert list(bigger[:4]) == [0, 1, 2, 3]


def test_memory_warning_fires_when_it_would_not_fit(monkeypatch):
    """内存眼看不够时要提前说，别让用户对着一次静默退出发呆。"""
    from subtitle_tool import runtime

    monkeypatch.setattr(runtime, "available_memory", lambda: 0.4)
    seen = []
    assert runtime.warn_if_memory_is_tight("small", 157 * 60, lambda m, f: seen.append(m))
    assert "0.4GB" in seen[0]

    monkeypatch.setattr(runtime, "available_memory", lambda: 12.0)
    assert not runtime.warn_if_memory_is_tight("small", 157 * 60, None)
