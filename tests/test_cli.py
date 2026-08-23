import os

from conftest import DATA

from subtitle_tool.cli import main


def test_no_arguments_prints_help_and_fails(capsys):
    assert main([]) == 2
    assert "usage" in capsys.readouterr().out


def test_list_languages(capsys):
    assert main(["--list-languages"]) == 0
    out = capsys.readouterr().out
    assert "zho_Hans" in out and "中文（简体）" in out


def test_list_tracks(capsys):
    assert main(["--list-tracks", os.path.join(DATA, "jfk.flac")]) == 0
    assert "音轨 1" in capsys.readouterr().out


def test_unknown_target_language_is_rejected(capsys):
    assert main(["x.mp4", "--target", "克林贡语"]) == 2
    assert "无法识别的目标语种" in capsys.readouterr().err


def test_unknown_format_is_rejected(capsys):
    assert main(["x.mp4", "--format", "srt,doc"]) == 2
    assert "doc" in capsys.readouterr().err


def test_target_accepts_short_code_and_chinese_name():
    # 解析成功就会往下走到模型加载，这里只验证不会在参数校验阶段被拒
    from subtitle_tool.languages import resolve_target

    assert resolve_target("zh") == resolve_target("中文（简体）") == "zho_Hans"
