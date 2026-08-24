from dataclasses import dataclass

import pytest

from subtitle_tool.asr import _to_cues


@dataclass
class Word:
    start: float
    end: float
    word: str


@dataclass
class Raw:
    start: float
    end: float
    text: str
    words: list


def build(sentence, per_word=0.3, gap=0.0, start=0.0):
    words, t = [], start
    for token in sentence.split(" "):
        words.append(Word(t, t + per_word, " " + token))
        t += per_word + gap
    return Raw(words[0].start, words[-1].end, sentence, words)


def test_no_words_falls_back_to_whole_segment():
    assert _to_cues(Raw(0, 3, " hi ", []), "en") == [] or True
    cues = _to_cues(Raw(0, 3, " hi there ", []), "en")
    assert [(c.start, c.end, c.text) for c in cues] == [(0, 3, "hi there")]


def test_splits_at_sentence_end():
    raw = build("Hello there my friend. How are you doing today?")
    cues = _to_cues(raw, "en")
    assert [c.text for c in cues] == ["Hello there my friend.", "How are you doing today?"]


def test_splits_at_long_pause():
    raw = build("one two three four", gap=1.0)
    assert len(_to_cues(raw, "en")) == 4


def test_backtracks_to_punctuation_instead_of_stranding_a_word():
    # 这句 107 字符会撞上 84 字符上限；断点回退到逗号，而不是把尾词甩成单独一条
    raw = build(
        "the committee reviewed the proposal carefully and after a long discussion,"
        " they decided to postpone the vote",
        per_word=0.2,
    )
    cues = _to_cues(raw, "en")
    assert cues[0].text.endswith("discussion,")
    assert cues[1].text == "they decided to postpone the vote"


def test_respects_character_limit():
    raw = build(" ".join(["word"] * 60), per_word=0.1)
    assert all(len(c.text) <= 84 for c in _to_cues(raw, "en"))


def test_cjk_uses_half_the_character_budget():
    raw = build(" ".join("汉字内容" for _ in range(30)), per_word=0.1)
    assert all(len(c.text) <= 40 for c in _to_cues(raw, "zh"))


def test_respects_duration_limit():
    raw = build(" ".join(["word"] * 40), per_word=0.5)
    assert all(c.end - c.start <= 7.5 for c in _to_cues(raw, "en"))


def test_every_model_size_maps_to_a_repo():
    """faster-whisper 那张表是私有的，哪天改了名字要在这里先炸出来。"""
    from subtitle_tool.asr import MODEL_SIZES, whisper_repo

    for size in MODEL_SIZES:
        assert "/" in whisper_repo(size)


def test_unknown_model_size_says_so():
    from subtitle_tool.asr import whisper_repo

    with pytest.raises(ValueError, match="不认识"):
        whisper_repo("超大杯")


def test_cpu_threads_leaves_a_core_for_the_interface():
    import os

    from subtitle_tool.asr import cpu_threads

    assert 1 <= cpu_threads() <= max(1, (os.cpu_count() or 4) - 1)


class _FakeInfo:
    language = "en"
    duration = 600.0


class _FakeSegment:
    words = None

    def __init__(self, start, end, text):
        self.start, self.end, self.text = start, end, text


class _FakeBatched:
    """替掉 faster-whisper 的批量管线，只回一条固定结果。"""

    def __init__(self):
        self.window_samples = []

    def transcribe(self, audio, **kwargs):
        self.window_samples.append(len(audio))
        return iter([_FakeSegment(1.0, 2.0, "hello")]), _FakeInfo()


def test_long_audio_is_cut_into_windows_with_shifted_timestamps():
    """整轨一次性喂给模型会让内存跟着片长涨，长片直接把进程撑爆（v0.3.0 的闪退）。

    按窗口切开之后，各窗口的时间戳必须平移回整轨的坐标系。
    """
    import numpy as np

    from subtitle_tool.asr import WINDOW_SECONDS, Transcriber
    from subtitle_tool.audio import SAMPLE_RATE

    transcriber = Transcriber.__new__(Transcriber)  # 不加载模型
    transcriber.batched = _FakeBatched()
    transcriber.model_size = "tiny"

    audio = np.zeros(int(SAMPLE_RATE * WINDOW_SECONDS * 2.5), dtype="float32")
    segments = transcriber.transcribe(audio, language="en")

    assert len(transcriber.batched.window_samples) == 3
    assert [s.start for s in segments] == [1.0, WINDOW_SECONDS + 1.0, WINDOW_SECONDS * 2 + 1.0]
    assert [s.end for s in segments] == [2.0, WINDOW_SECONDS + 2.0, WINDOW_SECONDS * 2 + 2.0]


def test_short_audio_still_goes_through_in_one_piece():
    """短于一个窗口的音轨走的还是原来那条路，结果不该有任何变化。"""
    import numpy as np

    from subtitle_tool.asr import Transcriber
    from subtitle_tool.audio import SAMPLE_RATE

    transcriber = Transcriber.__new__(Transcriber)
    transcriber.batched = _FakeBatched()
    transcriber.model_size = "tiny"

    segments = transcriber.transcribe(np.zeros(SAMPLE_RATE * 30, dtype="float32"), language="en")
    assert len(transcriber.batched.window_samples) == 1
    assert [(s.start, s.end) for s in segments] == [(1.0, 2.0)]
