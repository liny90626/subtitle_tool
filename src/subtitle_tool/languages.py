"""语种表：打通 Whisper 识别码、NLLB(FLORES-200) 翻译码、容器音轨语言标签三套编码。

- Whisper 用 ISO 639-1 两字母码（外加 ``yue``）标识识别出的语种。
- NLLB-200 用 FLORES-200 码（``语言_文字``，如 ``zho_Hans``）标识翻译方向。
- 视频容器（MKV/MP4）的音轨 ``language`` 元数据用 ISO 639-2，且 B/T 两套并存
  （德语可能是 ``ger`` 也可能是 ``deu``），需要同时认。
"""

# (whisper 码, FLORES-200 码, ISO 639-2 码/以空格分隔的多写法, 中文名)
# flores 为 None：Whisper 能识别但 NLLB 不支持，只能作源语言、不能作翻译目标。
# whisper 为 None：Whisper 不单独识别但可作为翻译目标。
_TABLE = (
    ("zh", "zho_Hans", "chi zho", "中文（简体）"),
    (None, "zho_Hant", "", "中文（繁体）"),
    ("yue", "yue_Hant", "yue", "粤语"),
    ("en", "eng_Latn", "eng", "英语"),
    ("ja", "jpn_Jpan", "jpn", "日语"),
    ("ko", "kor_Hang", "kor", "韩语"),
    ("fr", "fra_Latn", "fre fra", "法语"),
    ("de", "deu_Latn", "ger deu", "德语"),
    ("es", "spa_Latn", "spa", "西班牙语"),
    ("pt", "por_Latn", "por", "葡萄牙语"),
    ("it", "ita_Latn", "ita", "意大利语"),
    ("ru", "rus_Cyrl", "rus", "俄语"),
    ("ar", "arb_Arab", "ara", "阿拉伯语"),
    ("hi", "hin_Deva", "hin", "印地语"),
    ("th", "tha_Thai", "tha", "泰语"),
    ("vi", "vie_Latn", "vie", "越南语"),
    ("id", "ind_Latn", "ind", "印尼语"),
    ("ms", "zsm_Latn", "may msa", "马来语"),
    ("tr", "tur_Latn", "tur", "土耳其语"),
    ("pl", "pol_Latn", "pol", "波兰语"),
    ("nl", "nld_Latn", "dut nld", "荷兰语"),
    ("sv", "swe_Latn", "swe", "瑞典语"),
    ("da", "dan_Latn", "dan", "丹麦语"),
    ("fi", "fin_Latn", "fin", "芬兰语"),
    ("no", "nob_Latn", "nor nob", "挪威语（书面）"),
    ("nn", "nno_Latn", "nno", "挪威语（新挪）"),
    ("cs", "ces_Latn", "cze ces", "捷克语"),
    ("sk", "slk_Latn", "slo slk", "斯洛伐克语"),
    ("uk", "ukr_Cyrl", "ukr", "乌克兰语"),
    ("el", "ell_Grek", "gre ell", "希腊语"),
    ("he", "heb_Hebr", "heb", "希伯来语"),
    ("hu", "hun_Latn", "hun", "匈牙利语"),
    ("ro", "ron_Latn", "rum ron", "罗马尼亚语"),
    ("bg", "bul_Cyrl", "bul", "保加利亚语"),
    ("hr", "hrv_Latn", "hrv", "克罗地亚语"),
    ("sr", "srp_Cyrl", "srp", "塞尔维亚语"),
    ("bs", "bos_Latn", "bos", "波斯尼亚语"),
    ("sl", "slv_Latn", "slv", "斯洛文尼亚语"),
    ("mk", "mkd_Cyrl", "mac mkd", "马其顿语"),
    ("sq", "als_Latn", "alb sqi", "阿尔巴尼亚语"),
    ("lt", "lit_Latn", "lit", "立陶宛语"),
    ("lv", "lvs_Latn", "lav", "拉脱维亚语"),
    ("et", "est_Latn", "est", "爱沙尼亚语"),
    ("ca", "cat_Latn", "cat", "加泰罗尼亚语"),
    ("gl", "glg_Latn", "glg", "加利西亚语"),
    ("eu", "eus_Latn", "baq eus", "巴斯克语"),
    ("oc", "oci_Latn", "oci", "奥克语"),
    ("is", "isl_Latn", "ice isl", "冰岛语"),
    ("fo", "fao_Latn", "fao", "法罗语"),
    ("mt", "mlt_Latn", "mlt", "马耳他语"),
    ("cy", "cym_Latn", "wel cym", "威尔士语"),
    ("ga", "gle_Latn", "gle", "爱尔兰语"),
    ("af", "afr_Latn", "afr", "南非荷兰语"),
    ("sw", "swh_Latn", "swa swh", "斯瓦希里语"),
    ("yo", "yor_Latn", "yor", "约鲁巴语"),
    ("ha", "hau_Latn", "hau", "豪萨语"),
    ("so", "som_Latn", "som", "索马里语"),
    ("sn", "sna_Latn", "sna", "绍纳语"),
    ("ln", "lin_Latn", "lin", "林加拉语"),
    ("mg", "plt_Latn", "mlg", "马达加斯加语"),
    ("am", "amh_Ethi", "amh", "阿姆哈拉语"),
    ("fa", "pes_Arab", "per fas", "波斯语"),
    ("ps", "pbt_Arab", "pus", "普什图语"),
    ("ur", "urd_Arab", "urd", "乌尔都语"),
    ("sd", "snd_Arab", "snd", "信德语"),
    ("bn", "ben_Beng", "ben", "孟加拉语"),
    ("as", "asm_Beng", "asm", "阿萨姆语"),
    ("gu", "guj_Gujr", "guj", "古吉拉特语"),
    ("pa", "pan_Guru", "pan", "旁遮普语"),
    ("mr", "mar_Deva", "mar", "马拉地语"),
    ("ne", "npi_Deva", "nep", "尼泊尔语"),
    ("sa", "san_Deva", "san", "梵语"),
    ("ta", "tam_Taml", "tam", "泰米尔语"),
    ("te", "tel_Telu", "tel", "泰卢固语"),
    ("kn", "kan_Knda", "kan", "卡纳达语"),
    ("ml", "mal_Mlym", "mal", "马拉雅拉姆语"),
    ("si", "sin_Sinh", "sin", "僧伽罗语"),
    ("my", "mya_Mymr", "bur mya", "缅甸语"),
    ("km", "khm_Khmr", "khm", "高棉语"),
    ("lo", "lao_Laoo", "lao", "老挝语"),
    ("bo", "bod_Tibt", "tib bod", "藏语"),
    ("ka", "kat_Geor", "geo kat", "格鲁吉亚语"),
    ("hy", "hye_Armn", "arm hye", "亚美尼亚语"),
    ("az", "azj_Latn", "aze", "阿塞拜疆语"),
    ("kk", "kaz_Cyrl", "kaz", "哈萨克语"),
    ("uz", "uzn_Latn", "uzb", "乌兹别克语"),
    ("tk", "tuk_Latn", "tuk", "土库曼语"),
    ("tg", "tgk_Cyrl", "tgk", "塔吉克语"),
    ("mn", "khk_Cyrl", "mon", "蒙古语"),
    ("be", "bel_Cyrl", "bel", "白俄罗斯语"),
    ("tt", "tat_Cyrl", "tat", "鞑靼语"),
    ("ba", "bak_Cyrl", "bak", "巴什基尔语"),
    ("tl", "tgl_Latn", "tgl fil", "他加禄语"),
    ("jw", "jav_Latn", "jav", "爪哇语"),
    ("su", "sun_Latn", "sun", "巽他语"),
    ("mi", "mri_Latn", "mao mri", "毛利语"),
    ("ht", "hat_Latn", "hat", "海地克里奥尔语"),
    ("lb", "ltz_Latn", "ltz", "卢森堡语"),
    ("yi", "ydd_Hebr", "yid", "意第绪语"),
    ("la", None, "lat", "拉丁语"),
    ("br", None, "bre", "布列塔尼语"),
    ("haw", None, "haw", "夏威夷语"),
)

#: Whisper 识别码 -> FLORES-200 翻译码
WHISPER_TO_FLORES = {w: f for w, f, _, _ in _TABLE if w and f}

#: FLORES-200 翻译码 -> 中文名（可作为翻译目标的全部语种）
FLORES_NAMES = {f: n for _, f, _, n in _TABLE if f}

#: Whisper 识别码 -> 中文名
WHISPER_NAMES = {w: n for w, _, _, n in _TABLE if w}

#: 音轨元数据里的语言码 -> 中文名。同时收 ISO 639-2 三字母码（B/T 两套写法）和
#: BCP-47 常见的两字母码——``zh-CN``、``en-US`` 这类标签在网络片源里很常见。
_TAG_NAMES = {c: n for _, _, codes, n in _TABLE for c in codes.split()}
_TAG_NAMES.update({w: n for w, _, _, n in _TABLE if w})


def flores_of(whisper_code):
    """Whisper 识别码转 FLORES-200 码；该语种 NLLB 不支持时返回 None。"""
    return WHISPER_TO_FLORES.get(whisper_code)


def describe_whisper(code):
    """把 Whisper 识别码渲染成 ``中文名(code)``，未知码原样返回。"""
    name = WHISPER_NAMES.get(code)
    return f"{name}({code})" if name else code


def describe_tag(tag):
    """把音轨 ``language`` 元数据渲染成中文名，未知或缺失时返回 None。"""
    if not tag:
        return None
    return _TAG_NAMES.get(tag.lower().split("-")[0])


def target_choices():
    """可选翻译目标语种，按中文名排序，返回 ``[(flores 码, 中文名), ...]``。"""
    return sorted(FLORES_NAMES.items(), key=lambda kv: kv[1])


_SHORT_CODES = {f: w for w, f in WHISPER_TO_FLORES.items()}
_SHORT_CODES["zho_Hant"] = "zh-Hant"


def short_code(flores_code):
    """FLORES-200 码转适合做文件名后缀的短码，如 ``zho_Hans`` -> ``zh``。"""
    return _SHORT_CODES.get(flores_code, flores_code)


def resolve_target(text):
    """把用户输入的目标语种解析成 FLORES-200 码。

    接受 FLORES 码(``zho_Hans``)、短码(``zh``)、中文名(``中文（简体）``)三种写法，
    无法识别时返回 None。
    """
    if text in FLORES_NAMES:
        return text
    for flores, short in _SHORT_CODES.items():
        if short == text:
            return flores
    for flores, name in FLORES_NAMES.items():
        if name == text:
            return flores
    return None
