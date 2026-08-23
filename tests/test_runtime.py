import os
import sys
import traceback

import pytest

from subtitle_tool import runtime

# ---------- 缺失的标准流 ----------


def test_missing_streams_are_replaced(monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    runtime.silence_missing_streams()
    # 窗口模式下这几件事以前都会抛 AttributeError，把界面拖死
    print("不该炸")
    traceback.print_exc(file=sys.stderr)
    sys.stderr.write("也不该炸")
    sys.stderr.flush()
    assert sys.stdout.isatty() is False


def test_real_streams_are_left_alone():
    before = (sys.stdout, sys.stderr)
    runtime.silence_missing_streams()
    assert (sys.stdout, sys.stderr) == before


# ---------- 覆盖安装的残留 ----------


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    """假装是打包后的程序，``_internal`` 就是 tmp_path。"""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    return tmp_path


def _ship(root, *names):
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
    (root / "shipped.txt").write_text("\n".join(names), encoding="utf-8")


def test_nothing_is_touched_when_running_from_source(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert runtime.clean_leftovers() == 0


def test_files_outside_the_manifest_are_removed(frozen):
    _ship(frozen, "keep.dll", "pkg/keep.pyd")
    (frozen / "old.dll").write_text("旧版本留下的", encoding="utf-8")
    (frozen / "gone").mkdir()
    (frozen / "gone" / "stale.pyd").write_text("旧版本留下的", encoding="utf-8")

    assert runtime.clean_leftovers() == 2
    assert (frozen / "keep.dll").exists() and (frozen / "pkg" / "keep.pyd").exists()
    assert not (frozen / "old.dll").exists()
    assert not (frozen / "gone").exists()  # 空目录一并收掉


def test_manifest_and_marker_survive_the_sweep(frozen):
    _ship(frozen, "keep.dll")
    runtime.clean_leftovers()
    assert (frozen / "shipped.txt").exists()
    assert (frozen / "cleaned.txt").exists()


def test_the_sweep_runs_once_per_version(frozen):
    _ship(frozen, "keep.dll")
    assert runtime.clean_leftovers() == 0  # 首次：没有多余文件可删
    (frozen / "later.dll").write_text("x", encoding="utf-8")
    # 版本没变就不再扫——上万个文件的目录不该每次启动都走一遍
    assert runtime.clean_leftovers() == 0
    assert (frozen / "later.dll").exists()


def test_a_new_version_sweeps_again(frozen):
    _ship(frozen, "keep.dll")
    runtime.clean_leftovers()
    (frozen / "old.dll").write_text("x", encoding="utf-8")
    (frozen / "cleaned.txt").write_text("0.0.1", encoding="utf-8")  # 假装上次是旧版本清的
    assert runtime.clean_leftovers() == 1
    assert not (frozen / "old.dll").exists()


def test_without_a_manifest_nothing_is_deleted(frozen):
    (frozen / "mystery.dll").write_text("x", encoding="utf-8")
    assert runtime.clean_leftovers() == 0
    assert (frozen / "mystery.dll").exists()


def test_cache_lives_outside_the_program_directory():
    """升级只覆盖程序目录，几百 MB 的模型必须留在用户目录下。"""
    from subtitle_tool.hub import _default_cache

    cache = os.path.abspath(_default_cache())
    assert cache.startswith(os.path.abspath(os.path.expanduser("~")))


# ---------- 崩溃留痕 ----------


def test_uncaught_exceptions_are_written_to_the_log(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    passed_on = []
    monkeypatch.setattr(sys, "excepthook", lambda *args: passed_on.append(args))
    runtime.report_crashes()
    try:
        raise ValueError("界面就是这么没的")
    except ValueError:
        sys.excepthook(*sys.exc_info())

    with open(runtime.log_path(), encoding="utf-8") as handle:
        assert "界面就是这么没的" in handle.read()
    assert passed_on, "有控制台时原来的钩子还得照旧把堆栈打出来"


def test_the_log_sits_next_to_the_settings(tmp_path, monkeypatch):
    from subtitle_tool import settings

    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert os.path.dirname(runtime.log_path()) == os.path.dirname(settings.path())


def test_a_mismatched_manifest_deletes_nothing(frozen):
    _ship(frozen, "keep.dll")
    for index in range(5):
        (frozen / f"stray{index}.dll").write_text("x", encoding="utf-8")
    # 要删的比该留的还多：多半是解压不全或清单写坏了。这时候删下去就是毁掉安装目录
    assert runtime.clean_leftovers() == 0
    assert (frozen / "stray0.dll").exists()


# ---------- 槽函数兜底 ----------


def test_only_as_many_arguments_as_the_slot_takes():
    """Qt 给 clicked 发 checked、给 currentIndexChanged 发下标，多的得截掉。"""
    seen = []
    runtime.guarded(lambda: seen.append(()))(True)
    runtime.guarded(lambda a: seen.append((a,)))(1, 2, 3)
    runtime.guarded(lambda a, b: seen.append((a, b)))(1, 2, 3)
    assert seen == [(), (1,), (1, 2)]


def test_an_exception_in_a_slot_is_reported_not_fatal(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    reported = []
    runtime.guarded(lambda: 1 / 0, reported.append)()  # 不抛出来就算过
    assert "ZeroDivisionError" in reported[0]
    with open(runtime.log_path(), encoding="utf-8") as handle:
        assert "ZeroDivisionError" in handle.read()


def test_a_healthy_slot_still_returns_its_value():
    assert runtime.guarded(lambda a: a * 2)(21) == 42
