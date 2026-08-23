from subtitle_tool.subtitles import Cue, render, stretch_cues


def test_srt_numbering_and_timestamps():
    out = render([Cue(0, 1.5, "hello"), Cue(2, 3.25, "world")], "srt")
    assert "1\n00:00:00,000 --> 00:00:01,500\nhello" in out
    assert "2\n00:00:02,000 --> 00:00:03,250\nworld" in out


def test_vtt_uses_dot_separator_and_header():
    out = render([Cue(0, 1, "hi")], "vtt")
    assert out.startswith("WEBVTT")
    assert "00:00:00.000 --> 00:00:01.000" in out


def test_hour_overflow():
    assert "01:01:01,001" in render([Cue(3661.001, 3662, "x")], "srt")


def test_zero_length_cue_gets_visible_duration():
    # 时间轴倒挂/零长的字幕会被播放器直接跳过
    assert "00:00:05,000 --> 00:00:05,100" in render([Cue(5, 5, "x")], "srt")


def test_long_latin_line_wraps_at_space():
    text = "And so my fellow Americans ask not what your country can do for you today"
    body = render([Cue(0, 5, text)], "srt").splitlines()
    lines = body[2:4]
    assert len(lines) == 2 and all(len(line) <= 42 for line in lines)
    assert " ".join(lines) == text


def test_cjk_line_breaks_after_punctuation():
    text = "所以我的同胞们，不要问你们的国家能为你们做些什么。"
    lines = render([Cue(0, 5, text)], "srt").splitlines()[2:4]
    assert lines[0].endswith("，")


def test_bilingual_wraps_each_language_separately():
    lines = render([Cue(0, 5, "Hello there\n你好呀")], "srt").splitlines()
    assert lines[2:4] == ["Hello there", "你好呀"]


def test_txt_drops_timing_and_flattens():
    assert render([Cue(0, 1, "a\nb"), Cue(1, 2, "c")], "txt") == "a b\nc\n"


def test_stretch_respects_next_cue_start():
    cues = stretch_cues([Cue(0, 0.4, "a"), Cue(1.5, 1.9, "b"), Cue(2.0, 5.0, "c")])
    assert cues[0].end == 1.2  # 延长到最短时长
    assert cues[1].end == 2.0  # 被下一条挡住，不重叠
    assert cues[2].end == 5.0  # 本来就够长，不动
