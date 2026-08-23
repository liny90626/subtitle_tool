import ast
import pathlib
from string import Formatter

import pytest

from subtitle_tool import gui, i18n
from subtitle_tool.i18n import _ENGLISH
from subtitle_tool.pipeline import Options, _plan

SOURCE = pathlib.Path(__file__).resolve().parents[1] / "src" / "subtitle_tool"
#: 这些函数的某个参数是「要翻译的中文原文」
TRANSLATED_ARGUMENT = {"t": 0, "_label": 0, "_text": 1, "_set_status": 1}


def _sources() -> list[str]:
    """源码里所有等着被翻译的中文原文。"""
    found = []
    for path in sorted(SOURCE.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            index = TRANSLATED_ARGUMENT.get(name)
            if index is None or len(node.args) <= index:
                continue
            argument = node.args[index]
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                found.append(argument.value)
    # 下拉框选项和阶段名是先存成表、显示时才翻的，扫不到调用点
    for table in (gui.LAYOUT_CHOICES, gui.DEVICE_CHOICES, gui.SOURCE_CHOICES):
        found += [label for label, _ in table]
    found += [label for label, _ in _plan(Options(multi_language=True, target_language="zho_Hans"))]
    return found


def _has_chinese(text: str) -> bool:
    return any("一" <= char <= "鿿" for char in text)


def _fields(text: str) -> set:
    return {name for _, name, _, _ in Formatter().parse(text) if name}


@pytest.fixture(autouse=True)
def restore_language():
    yield
    i18n.use("zh")


# ---------- 取文案 ----------


def test_chinese_is_returned_as_is():
    i18n.use("zh")
    assert i18n.t("开始生成") == "开始生成"


def test_english_comes_from_the_catalog():
    i18n.use("en")
    assert i18n.t("开始生成") == "Start"


def test_untranslated_text_falls_back_to_chinese():
    i18n.use("en")
    assert i18n.t("这句没有翻译") == "这句没有翻译"


def test_placeholders_are_filled_in_both_languages():
    i18n.use("zh")
    assert i18n.t("载入模型 {model}…", model="small") == "载入模型 small…"
    i18n.use("en")
    assert i18n.t("载入模型 {model}…", model="small") == "Loading model small…"


def test_explicit_language_beats_the_system(monkeypatch):
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    i18n.use("zh")
    assert i18n.language() == "zh"


def test_auto_follows_the_system_locale(monkeypatch):
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_MESSAGES", raising=False)
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    i18n.use("auto")
    assert i18n.language() == "en"
    monkeypatch.setenv("LANG", "zh_CN.UTF-8")
    i18n.use("auto")
    assert i18n.language() == "zh"


def test_unknown_language_falls_back_to_the_system(monkeypatch):
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_MESSAGES", raising=False)
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    i18n.use("klingon")
    assert i18n.language() == "en"


# ---------- 译文表本身 ----------


def test_every_chinese_string_in_the_source_has_a_translation():
    missing = sorted({s for s in _sources() if _has_chinese(s) and s not in _ENGLISH})
    assert not missing, f"这些文案还没有英文：{missing}"


def test_no_leftover_entries_in_the_catalog():
    used = set(_sources())
    stale = sorted(key for key in _ENGLISH if key not in used)
    assert not stale, f"源码里已经用不到这些文案了：{stale}"


def test_translations_keep_the_same_placeholders():
    for chinese, english in _ENGLISH.items():
        assert _fields(chinese) == _fields(english), f"占位符对不上：{chinese!r}"


def test_language_names_switch_with_the_interface():
    from subtitle_tool.languages import describe_tag, flores_name

    i18n.use("zh")
    assert flores_name("jpn_Jpan") == "日语" and describe_tag("ger") == "德语"
    i18n.use("en")
    assert flores_name("jpn_Jpan") == "Japanese" and describe_tag("ger") == "German"


def test_every_language_has_both_names():
    from subtitle_tool.languages import _TABLE

    for row in _TABLE:
        assert len(row) == 5 and row[3] and row[4], row
