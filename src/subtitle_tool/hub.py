"""模型下载源：本地缓存优先，官方源连不上就换镜像，也可以走代理。

打包版最常见的失败是下不动模型。识别与翻译模型都托管在 huggingface.co，而这个
域名在部分网络（尤其中国大陆）根本连不通，huggingface_hub 会一路超时到
``ConnectTimeout: [WinError 10060]``，最后报「cannot find the appropriate snapshot
folder」——看着像程序坏了，其实只是网络到不了下载源。

因此这里统一接管「取模型」这件事：

- 下过的模型直接从本地缓存加载，一次网都不联（README 承诺的「离线可用」）；
- 真要下载时先挑一个通得了的源，官方不通就自动换镜像；
- 下载失败给出照着做就能解决的中文提示，而不是把英文调用栈甩给用户。
"""

import json
import os
import sys
from dataclasses import asdict, dataclass
from typing import Callable, Optional

#: 官方源
OFFICIAL = "https://huggingface.co"
#: 国内可用的只读镜像。路径与官方完全一致，换个域名就能下
MIRROR = "https://hf-mirror.com"
#: 下载源设置的特殊值：先试官方，连不上再用镜像
AUTO = "auto"

#: 探测用的小文件。识别模型都出自这个仓库家族，拿它当代表最贴近真实下载
_PROBE_FILE = "/Systran/faster-whisper-tiny/resolve/main/config.json"
#: 探测超时。连不通的网络通常卡在 TCP 握手，等满这几秒就足够判定
_PROBE_TIMEOUT = 6.0
#: CTranslate2 模型（识别、翻译都是）由这几个文件组成，缺一个就说明缓存没下全
_REQUIRED_FILES = ("config.json", "model.bin", "tokenizer.json")

#: 用户自己在环境里配的 HF_ENDPOINT。必须在本模块设值之前读，它比「自动」优先
_ENV_ENDPOINT = (os.environ.get("HF_ENDPOINT") or "").rstrip("/")

#: 当前生效的设置，由 apply() 写入
_settings: "Settings"
#: 本进程已选定的下载源，避免每次取模型都重探一遍
_chosen: Optional[str] = None
#: 本进程设过的代理环境变量，用户改设置时要能撤掉
_proxy_vars: tuple = ()


class DownloadError(RuntimeError):
    """模型下载失败。消息里带着可以照做的解决办法。"""


@dataclass
class Settings:
    """模型下载相关的设置，图形界面与命令行共用一份。"""

    source: str = AUTO  #: AUTO，或某个下载源地址
    proxy: str = ""  #: 形如 http://127.0.0.1:7890，留空表示不用代理


def config_path() -> str:
    """设置文件路径。Windows 放 %APPDATA%，其它平台放 ~/.config。"""
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "subtitle-tool", "settings.json")


def load() -> Settings:
    """读设置。文件不存在或读坏了都退回默认值——设置坏了不该让程序起不来。"""
    try:
        with open(config_path(), encoding="utf-8") as handle:
            data = json.load(handle)
        return Settings(source=str(data.get("source") or AUTO), proxy=str(data.get("proxy") or ""))
    except (OSError, ValueError, AttributeError):
        return Settings()


def save(settings: Settings) -> None:
    """写设置。写不进去（目录只读等）会抛 OSError，由调用方决定怎么提示。"""
    path = config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(asdict(settings), handle, ensure_ascii=False, indent=2)


def apply(settings: Settings) -> None:
    """让设置生效。

    环境变量得赶在 huggingface_hub 被导入之前设好——它在 import 时就把
    ``HF_ENDPOINT`` 固化成模块常量了，所以 :mod:`subtitle_tool` 一被导入就会调一次
    本函数。界面上改设置发生在导入之后，那时还得直接改常量、并把 HTTP 连接池丢掉
    重建（代理是建连接池时读的环境变量），两条路都要走。
    """
    global _settings, _chosen
    _settings = settings
    _chosen = None
    _apply_proxy(settings.proxy)
    if settings.source != AUTO:
        _use(settings.source)
    _reset_session()


def endpoint() -> str:
    """选定这次用哪个下载源。「自动」时探测一次，结果按进程缓存。"""
    global _chosen
    if _chosen:
        return _chosen
    if _settings.source != AUTO:
        candidates = [_settings.source]
    elif _ENV_ENDPOINT:
        # 用户自己配了 HF_ENDPOINT（自建源、公司内网镜像），照做，不去探测
        candidates = [_ENV_ENDPOINT]
    else:
        candidates = [OFFICIAL, MIRROR]

    # 一个都探测不过时仍按首选源试一次：探测只用来加速选源，不该把本来
    # 能下的情况直接挡掉
    chosen = candidates[0]
    if len(candidates) > 1:
        chosen = next((c for c in candidates if _usable(c)), chosen)

    _chosen = chosen.rstrip("/")
    _use(_chosen)
    return _chosen


def fetch(
    download: Callable[[bool], str],
    what: str,
    cache_dir: Optional[str] = None,
    notify: Optional[Callable[[str], None]] = None,
) -> str:
    """取模型目录：先看本地缓存，缺了才联网下载。

    ``download(local_only)`` 是各模型自己的下载函数（faster-whisper 的
    ``download_model``、huggingface_hub 的 ``snapshot_download``），返回模型目录。
    """
    path = _cached(download)
    if path is not None:
        return path
    source = endpoint()
    if notify:
        notify(f"正在从 {source} 下载{what}，首次使用需要等一会儿，之后一直复用本地缓存。")
    try:
        return download(False)
    except Exception as error:
        raise DownloadError(_advice(what, source, cache_dir, error)) from error


def _cached(download: Callable[[bool], str]) -> Optional[str]:
    """本地缓存里已有完整模型就返回它的目录，否则返回 None。

    huggingface_hub 即使缓存命中也要先问一次 Hub 有没有新版本，网络不通就得等满
    超时。模型仓库是固定不动的，直接认缓存能让离线启动快得多，也更可靠。
    """
    try:
        path = download(True)
    except Exception:
        return None
    if all(os.path.isfile(os.path.join(path, name)) for name in _REQUIRED_FILES):
        return path
    # 上次下到一半：当作没有，重新联网补全
    return None


def _usable(source: str) -> bool:
    """这个源能不能真的下东西。

    只测「连得上」不够：hf-mirror.com 对境外 IP 会 308 跳回 huggingface.co，而
    huggingface_hub 不跟随跨域跳转，这种源看着通、实际下不动。所以按它真正依赖的
    东西判定——HEAD 一个小文件，响应头里必须带 x-repo-commit。
    """
    try:
        response = _head(source.rstrip("/") + _PROBE_FILE, _PROBE_TIMEOUT)
        return response.headers.get("x-repo-commit") is not None
    except Exception:
        return False


def _head(url: str, timeout: float):
    """用 huggingface_hub 自己的 HTTP 客户端发 HEAD，且不跟随跳转。

    借它的客户端是为了让探测与真正下载走同一套代理、证书和超时设置；
    1.x 用 httpx、0.x 用 requests，两边关跳转的参数名不一样。
    """
    from huggingface_hub.utils import get_session

    session = get_session()
    try:
        return session.head(url, timeout=timeout, follow_redirects=False)
    except TypeError:
        return session.head(url, timeout=timeout, allow_redirects=False)


def _use(source: str) -> None:
    """把下载源切到 ``source``：环境变量，以及已经导入的 huggingface_hub。"""
    source = source.rstrip("/")
    os.environ["HF_ENDPOINT"] = source
    if source != OFFICIAL:
        # 非官方源必须关掉 Xet：它的分块下载会绕开镜像直连 huggingface 自己的存储
        # 服务器，连不上官方源的网络照样下不动
        os.environ["HF_HUB_DISABLE_XET"] = "1"

    constants = sys.modules.get("huggingface_hub.constants")
    if constants is None:
        return  # 还没导入，等它 import 时读上面的环境变量就行
    if source != OFFICIAL:
        constants.HF_HUB_DISABLE_XET = True
    old = constants.ENDPOINT.rstrip("/")
    if old == source:
        return
    template = source + "/{repo_id}/resolve/{revision}/{filename}"
    for name, module in list(sys.modules.items()):
        # 0.x 的 file_download 是 `from .constants import HUGGINGFACE_CO_URL_TEMPLATE`
        # 按名字绑过去的，只改 constants 上那一份对它不起作用
        if module is None or not name.startswith("huggingface_hub"):
            continue
        if getattr(module, "ENDPOINT", None) == old:
            module.ENDPOINT = source
        if isinstance(getattr(module, "HUGGINGFACE_CO_URL_TEMPLATE", None), str):
            module.HUGGINGFACE_CO_URL_TEMPLATE = template


def _apply_proxy(proxy: str) -> None:
    """设置里的代理写进环境变量；httpx 与 requests 都从这里读。"""
    global _proxy_vars
    for name in _proxy_vars:
        os.environ.pop(name, None)
    _proxy_vars = ()
    if not proxy:
        # 留空只撤掉本程序设过的，不动用户自己在系统里配的
        return
    _proxy_vars = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")
    for name in _proxy_vars:
        os.environ[name] = proxy


def _reset_session() -> None:
    """丢掉 huggingface_hub 缓存的 HTTP 连接池。

    1.x 的 httpx 客户端是第一次请求时按当时的环境变量建的，之后再改代理不会生效，
    必须让它重建；0.x 的 requests 每次请求都重读环境变量，没这个问题。
    """
    if "huggingface_hub" not in sys.modules:
        return  # 还没导入就别为了重置把它拖进来
    try:
        from huggingface_hub.utils import close_session
    except ImportError:
        return
    close_session()


def _advice(what: str, source: str, cache_dir: Optional[str], error: Exception) -> str:
    # 已经在用镜像了就别再劝人换镜像
    switch = (
        "把「模型下载源」改回「自动选源」（命令行加 --model-source auto）"
        if source == MIRROR
        else "把「模型下载源」改成「镜像 hf-mirror.com」（命令行加 --model-source mirror）"
    )
    tips = (
        switch,
        "有代理/VPN 就填上「代理」，例如 http://127.0.0.1:7890"
        "（命令行加 --proxy http://127.0.0.1:7890）",
        f"在能联网的机器上下好模型，把整个 {cache_dir or _default_cache()} 目录复制过来",
    )
    steps = "；\n".join(f"  {i}. {tip}" for i, tip in enumerate(tips, 1))
    return (
        f"{what} 下载失败，通常是连不上下载源 {source}。可以试试：\n"
        f"{steps}。\n"
        f"原始错误：{type(error).__name__}: {error}"
    )


def _default_cache() -> str:
    try:
        from huggingface_hub import constants

        return constants.HF_HUB_CACHE
    except Exception:
        return os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")


_settings = Settings()
