import os

import pytest
from conftest import DATA

from subtitle_tool.asr import Segment
from subtitle_tool.pipeline import Options, _build_cues, _plan, _Reporter, _spans, _write


def test_plan_only_includes_stages_that_will_run():
    minimal = [label for label, _ in _plan(Options(source_language="en"))]
    assert minimal == ["解码音轨", "语音转写", "写出文件"]
    full = [label for label, _ in _plan(Options(multi_language=True, target_language="zho_Hans"))]
    assert full == ["解码音轨", "识别语种", "语音转写", "标注语种", "翻译字幕", "写出文件"]


def test_reporter_is_monotonic_and_ends_at_one():
    seen = []
    options = Options(multi_language=True, target_language="zho_Hans")
    reporter = _Reporter(_plan(options), lambda stage, fraction: seen.append(fraction))
    for label, _ in _plan(options):
        reporter.stage(label)(0.5)
        reporter.done(label)
    values = [f for f in seen]
    assert values == sorted(values)
    assert values[-1] == pytest.approx(1.0)


def test_reporter_throttles_tiny_steps():
    seen = []
    reporter = _Reporter([("解码音轨", 1.0)], lambda stage, fraction: seen.append(fraction))
    report = reporter.stage("解码音轨")
    for i in range(1000):
        report(i / 1000)
    # 逐帧回调会打爆界面事件队列，必须按步进节流
    assert len(seen) < 250


def test_spans_merge_adjacent_same_language():
    segments = [
        Segment(0, 1, "a", "en"),
        Segment(1, 2, "b", "en"),
        Segment(2, 3, "c", "de"),
        Segment(3, 4, "d", "en"),
    ]
    assert _spans(segments) == [(0, 2, "en"), (2, 3, "de"), (3, 4, "en")]


def test_layouts_pick_the_right_text():
    segments = [Segment(0, 1, "hello", "en")]
    assert _build_cues(segments, ["你好"], "target")[0].text == "你好"
    assert _build_cues(segments, ["你好"], "source")[0].text == "hello"
    assert _build_cues(segments, ["你好"], "bilingual")[0].text == "hello\n你好"
    # 没翻译时无论选什么排版都只能出原文
    assert _build_cues(segments, None, "bilingual")[0].text == "hello"


def test_output_filenames_encode_the_languages(tmp_path):
    cues = _build_cues([Segment(0, 1, "hi", "en")], ["你好"], "target")
    base = Options(output_dir=str(tmp_path), formats=("srt", "vtt"))

    target = _write(
        "/x/movie.mkv", cues, Options(**{**vars(base), "target_language": "zho_Hans"}), "en"
    )
    assert [os.path.basename(p) for p in target] == ["movie.zh.srt", "movie.zh.vtt"]

    bilingual = _write(
        "/x/movie.mkv",
        cues,
        Options(**{**vars(base), "target_language": "zho_Hans", "layout": "bilingual"}),
        "en",
    )
    assert os.path.basename(bilingual[0]) == "movie.en-zh.srt"

    plain = _write("/x/movie.mkv", cues, base, "en")
    assert os.path.basename(plain[0]) == "movie.en.srt"


def test_srt_gets_a_bom_but_vtt_does_not(tmp_path):
    cues = _build_cues([Segment(0, 1, "hi", "en")], None, "source")
    options = Options(output_dir=str(tmp_path), formats=("srt", "vtt"))
    srt, vtt = _write("/x/movie.mkv", cues, options, "en")
    # Windows 上不少播放器靠 BOM 认 UTF-8
    assert open(srt, "rb").read(3) == b"\xef\xbb\xbf"
    assert open(vtt, "rb").read(3) != b"\xef\xbb\xbf"


@pytest.mark.parametrize("track", [-1, 5])
def test_out_of_range_track_fails_with_a_clear_message(track):
    from subtitle_tool.pipeline import Engine

    with pytest.raises(ValueError, match="音轨"):
        Engine().run(os.path.join(DATA, "jfk.flac"), Options(track_index=track))
