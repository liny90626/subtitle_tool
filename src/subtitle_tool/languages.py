"""语种表：打通 Whisper 识别码、NLLB(FLORES-200) 翻译码、容器音轨语言标签三套编码。

- Whisper 用 ISO 639-1 两字母码（外加 ``yue``）标识识别出的语种。
- NLLB-200 用 FLORES-200 码（``语言_文字``，如 ``zho_Hans``）标识翻译方向。
- 视频容器（MKV/MP4）的音轨 ``language`` 元数据用 ISO 639-2，且 B/T 两套并存
  （德语可能是 ``ger`` 也可能是 ``deu``），需要同时认。

语种名中英各一套，跟着界面语言走。
"""

from .i18n import language, t

# (whisper 码, FLORES-200 码, ISO 639-2 码/以空格分隔的多写法, 中文名, 英文名)
# flores 为 None：Whisper 能识别但 NLLB 不支持，只能作源语言、不能作翻译目标。
# whisper 为 None：Whisper 不单独识别但可作为翻译目标。
_TABLE = (
    ("zh", "zho_Hans", "chi zho", "中文（简体）", "Chinese (Simplified)"),
    (None, "zho_Hant", "", "中文（繁体）", "Chinese (Traditional)"),
    ("yue", "yue_Hant", "yue", "粤语", "Cantonese"),
    ("en", "eng_Latn", "eng", "英语", "English"),
    ("ja", "jpn_Jpan", "jpn", "日语", "Japanese"),
    ("ko", "kor_Hang", "kor", "韩语", "Korean"),
    ("fr", "fra_Latn", "fre fra", "法语", "French"),
    ("de", "deu_Latn", "ger deu", "德语", "German"),
    ("es", "spa_Latn", "spa", "西班牙语", "Spanish"),
    ("pt", "por_Latn", "por", "葡萄牙语", "Portuguese"),
    ("it", "ita_Latn", "ita", "意大利语", "Italian"),
    ("ru", "rus_Cyrl", "rus", "俄语", "Russian"),
    ("ar", "arb_Arab", "ara", "阿拉伯语", "Arabic"),
    ("hi", "hin_Deva", "hin", "印地语", "Hindi"),
    ("th", "tha_Thai", "tha", "泰语", "Thai"),
    ("vi", "vie_Latn", "vie", "越南语", "Vietnamese"),
    ("id", "ind_Latn", "ind", "印尼语", "Indonesian"),
    ("ms", "zsm_Latn", "may msa", "马来语", "Malay"),
    ("tr", "tur_Latn", "tur", "土耳其语", "Turkish"),
    ("pl", "pol_Latn", "pol", "波兰语", "Polish"),
    ("nl", "nld_Latn", "dut nld", "荷兰语", "Dutch"),
    ("sv", "swe_Latn", "swe", "瑞典语", "Swedish"),
    ("da", "dan_Latn", "dan", "丹麦语", "Danish"),
    ("fi", "fin_Latn", "fin", "芬兰语", "Finnish"),
    ("no", "nob_Latn", "nor nob", "挪威语（书面）", "Norwegian (Bokmal)"),
    ("nn", "nno_Latn", "nno", "挪威语（新挪）", "Norwegian (Nynorsk)"),
    ("cs", "ces_Latn", "cze ces", "捷克语", "Czech"),
    ("sk", "slk_Latn", "slo slk", "斯洛伐克语", "Slovak"),
    ("uk", "ukr_Cyrl", "ukr", "乌克兰语", "Ukrainian"),
    ("el", "ell_Grek", "gre ell", "希腊语", "Greek"),
    ("he", "heb_Hebr", "heb", "希伯来语", "Hebrew"),
    ("hu", "hun_Latn", "hun", "匈牙利语", "Hungarian"),
    ("ro", "ron_Latn", "rum ron", "罗马尼亚语", "Romanian"),
    ("bg", "bul_Cyrl", "bul", "保加利亚语", "Bulgarian"),
    ("hr", "hrv_Latn", "hrv", "克罗地亚语", "Croatian"),
    ("sr", "srp_Cyrl", "srp", "塞尔维亚语", "Serbian"),
    ("bs", "bos_Latn", "bos", "波斯尼亚语", "Bosnian"),
    ("sl", "slv_Latn", "slv", "斯洛文尼亚语", "Slovenian"),
    ("mk", "mkd_Cyrl", "mac mkd", "马其顿语", "Macedonian"),
    ("sq", "als_Latn", "alb sqi", "阿尔巴尼亚语", "Albanian"),
    ("lt", "lit_Latn", "lit", "立陶宛语", "Lithuanian"),
    ("lv", "lvs_Latn", "lav", "拉脱维亚语", "Latvian"),
    ("et", "est_Latn", "est", "爱沙尼亚语", "Estonian"),
    ("ca", "cat_Latn", "cat", "加泰罗尼亚语", "Catalan"),
    ("gl", "glg_Latn", "glg", "加利西亚语", "Galician"),
    ("eu", "eus_Latn", "baq eus", "巴斯克语", "Basque"),
    ("oc", "oci_Latn", "oci", "奥克语", "Occitan"),
    ("is", "isl_Latn", "ice isl", "冰岛语", "Icelandic"),
    ("fo", "fao_Latn", "fao", "法罗语", "Faroese"),
    ("mt", "mlt_Latn", "mlt", "马耳他语", "Maltese"),
    ("cy", "cym_Latn", "wel cym", "威尔士语", "Welsh"),
    ("ga", "gle_Latn", "gle", "爱尔兰语", "Irish"),
    ("af", "afr_Latn", "afr", "南非荷兰语", "Afrikaans"),
    ("sw", "swh_Latn", "swa swh", "斯瓦希里语", "Swahili"),
    ("yo", "yor_Latn", "yor", "约鲁巴语", "Yoruba"),
    ("ha", "hau_Latn", "hau", "豪萨语", "Hausa"),
    ("so", "som_Latn", "som", "索马里语", "Somali"),
    ("sn", "sna_Latn", "sna", "绍纳语", "Shona"),
    ("ln", "lin_Latn", "lin", "林加拉语", "Lingala"),
    ("mg", "plt_Latn", "mlg", "马达加斯加语", "Malagasy"),
    ("am", "amh_Ethi", "amh", "阿姆哈拉语", "Amharic"),
    ("fa", "pes_Arab", "per fas", "波斯语", "Persian"),
    ("ps", "pbt_Arab", "pus", "普什图语", "Pashto"),
    ("ur", "urd_Arab", "urd", "乌尔都语", "Urdu"),
    ("sd", "snd_Arab", "snd", "信德语", "Sindhi"),
    ("bn", "ben_Beng", "ben", "孟加拉语", "Bengali"),
    ("as", "asm_Beng", "asm", "阿萨姆语", "Assamese"),
    ("gu", "guj_Gujr", "guj", "古吉拉特语", "Gujarati"),
    ("pa", "pan_Guru", "pan", "旁遮普语", "Punjabi"),
    ("mr", "mar_Deva", "mar", "马拉地语", "Marathi"),
    ("ne", "npi_Deva", "nep", "尼泊尔语", "Nepali"),
    ("sa", "san_Deva", "san", "梵语", "Sanskrit"),
    ("ta", "tam_Taml", "tam", "泰米尔语", "Tamil"),
    ("te", "tel_Telu", "tel", "泰卢固语", "Telugu"),
    ("kn", "kan_Knda", "kan", "卡纳达语", "Kannada"),
    ("ml", "mal_Mlym", "mal", "马拉雅拉姆语", "Malayalam"),
    ("si", "sin_Sinh", "sin", "僧伽罗语", "Sinhala"),
    ("my", "mya_Mymr", "bur mya", "缅甸语", "Burmese"),
    ("km", "khm_Khmr", "khm", "高棉语", "Khmer"),
    ("lo", "lao_Laoo", "lao", "老挝语", "Lao"),
    ("bo", "bod_Tibt", "tib bod", "藏语", "Tibetan"),
    ("ka", "kat_Geor", "geo kat", "格鲁吉亚语", "Georgian"),
    ("hy", "hye_Armn", "arm hye", "亚美尼亚语", "Armenian"),
    ("az", "azj_Latn", "aze", "阿塞拜疆语", "Azerbaijani"),
    ("kk", "kaz_Cyrl", "kaz", "哈萨克语", "Kazakh"),
    ("uz", "uzn_Latn", "uzb", "乌兹别克语", "Uzbek"),
    ("tk", "tuk_Latn", "tuk", "土库曼语", "Turkmen"),
    ("tg", "tgk_Cyrl", "tgk", "塔吉克语", "Tajik"),
    ("mn", "khk_Cyrl", "mon", "蒙古语", "Mongolian"),
    ("be", "bel_Cyrl", "bel", "白俄罗斯语", "Belarusian"),
    ("tt", "tat_Cyrl", "tat", "鞑靼语", "Tatar"),
    ("ba", "bak_Cyrl", "bak", "巴什基尔语", "Bashkir"),
    ("tl", "tgl_Latn", "tgl fil", "他加禄语", "Tagalog"),
    ("jw", "jav_Latn", "jav", "爪哇语", "Javanese"),
    ("su", "sun_Latn", "sun", "巽他语", "Sundanese"),
    ("mi", "mri_Latn", "mao mri", "毛利语", "Maori"),
    ("ht", "hat_Latn", "hat", "海地克里奥尔语", "Haitian Creole"),
    ("lb", "ltz_Latn", "ltz", "卢森堡语", "Luxembourgish"),
    ("yi", "ydd_Hebr", "yid", "意第绪语", "Yiddish"),
    ("la", None, "lat", "拉丁语", "Latin"),
    ("br", None, "bre", "布列塔尼语", "Breton"),
    ("haw", None, "haw", "夏威夷语", "Hawaiian"),
)

#: Whisper 识别码 -> FLORES-200 翻译码
WHISPER_TO_FLORES = {w: f for w, f, _, _, _ in _TABLE if w and f}

#: 可作为翻译目标的全部 FLORES-200 码
_TARGETS = frozenset(f for _, f, _, _, _ in _TABLE if f)


def _both(rows):
    """把 ``(键, 中文名, 英文名)`` 拆成 ``{语言: {键: 名}}`` 两套。"""
    return {"zh": {k: zh for k, zh, _ in rows}, "en": {k: en for k, _, en in rows}}


_FLORES_NAMES = _both([(f, zh, en) for _, f, _, zh, en in _TABLE if f])
_WHISPER_NAMES = _both([(w, zh, en) for w, _, _, zh, en in _TABLE if w])

#: 音轨元数据里的语言码 -> 语种名。同时收 ISO 639-2 三字母码（B/T 两套写法）和
#: BCP-47 常见的两字母码——``zh-CN``、``en-US`` 这类标签在网络片源里很常见。
_TAG_NAMES = _both(
    [(c, zh, en) for _, _, codes, zh, en in _TABLE for c in codes.split()]
    + [(w, zh, en) for w, _, _, zh, en in _TABLE if w]
)


def flores_of(whisper_code):
    """Whisper 识别码转 FLORES-200 码；该语种 NLLB 不支持时返回 None。"""
    return WHISPER_TO_FLORES.get(whisper_code)


def flores_name(flores_code):
    """FLORES-200 码转语种名，未知码原样返回。"""
    return _FLORES_NAMES[language()].get(flores_code, flores_code)


def describe_whisper(code):
    """把 Whisper 识别码渲染成 ``语种名(code)``，未知码原样返回。"""
    name = _WHISPER_NAMES[language()].get(code)
    return t("{name}({code})", name=name, code=code) if name else code


def describe_tag(tag):
    """把音轨 ``language`` 元数据渲染成语种名，未知或缺失时返回 None。"""
    if not tag:
        return None
    return _TAG_NAMES[language()].get(tag.lower().split("-")[0])


def target_choices():
    """可选翻译目标语种，按语种名排序，返回 ``[(flores 码, 语种名), ...]``。"""
    return sorted(_FLORES_NAMES[language()].items(), key=lambda kv: kv[1])


_SHORT_CODES = {f: w for w, f in WHISPER_TO_FLORES.items()}
_SHORT_CODES["zho_Hant"] = "zh-Hant"


def short_code(flores_code):
    """FLORES-200 码转适合做文件名后缀的短码，如 ``zho_Hans`` -> ``zh``。"""
    return _SHORT_CODES.get(flores_code, flores_code)


def resolve_target(text):
    """把用户输入的目标语种解析成 FLORES-200 码。

    接受 FLORES 码(``zho_Hans``)、短码(``zh``)、语种名（中英文都认，如
    ``中文（简体）`` / ``Chinese (Simplified)``），无法识别时返回 None。
    """
    if text in _TARGETS:
        return text
    for flores, short in _SHORT_CODES.items():
        if short == text:
            return flores
    for names in _FLORES_NAMES.values():
        for flores, name in names.items():
            if name == text:
                return flores
    return None
