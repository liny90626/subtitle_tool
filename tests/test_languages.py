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


def test_resolve_target_accepts_three_notations():
    assert L.resolve_target("zh") == "zho_Hans"
    assert L.resolve_target("zho_Hans") == "zho_Hans"
    assert L.resolve_target("中文（简体）") == "zho_Hans"
    assert L.resolve_target("不存在的语言") is None


def test_short_code_round_trip():
    assert L.short_code("jpn_Jpan") == "ja"
    assert L.short_code("zho_Hant") == "zh-Hant"


def test_every_flores_target_is_unique():
    codes = [f for _, f, _, _ in L._TABLE if f]
    assert len(codes) == len(set(codes))
