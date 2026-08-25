"""子进程驱动：崩了要重试，一直崩要放弃，起不来要退回本进程。

原生层崩掉（非法指令、跨不出线程的 C++ 异常、分配失败后 abort）在同一个进程里谁都
接不住，所以流水线放进了子进程。这里用假的子进程把三条路都走一遍。
"""

import queue

import pytest

from subtitle_tool import worker
from subtitle_tool.pipeline import Options


class _FakeChannel:
    def __init__(self, messages):
        self.messages = list(messages)

    def get(self, timeout=None):
        if self.messages:
            return self.messages.pop(0)
        raise queue.Empty

    def close(self):
        pass

    def join_thread(self):
        pass


class _FakeProcess:
    """消息发完就"没了"：没发 finished 就当作被系统干掉了。"""

    exitcode = -11

    def __init__(self, channel):
        self.channel = channel
        self.terminated = False

    def is_alive(self):
        return bool(self.channel.messages)

    def join(self, timeout=None):
        pass

    def terminate(self):
        self.terminated = True


class _FakeEvent:
    def __init__(self):
        self.value = False

    def set(self):
        self.value = True

    def is_set(self):
        return self.value


def _pair(messages):
    channel = _FakeChannel(messages)
    return _FakeProcess(channel), channel, _FakeEvent()


def _jobs(count=1):
    return [worker.Job(row, f"{row}.mp4", Options()) for row in range(count)]


def _recorder():
    seen = {"done": [], "failed": [], "retry": 0, "give_up": []}
    return seen, worker.Events(
        done=lambda row, result: seen["done"].append(row),
        failed=lambda row, message: seen["failed"].append(row),
        retry=lambda: seen.__setitem__("retry", seen["retry"] + 1),
        give_up=lambda row: seen["give_up"].append(row),
    )


def test_a_normal_run_needs_only_one_child():
    calls = []

    def spawn(jobs, setup):
        calls.append(setup)
        return _pair([("done", 0, "结果"), ("finished",)])

    seen, events = _recorder()
    worker.drive(_jobs(), worker.Setup("tiny", "cpu", "nllb-600m"), events, spawn=spawn)
    assert len(calls) == 1 and seen["done"] == [0] and seen["retry"] == 0


def test_a_crashed_child_is_retried_with_a_safer_setup():
    """崩了要换更保守的配置再来一次，而不是把整个程序带走。"""
    calls = []

    def spawn(jobs, setup):
        calls.append(setup)
        if len(calls) == 1:
            return _pair([("progress", 0, "语音转写", 0.1)])  # 没有 finished ＝ 崩了
        return _pair([("done", 0, "结果"), ("finished",)])

    seen, events = _recorder()
    worker.drive(_jobs(), worker.Setup("small", "cpu", "nllb-600m"), events, spawn=spawn)
    assert len(calls) == 2
    assert calls[0].window_seconds is None
    assert (calls[1].window_seconds, calls[1].batch_size) == (worker.SAFE_WINDOW, worker.SAFE_BATCH)
    assert seen["retry"] == 1 and seen["done"] == [0]


def test_a_child_that_keeps_crashing_gives_up_and_moves_on():
    """保守配置也崩：这一条如实标失败，后面的照跑。"""
    calls = []

    def spawn(jobs, setup):
        calls.append(jobs)
        if len(calls) <= 2:
            return _pair([("progress", jobs[0].row, "语音转写", 0.1)])
        return _pair([("done", job.row, "结果") for job in jobs] + [("finished",)])

    seen, events = _recorder()
    worker.drive(_jobs(2), worker.Setup("small", "cpu", "nllb-600m"), events, spawn=spawn)
    assert seen["give_up"] == [0]  # 第一个放弃
    assert seen["done"] == [1]  # 第二个照常做完


def test_finished_files_are_not_redone_after_a_crash():
    calls = []

    def spawn(jobs, setup):
        calls.append([job.row for job in jobs])
        if len(calls) == 1:
            return _pair([("done", 0, "结果"), ("progress", 1, "语音转写", 0.1)])
        return _pair([("done", job.row, "结果") for job in jobs] + [("finished",)])

    seen, events = _recorder()
    worker.drive(_jobs(3), worker.Setup("small", "cpu", "nllb-600m"), events, spawn=spawn)
    assert calls[0] == [0, 1, 2]
    assert calls[1] == [1, 2]  # 做完的不重做
    assert sorted(seen["done"]) == [0, 1, 2]


def test_spawn_failure_falls_back_to_running_here(monkeypatch):
    """子进程完全起不来时退回本进程，至少还能用。"""

    class FakeEngine:
        def __init__(self, *args, **kwargs):
            self.force_profile = None

        def run(self, path, options, progress=None, cancel=None):
            return f"{path} 的结果"

    monkeypatch.setattr("subtitle_tool.pipeline.Engine", FakeEngine)

    def cannot_spawn(jobs, setup):
        raise OSError("spawn 失败")

    seen, events = _recorder()
    worker.drive(_jobs(2), worker.Setup("tiny", "cpu", "nllb-600m"), events, spawn=cannot_spawn)
    assert seen["done"] == [0, 1]


def test_cancelling_stops_between_files():
    cancel = _FakeEvent()
    cancel.set()

    def spawn(jobs, setup):
        pytest.fail("已经取消了就不该再起子进程")

    seen, events = _recorder()
    worker.drive(
        _jobs(2), worker.Setup("tiny", "cpu", "nllb-600m"), events, cancel=cancel, spawn=spawn
    )
    assert seen["done"] == []
