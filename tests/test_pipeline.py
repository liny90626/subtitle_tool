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

    target, _ = _write(
        "/x/movie.mkv", cues, Options(**{**vars(base), "target_language": "zho_Hans"}), "en"
    )
    assert [os.path.basename(p) for p in target] == ["movie.zh.srt", "movie.zh.vtt"]

    bilingual, _ = _write(
        "/x/movie.mkv",
        cues,
        Options(**{**vars(base), "target_language": "zho_Hans", "layout": "bilingual"}),
        "en",
    )
    assert os.path.basename(bilingual[0]) == "movie.en-zh.srt"

    plain, _ = _write("/x/movie.mkv", cues, base, "en")
    assert os.path.basename(plain[0]) == "movie.en.srt"


def test_srt_gets_a_bom_but_vtt_does_not(tmp_path):
    cues = _build_cues([Segment(0, 1, "hi", "en")], None, "source")
    options = Options(output_dir=str(tmp_path), formats=("srt", "vtt"))
    (srt, vtt), _ = _write("/x/movie.mkv", cues, options, "en")
    # Windows 上不少播放器靠 BOM 认 UTF-8
    assert open(srt, "rb").read(3) == b"\xef\xbb\xbf"
    assert open(vtt, "rb").read(3) != b"\xef\xbb\xbf"


def test_same_name_subtitle_is_overwritten(tmp_path):
    cues = _build_cues([Segment(0, 1, "hi", "en")], None, "source")
    options = Options(output_dir=str(tmp_path), formats=("srt",))
    (tmp_path / "movie.en.srt").write_text("旧内容", encoding="utf-8")

    (srt,), replaced = _write("/x/movie.mkv", cues, options, "en")

    assert replaced == []  # 名字一样，直接被写没了，谈不上「替换掉另一个文件」
    assert "旧内容" not in open(srt, encoding="utf-8-sig").read()


def test_bilingual_output_replaces_the_previous_source_language(tmp_path):
    """上次识别成英语写了 movie.en-zh.srt，这次识别成日语——旧的那份不该留在原地。"""
    cues = _build_cues([Segment(0, 1, "hi", "ja")], ["你好"], "bilingual")
    options = Options(
        output_dir=str(tmp_path),
        target_language="zho_Hans",
        layout="bilingual",
        formats=("srt", "vtt"),
    )
    stale = [tmp_path / "movie.en-zh.srt", tmp_path / "movie.en-zh.vtt"]
    for path in stale:
        path.write_text("上一次识别错了的", encoding="utf-8")

    outputs, replaced = _write("/x/movie.mkv", cues, options, "ja")

    assert [os.path.basename(p) for p in outputs] == ["movie.ja-zh.srt", "movie.ja-zh.vtt"]
    assert sorted(replaced) == sorted(str(p) for p in stale)
    assert not any(p.exists() for p in stale)


def test_cleanup_never_touches_subtitles_it_did_not_name(tmp_path):
    """别处来的字幕拼不出本工具的文件名，一个都不该被碰。"""
    cues = _build_cues([Segment(0, 1, "hi", "ja")], ["你好"], "bilingual")
    options = Options(
        output_dir=str(tmp_path), target_language="zho_Hans", layout="bilingual", formats=("srt",)
    )
    others = [
        tmp_path / "movie.srt",  # 播放器默认加载的那份，没有语种后缀
        tmp_path / "movie.chs.srt",  # 别的工具的命名习惯
        tmp_path / "movie.zh.srt",  # 之前「只要译文」跑出来的
        tmp_path / "other.en-zh.srt",  # 另一个视频的
    ]
    for path in others:
        path.write_text("别动我", encoding="utf-8")

    _, replaced = _write("/x/movie.mkv", cues, options, "ja")

    assert replaced == []
    assert all(p.read_text(encoding="utf-8") == "别动我" for p in others)


def test_translated_subtitle_is_never_deleted_by_a_source_only_run(tmp_path):
    """movie.zh.srt 可能是译文也可能是原文，单看文件名分不清，所以一律不动。"""
    cues = _build_cues([Segment(0, 1, "hi", "en")], None, "source")
    options = Options(output_dir=str(tmp_path), formats=("srt",))
    translated = tmp_path / "movie.zh.srt"
    translated.write_text("等了半小时的译文", encoding="utf-8")

    _, replaced = _write("/x/movie.mkv", cues, options, "en")

    assert replaced == []
    assert translated.read_text(encoding="utf-8") == "等了半小时的译文"


@pytest.mark.parametrize("track", [-1, 5])
def test_out_of_range_track_fails_with_a_clear_message(track):
    from subtitle_tool.pipeline import Engine

    with pytest.raises(ValueError, match="音轨"):
        Engine().run(os.path.join(DATA, "jfk.flac"), Options(track_index=track))
