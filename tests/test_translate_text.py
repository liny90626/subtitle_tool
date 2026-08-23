import threading

import pytest

from subtitle_tool.errors import Cancelled
from subtitle_tool.translate import Translator, _clause_point, _localize, _split_sentences


def test_splits_on_sentence_end():
    assert _split_sentences("Hello there. How are you?") == ["Hello there.", "How are you?"]


def test_keeps_decimals_and_abbreviations_intact():
    # "3.5" 后面没有空白不算句末；"Dr." 太短会并回下一句
    assert _split_sentences("Dr. Smith released version 3.5 today. It works.") == [
        "Dr. Smith released version 3.5 today.",
        "It works.",
    ]


def test_cjk_sentence_end_needs_no_trailing_space():
    assert _split_sentences("所以我的同胞们。不要问国家能做什么！") == [
        "所以我的同胞们。",
        "不要问国家能做什么！",
    ]


def test_text_without_punctuation_stays_whole():
    assert _split_sentences("no punctuation at all") == ["no punctuation at all"]


def test_clause_point_picks_the_break_nearest_the_middle():
    text = "aaaa, bbbb, cccccccccccccccccccccccccc"
    assert text[: _clause_point(text)] == "aaaa, bbbb, "


def test_clause_point_is_none_without_clause_marks():
    assert _clause_point("no clause marks here") is None


def test_cjk_punctuation_is_widened_only_after_han():
    assert _localize("所以,我的同胞们.", "zho_Hans") == "所以，我的同胞们。"
    assert _localize("だから,私の同胞.", "jpn_Jpan") == "だから、私の同胞。"
    # 数字和缩写里的 ASCII 标点不能动
    assert _localize("版本 3.5 由 Dr. Smith 发布,今天上线.", "zho_Hans") == (
        "版本 3.5 由 Dr. Smith 发布，今天上线。"
    )
    # 非 CJK 目标语原样不动
    assert _localize("Hello, world.", "fra_Latn") == "Hello, world."


class _Fake(Translator):
    """不加载模型的替身，只用来验切批逻辑。"""

    def __init__(self):
        pass

    def _translate_batch(self, texts, source, target):
        return [f"<{text}>" for text in texts]


def test_length_sorted_batches_keep_the_original_order():
    # 按长度排序只是为了少算 padding，出来的顺序和条数必须和进去时一样
    sentences = ["a" * n for n in (5, 1, 9, 3, 7, 2)]
    seen = []
    result = _Fake()._translate_all(sentences, "x", "y", 2, seen.append, None)
    assert result == [f"<{s}>" for s in sentences]
    assert seen == sorted(seen) and seen[-1] == 1.0


def test_batches_really_are_grouped_by_length():
    batches = []

    class Spy(_Fake):
        def _translate_batch(self, texts, source, target):
            batches.append([len(t) for t in texts])
            return super()._translate_batch(texts, source, target)

    Spy()._translate_all(["a" * n for n in (9, 1, 8, 2)], "x", "y", 2, None, None)
    # 长短混着切批时每批都要补齐到最长那条，凑到一起就省下来了
    assert batches == [[1, 2], [8, 9]]


def test_cancelling_stops_between_batches():
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        _Fake()._translate_all(["a", "b"], "x", "y", 2, None, cancel)
