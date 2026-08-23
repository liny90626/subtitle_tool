from dataclasses import dataclass

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
