import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

DATA = os.path.join(os.path.dirname(__file__), "data")


@pytest.fixture(autouse=True)
def chinese_interface():
    """断言里写的是中文文案，别让跑测试的机器语言把结果搅了。"""
    from subtitle_tool import i18n

    i18n.use("zh")
