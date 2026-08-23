"""字幕翻译：CTranslate2 + NLLB-200。

选 NLLB 而非 Opus-MT/Argos：单个模型覆盖 200 语种的任意方向，不必按语言对分别
下载模型；且与语音识别共用 CTranslate2 运行时，不引入第二套推理框架。
分词直接用 ``tokenizers`` 读 ``tokenizer.json``，省掉 transformers 依赖。
"""

import os
import threading
from typing import Callable, List, Optional

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
        texts: List[str],
        source: str,
        target: str,
        batch_size: int = 16,
        progress: Optional[Callable[[float], None]] = None,
        cancel: Optional[threading.Event] = None,
    ) -> List[str]:
        """把 ``texts`` 从 FLORES 码 ``source`` 翻成 ``target``，顺序与入参一一对应。"""
        if source == target:
            return list(texts)

        results: List[str] = []
        for start in range(0, len(texts), batch_size):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            chunk = texts[start : start + batch_size]
            results.extend(self._translate_batch(chunk, source, target))
            if progress:
                progress(min(len(results) / len(texts), 1.0))
        return results

    def _translate_batch(self, texts: List[str], source: str, target: str) -> List[str]:
        # NLLB 的输入格式：[源语言码] ...子词... </s>，目标语言码作为解码前缀强制输出方向
        sources = [
            [source] + self.tokenizer.encode(text, add_special_tokens=False).tokens + [_EOS]
            for text in texts
        ]
        outputs = self.translator.translate_batch(
            sources,
            target_prefix=[[target]] * len(sources),
            beam_size=4,
            # NLLB 偶发复读，轻微惩罚重复即可压住，且几乎不影响正常译文
            repetition_penalty=1.1,
        )
        return [self._decode(out.hypotheses[0]) for out in outputs]

    def _decode(self, tokens: List[str]) -> str:
        ids = [self.tokenizer.token_to_id(t) for t in tokens[1:]]  # 去掉开头的目标语言码
        return self.tokenizer.decode([i for i in ids if i is not None], skip_special_tokens=True)
