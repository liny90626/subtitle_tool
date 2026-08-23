import json
import os

import pytest

from subtitle_tool import settings


@pytest.fixture(autouse=True)
def config_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))


def test_round_trip():
    settings.save(settings.Settings("https://hf-mirror.com", "http://127.0.0.1:7890", "en"))
    assert settings.load() == settings.Settings(
        "https://hf-mirror.com", "http://127.0.0.1:7890", "en"
    )


def test_missing_file_gives_defaults():
    assert settings.load() == settings.Settings()


def test_broken_file_gives_defaults():
    os.makedirs(os.path.dirname(settings.path()), exist_ok=True)
    with open(settings.path(), "w", encoding="utf-8") as handle:
        handle.write("{ 这不是 json")
    # 设置文件坏掉不该让程序起不来
    assert settings.load() == settings.Settings()


def test_partial_file_keeps_defaults_for_the_rest():
    os.makedirs(os.path.dirname(settings.path()), exist_ok=True)
    with open(settings.path(), "w", encoding="utf-8") as handle:
        json.dump({"proxy": "http://127.0.0.1:7890"}, handle)
    assert settings.load() == settings.Settings(proxy="http://127.0.0.1:7890")


def test_saved_file_is_readable_json():
    settings.save(settings.Settings(language="zh"))
    with open(settings.path(), encoding="utf-8") as handle:
        assert json.load(handle) == {"source": "auto", "proxy": "", "language": "zh"}
