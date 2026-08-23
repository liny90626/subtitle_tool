"""字幕翻译：CTranslate2 + NLLB-200。

选 NLLB 而非 Opus-MT/Argos：单个模型覆盖 200 语种的任意方向，不必按语言对分别
下载模型；且与语音识别共用 CTranslate2 运行时，不引入第二套推理框架。
分词直接用 ``tokenizers`` 读 ``tokenizer.json``，省掉 transformers 依赖。
"""

import os
import re
import threading
from typing import Callable, Optional

import ctranslate2
from huggingface_hub import snapshot_download
from tokenizers import Tokenizer

from .asr import Cancelled, pick_device

#: 翻译模型仓库。600M 约 620MB，1.3B 约 1.4GB、质量更好但慢 2 倍以上。
MODEL_REPOS = {
    "nllb-600m": "JustFrederik/nllb-200-distilled-600M-ct2-int8",
    "nllb-1.3b": "JustFrederik/nllb-200-distilled-1.3B-ct2-int8",
}
DEFAULT_MODEL = "nllb-600m"

_EOS = "</s>"


class Translator:
    """加载一次翻译模型，反复翻译。"""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        device: str = "auto",
        download_root: Optional[str] = None,
    ):
        path = snapshot_download(MODEL_REPOS[model], cache_dir=download_root)
        self.tokenizer = Tokenizer.from_file(os.path.join(path, "tokenizer.json"))
        self.device, self.compute_type = pick_device(device)
        self.translator = ctranslate2.Translator(
            path, device=self.device, compute_type=self.compute_type
        )
        self.model = model

    def translate(
        self,
        texts: list[str],
        source: str,
        target: str,
        batch_size: int = 16,
        progress: Optional[Callable[[float], None]] = None,
        cancel: Optional[threading.Event] = None,
    ) -> list[str]:
        """把 ``texts`` 从 FLORES 码 ``source`` 翻成 ``target``，顺序与入参一一对应。"""
        if source == target:
            return list(texts)

        groups = [self._segment(text) for text in texts]
        sentences = [s for group in groups for s in group]

        done: list[str] = []
        for start in range(0, len(sentences), batch_size):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            done.extend(
                self._translate_batch(sentences[start : start + batch_size], source, target)
            )
            if progress:
                progress(min(len(done) / len(sentences), 1.0))

        joiner = "" if target in _PUNCTUATION else " "
        results, cursor = [], 0
        for group in groups:
            results.append(joiner.join(done[cursor : cursor + len(group)]))
            cursor += len(group)
        return results

    def _segment(self, text: str) -> list[str]:
        """把一条字幕拆成 NLLB 能稳定处理的片段。

        NLLB-600M 是句级模型：一条字幕塞进两三句、或者一句里挂着 20 个 token 以上的
        并列子句时，它会直接把后半段吞掉（实测「…can do for you, ask what you can do
        for your country.」后半句整段丢失）。漏译是正确性问题，拆句带来的行文碎片化
        只是风格问题，因此宁可多拆。
        """
        pieces = []
        for sentence in _split_sentences(text):
            pieces.extend(self._split_clauses(sentence))
        return pieces

    def _split_clauses(self, text: str) -> list[str]:
        if len(self.tokenizer.encode(text, add_special_tokens=False).ids) <= _MAX_TOKENS:
            return [text]
        cut = _clause_point(text)
        if cut is None:
            return [text]
        return self._split_clauses(text[:cut].strip()) + self._split_clauses(text[cut:].strip())

    def _translate_batch(self, texts: list[str], source: str, target: str) -> list[str]:
        # NLLB 的输入格式：[源语言码] ...子词... </s>，目标语言码作为解码前缀强制输出方向
        sources = [
            [source, *self.tokenizer.encode(text, add_special_tokens=False).tokens, _EOS]
            for text in texts
        ]
        outputs = self.translator.translate_batch(
            sources,
            target_prefix=[[target]] * len(sources),
            beam_size=4,
            # NLLB 偶发复读，轻微惩罚重复即可压住，且几乎不影响正常译文
            repetition_penalty=1.1,
        )
        return [_localize(self._decode(out.hypotheses[0]), target) for out in outputs]

    def _decode(self, tokens: list[str]) -> str:
        ids = [self.tokenizer.token_to_id(t) for t in tokens[1:]]  # 去掉开头的目标语言码
        return self.tokenizer.decode([i for i in ids if i is not None], skip_special_tokens=True)


# NLLB 的解码器对 CJK 目标语一律吐 ASCII 标点（"所以,我的同胞们."），
# 直接当字幕看很别扭，按目标语种换回全角。
_ZH_PUNCTUATION = {",": "，", ".": "。", "?": "？", "!": "！", ":": "：", ";": "；"}
_JA_PUNCTUATION = dict(_ZH_PUNCTUATION, **{",": "、"})
_PUNCTUATION = {
    "zho_Hans": _ZH_PUNCTUATION,
    "zho_Hant": _ZH_PUNCTUATION,
    "yue_Hant": _ZH_PUNCTUATION,
    "jpn_Jpan": _JA_PUNCTUATION,
}


def _localize(text: str, target: str) -> str:
    table = _PUNCTUATION.get(target)
    if not table:
        return text
    chars = []
    for char in text:
        # 只在前一个字是汉字/假名时替换，避免把 "3.5"、"Dr. Smith" 一起改掉
        if char in table and chars and _is_han(chars[-1]):
            chars.append(table[char])
        else:
            chars.append(char)
    return "".join(chars)


def _is_han(char: str) -> bool:
    return "\u3040" <= char <= "\u9fff" or "\uf900" <= char <= "\ufaff"


#: 句末标点：CJK 标点后必断句，拉丁标点要求后面是空白或结尾，免得把 "3.5" 拆开
_SENTENCE_BREAK = re.compile(r"(?<=[。！？])|(?<=[.!?…])(?=\s|$)")
#: 短于此长度的片段并回下一句，免得 "Dr." 这类缩写被当成独立句子送去翻译
_MIN_SENTENCE = 8
#: 单句超过这么多 token 就按子句再拆一次，阈值由实测漏译的起点定出
_MAX_TOKENS = 20
#: 子句分隔符，切点落在这些标点之后
_CLAUSE_BREAK = re.compile(r"(?<=[,;，；、])\s*")


def _split_sentences(text: str) -> list[str]:
    pieces = [p.strip() for p in _SENTENCE_BREAK.split(text)]
    sentences: list[str] = []
    for piece in pieces:
        if not piece:
            continue
        if sentences and len(sentences[-1]) < _MIN_SENTENCE:
            sentences[-1] = f"{sentences[-1]} {piece}"
        else:
            sentences.append(piece)
    return sentences or [text]


def _clause_point(text: str):
    """找最接近正中的子句切点，没有子句标点时返回 None。"""
    cuts = [m.end() for m in _CLAUSE_BREAK.finditer(text) if 0 < m.end() < len(text)]
    if not cuts:
        return None
    middle = len(text) // 2
    return min(cuts, key=lambda i: abs(i - middle))
