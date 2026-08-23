import os
import sys

import pytest

from subtitle_tool import hub, settings


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    """隔离 hub 的进程级状态、环境变量和 huggingface_hub 的模块常量。"""
    monkeypatch.setenv("APPDATA", str(tmp_path / "config"))
    monkeypatch.setattr(hub, "_ENV_ENDPOINT", "")
    environ = dict(os.environ)
    state = (hub._settings, hub._chosen, hub._proxy_vars)
    constants = sys.modules.get("huggingface_hub.constants")
    frozen = None
    if constants is not None:
        frozen = (
            constants.ENDPOINT,
            constants.HUGGINGFACE_CO_URL_TEMPLATE,
            constants.HF_HUB_DISABLE_XET,
        )

    yield

    if frozen is not None:
        hub._use(frozen[0])  # 把扫描改过的各模块常量改回去
        constants.HUGGINGFACE_CO_URL_TEMPLATE = frozen[1]
        constants.HF_HUB_DISABLE_XET = frozen[2]
    os.environ.clear()
    os.environ.update(environ)
    hub._settings, hub._chosen, hub._proxy_vars = state


class _Response:
    def __init__(self, headers):
        self.headers = headers


class _Session:
    """假的 HTTP 客户端，记录调用参数。"""

    def __init__(self, replies, style="httpx"):
        self.replies = replies  # {url: 响应头 或 异常}
        self.style = style
        self.calls = []

    def head(self, url, timeout=None, **kwargs):
        if self.style == "httpx" and "allow_redirects" in kwargs:
            raise TypeError("unexpected keyword argument 'allow_redirects'")
        if self.style == "requests" and "follow_redirects" in kwargs:
            raise TypeError("unexpected keyword argument 'follow_redirects'")
        self.calls.append((url, kwargs))
        reply = self.replies[url]
        if isinstance(reply, Exception):
            raise reply
        return _Response(reply)


def _session(monkeypatch, replies, style="httpx"):
    session = _Session(replies, style)
    monkeypatch.setattr("huggingface_hub.utils.get_session", lambda: session)
    return session


def _snapshot(tmp_path, name, files=hub._REQUIRED_FILES):
    directory = tmp_path / name
    directory.mkdir()
    for filename in files:
        (directory / filename).write_text("x", encoding="utf-8")
    return str(directory)


# ---------- 选源 ----------


def test_explicit_source_is_used_without_probing(monkeypatch):
    monkeypatch.setattr(hub, "_usable", lambda source: pytest.fail("指定了源就不该再探测"))
    hub.apply(settings.Settings(source=hub.MIRROR))
    assert hub.endpoint() == hub.MIRROR


def test_auto_keeps_official_when_it_works(monkeypatch):
    monkeypatch.setattr(hub, "_usable", lambda source: source == hub.OFFICIAL)
    hub.apply(settings.Settings())
    assert hub.endpoint() == hub.OFFICIAL


def test_auto_switches_to_mirror_when_official_is_unreachable(monkeypatch):
    monkeypatch.setattr(hub, "_usable", lambda source: source == hub.MIRROR)
    hub.apply(settings.Settings())
    assert hub.endpoint() == hub.MIRROR


def test_auto_still_tries_official_when_every_probe_fails(monkeypatch):
    # 探测只用来加速选源，全都探不过时不能把本来能下的情况直接挡掉
    monkeypatch.setattr(hub, "_usable", lambda source: False)
    hub.apply(settings.Settings())
    assert hub.endpoint() == hub.OFFICIAL


def test_source_is_probed_once_per_process(monkeypatch):
    probed = []
    monkeypatch.setattr(hub, "_usable", lambda source: probed.append(source) or True)
    hub.apply(settings.Settings())
    assert hub.endpoint() == hub.endpoint() == hub.OFFICIAL
    assert probed == [hub.OFFICIAL]


def test_user_set_hf_endpoint_wins_over_auto(monkeypatch):
    monkeypatch.setattr(hub, "_ENV_ENDPOINT", "https://hub.example.com")
    monkeypatch.setattr(hub, "_usable", lambda source: pytest.fail("自建源不该被探测掉"))
    hub.apply(settings.Settings())
    assert hub.endpoint() == "https://hub.example.com"


# ---------- 探测 ----------


def test_probe_accepts_a_source_that_serves_repo_metadata(monkeypatch):
    session = _session(monkeypatch, {hub.OFFICIAL + hub._PROBE_FILE: {"x-repo-commit": "abc"}})
    assert hub._usable(hub.OFFICIAL) is True
    assert session.calls[0][1]["follow_redirects"] is False


def test_probe_rejects_a_source_that_only_redirects_elsewhere(monkeypatch):
    # hf-mirror.com 对境外 IP 会 308 跳回 huggingface.co：连得上，但实际下不动
    _session(monkeypatch, {hub.MIRROR + hub._PROBE_FILE: {"location": hub.OFFICIAL}})
    assert hub._usable(hub.MIRROR) is False


def test_probe_rejects_a_source_that_cannot_be_reached(monkeypatch):
    _session(monkeypatch, {hub.OFFICIAL + hub._PROBE_FILE: OSError("connect timeout")})
    assert hub._usable(hub.OFFICIAL) is False


def test_probe_works_with_the_requests_based_client(monkeypatch):
    # huggingface_hub 0.x 用 requests，关跳转的参数名跟 httpx 不一样
    session = _session(
        monkeypatch,
        {hub.OFFICIAL + hub._PROBE_FILE: {"x-repo-commit": "abc"}},
        style="requests",
    )
    assert hub._usable(hub.OFFICIAL) is True
    assert session.calls[0][1]["allow_redirects"] is False


# ---------- 取模型 ----------


def test_cached_model_loads_without_touching_the_network(tmp_path, monkeypatch):
    path = _snapshot(tmp_path, "cached")
    monkeypatch.setattr(hub, "endpoint", lambda: pytest.fail("缓存命中就不该联网"))
    calls = []

    def download(local_only):
        calls.append(local_only)
        return path

    assert hub.fetch(download, "识别模型 small") == path
    assert calls == [True]


def test_half_downloaded_cache_is_downloaded_again(tmp_path, monkeypatch):
    partial = _snapshot(tmp_path, "partial", files=("config.json",))
    complete = _snapshot(tmp_path, "complete")
    monkeypatch.setattr(hub, "endpoint", lambda: hub.OFFICIAL)

    def download(local_only):
        return partial if local_only else complete

    assert hub.fetch(download, "识别模型 small") == complete


def test_missing_cache_falls_through_to_downloading(tmp_path, monkeypatch):
    complete = _snapshot(tmp_path, "complete")
    monkeypatch.setattr(hub, "endpoint", lambda: hub.OFFICIAL)
    notes = []

    def download(local_only):
        if local_only:
            raise FileNotFoundError("没下过")
        return complete

    assert hub.fetch(download, "识别模型 small", notify=notes.append) == complete
    assert hub.OFFICIAL in notes[0] and "识别模型 small" in notes[0]


def _failing_fetch(monkeypatch, source):
    monkeypatch.setattr(hub, "endpoint", lambda: source)

    def download(local_only):
        raise OSError("[WinError 10060] 连接尝试失败")

    with pytest.raises(hub.DownloadError) as error:
        hub.fetch(download, "识别模型 small", cache_dir="D:/models")
    return str(error.value)


def test_failed_download_explains_what_to_do(monkeypatch):
    message = _failing_fetch(monkeypatch, hub.OFFICIAL)
    assert "--model-source mirror" in message  # 换镜像
    assert "--proxy" in message  # 走代理
    assert "D:/models" in message  # 手动拷模型
    assert "WinError 10060" in message  # 原始错误别吞


def test_failed_download_on_the_mirror_does_not_suggest_the_mirror(monkeypatch):
    message = _failing_fetch(monkeypatch, hub.MIRROR)
    assert "--model-source mirror" not in message
    assert "--model-source auto" in message


# ---------- 让 huggingface_hub 跟着换源 ----------


def test_switching_source_redirects_huggingface_hub():
    """huggingface_hub 在 import 时就把源固化进模块常量，换源必须能穿透进去。"""
    huggingface_hub = pytest.importorskip("huggingface_hub")

    hub._use(hub.MIRROR)
    assert huggingface_hub.hf_hub_url("Systran/faster-whisper-tiny", "config.json").startswith(
        hub.MIRROR
    )
    assert os.environ["HF_ENDPOINT"] == hub.MIRROR
    # 镜像代理不了 Xet 的分块下载，得关掉，否则照样要连 huggingface 自己的服务器
    assert os.environ["HF_HUB_DISABLE_XET"] == "1"

    hub._use(hub.OFFICIAL)
    assert huggingface_hub.hf_hub_url("Systran/faster-whisper-tiny", "config.json").startswith(
        hub.OFFICIAL
    )


# ---------- 代理 ----------


def test_proxy_goes_into_the_environment_both_stacks_read():
    hub.apply(settings.Settings(proxy="http://127.0.0.1:7890"))
    assert os.environ["HTTP_PROXY"] == "http://127.0.0.1:7890"
    assert os.environ["https_proxy"] == "http://127.0.0.1:7890"


def test_clearing_the_proxy_removes_what_we_set():
    hub.apply(settings.Settings(proxy="http://127.0.0.1:7890"))
    hub.apply(settings.Settings())
    assert "HTTP_PROXY" not in os.environ


def test_clearing_the_proxy_leaves_the_system_one_alone(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://company:8080")
    hub.apply(settings.Settings())
    assert os.environ["HTTP_PROXY"] == "http://company:8080"
