from subtitle_tool import languages as L


def test_whisper_codes_map_to_flores():
    assert L.flores_of("zh") == "zho_Hans"
    assert L.flores_of("de") == "deu_Latn"
    # Whisper 认得但 NLLB 没有的语种，只能当源语言
    assert L.flores_of("la") is None


def test_container_tags_accept_both_iso_variants():
    # ffmpeg 写出的德语标签可能是 ISO 639-2/B 的 ger 也可能是 /T 的 deu
    assert L.describe_tag("ger") == L.describe_tag("deu") == "德语"
    assert L.describe_tag("zh-CN") == "中文（简体）"
    assert L.describe_tag(None) is None
    assert L.describe_tag("xxx") is None


def test_resolve_target_accepts_codes_and_names_in_both_languages():
    assert L.resolve_target("zh") == "zho_Hans"
    assert L.resolve_target("zho_Hans") == "zho_Hans"
    assert L.resolve_target("中文（简体）") == "zho_Hans"
    # 英文界面下用户看到的是英文名，命令行也得认
    assert L.resolve_target("Chinese (Simplified)") == "zho_Hans"
    assert L.resolve_target("不存在的语言") is None


def test_short_code_round_trip():
    assert L.short_code("jpn_Jpan") == "ja"
    assert L.short_code("zho_Hant") == "zh-Hant"


def test_every_flores_target_is_unique():
    codes = [f for _, f, _, _, _ in L._TABLE if f]
    assert len(codes) == len(set(codes))


def test_language_names_are_unique_within_each_language():
    for names in (L._FLORES_NAMES["zh"], L._FLORES_NAMES["en"]):
        assert len(set(names.values())) == len(names)


def test_source_choices_cover_every_whisper_code_and_follow_the_interface():
    from subtitle_tool import i18n

    codes = [code for code, _ in L.source_choices()]
    assert sorted(codes) == sorted(L.WHISPER_CODES)
    # NLLB 翻不了的语种照样能当源语言，别在这儿把它们漏掉
    assert "la" in codes
    assert dict(L.source_choices())["ja"] == "日语"
    i18n.use("en")
    assert dict(L.source_choices())["ja"] == "Japanese"


def test_source_choices_are_sorted_by_name():
    names = [name for _, name in L.source_choices()]
    assert names == sorted(names)
