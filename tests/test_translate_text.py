from subtitle_tool.translate import _clause_point, _localize, _split_sentences


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
