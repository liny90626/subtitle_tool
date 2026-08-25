"""把整条流水线放进子进程跑。

原生层崩掉——CTranslate2 / onnxruntime 里的非法指令、跨不出线程边界的 C++ 异常、
分配失败后的 abort——是整个进程一起没，在同一个进程里再怎么兜都接不住：日志最后一行
之后什么都没有，界面直接消失。

放进子进程之后，崩的只是子进程：父进程看退出码就知道出了事，能把这一条标成失败、
换一个更保守的配置自动重试，剩下的文件照常处理。界面不会再凭空消失。

进程间只走一个队列，消息都是 ``(类型, ...)`` 元组，内容全是可 pickle 的简单对象。
"""

import multiprocessing
import queue as queue_module
from dataclasses import dataclass, replace
from typing import Optional

#: 子进程被系统干掉后，换这套更保守的配置再试一次
SAFE_WINDOW = 150.0
SAFE_BATCH = 1


@dataclass
class Job:
    """一个待处理的文件。``row`` 用来把结果对回界面上的那一行。"""

    row: int
    path: str
    options: object


@dataclass
class Setup:
    """子进程里重建 Engine 需要的东西。"""

    model_size: str
    device: str
    translate_model: str
    download_root: Optional[str] = None
    window_seconds: Optional[float] = None
    batch_size: Optional[int] = None


def run(jobs, setup: Setup, channel, cancel) -> None:
    """子进程入口：把 ``jobs`` 跑完，进度和结果都从 ``channel`` 发回去。

    这个函数在子进程里执行，模块级导入必须能被 spawn 重新跑一遍，所以重活都在函数里导。
    """
    from . import runtime
    from .errors import Cancelled
    from .pipeline import Engine

    runtime.silence_missing_streams()
    runtime.report_crashes()

    engine = Engine(
        setup.model_size,
        setup.device,
        setup.translate_model,
        setup.download_root,
        lambda message, fraction: channel.put(("note", message, fraction)),
    )
    if setup.window_seconds:  # 保守重试：把粒度写死，不再按内存自动挑
        engine.force_profile = (setup.window_seconds, setup.batch_size)

    for job in jobs:
        if cancel.is_set():
            break
        try:
            result = engine.run(
                job.path,
                job.options,
                progress=lambda stage, fraction, row=job.row: channel.put(
                    ("progress", row, stage, fraction)
                ),
                cancel=cancel,
            )
            channel.put(("done", job.row, result))
        except Cancelled:
            break
        except Exception as error:  # 子进程里出的错原样带回父进程显示
            channel.put(("failed", job.row, f"{error}"))
    channel.put(("finished",))


def start(jobs, setup: Setup):
    """拉起子进程，返回 ``(进程, 队列, 取消信号)``。"""
    context = multiprocessing.get_context("spawn")
    channel = context.Queue()
    cancel = context.Event()
    process = context.Process(target=run, args=(jobs, setup, channel, cancel), daemon=True)
    process.start()
    return process, channel, cancel


@dataclass
class Events:
    """父进程侧的回调。都给了空实现，用得着哪个填哪个。"""

    progress: object = None  # (行号, 阶段, 比例)
    note: object = None  # (消息, 比例或 None)
    done: object = None  # (行号, Result)
    failed: object = None  # (行号, 消息)
    retry: object = None  # 换保守配置重试
    give_up: object = None  # (行号) 保守配置也崩，跳过

    def fire(self, name, *args):
        handler = getattr(self, name)
        if handler is not None:
            handler(*args)


def drive(jobs, setup: Setup, events: Events, cancel=None, spawn=None) -> None:
    """把 ``jobs`` 跑完，子进程崩了就换保守配置重试，再崩就跳过那一条。

    ``cancel`` 是父进程这侧的 :class:`threading.Event`；``spawn`` 只为测试留的口子。
    子进程完全起不来时（打包环境的意外）退回本进程跑，至少还能用。
    """
    from . import runtime

    spawn = spawn or start
    remaining, safe = list(jobs), False
    while remaining and not (cancel is not None and cancel.is_set()):
        try:
            remaining, crashed = _run_batch(remaining, setup, events, cancel, safe, spawn)
        except Exception as error:
            runtime.trace(f"子进程起不来，退回本进程：{error}")
            _run_here(remaining, setup, events, cancel, safe)
            return
        if not crashed:
            return
        if safe:
            # 保守配置还是崩：这一条放弃，继续后面的
            events.fire("give_up", remaining[0].row)
            remaining = remaining[1:]
        else:
            safe = True
            events.fire("retry")


def _run_batch(jobs, setup: Setup, events: Events, cancel, safe: bool, spawn):
    """跑一批，返回 ``(还没做完的, 子进程是不是崩了)``。"""
    from . import runtime

    if safe:
        setup = replace(setup, window_seconds=SAFE_WINDOW, batch_size=SAFE_BATCH)
    runtime.trace(f"启动子进程处理 {len(jobs)} 个文件{'（保守配置）' if safe else ''}")
    process, channel, child_cancel = spawn(jobs, setup)
    pending = {job.row: job for job in jobs}
    try:
        while True:
            for message in drain(channel, 0.2):
                kind = message[0]
                if kind == "finished":
                    return [], False
                if kind in ("done", "failed"):
                    pending.pop(message[1], None)
                events.fire(kind, *message[1:])
            if cancel is not None and cancel.is_set():
                child_cancel.set()
                process.join(15)
                return [], False
            if not process.is_alive():
                # 没等到 finished 就没了：原生层把子进程带走了
                runtime.trace(f"子进程异常退出（退出码 {process.exitcode}）")
                return [pending[row] for row in sorted(pending)], True
    finally:
        if process.is_alive():
            process.terminate()
            process.join(5)
        channel.close()
        channel.join_thread()  # 不收尾的话退出时会报「泄漏了信号量」


def _run_here(jobs, setup: Setup, events: Events, cancel, safe: bool) -> None:
    """子进程用不了时的退路：老办法，在本进程里跑。"""
    from .errors import Cancelled
    from .pipeline import Engine

    engine = Engine(
        setup.model_size,
        setup.device,
        setup.translate_model,
        setup.download_root,
        lambda message, fraction: events.fire("note", message, fraction),
    )
    if safe:
        engine.force_profile = (SAFE_WINDOW, SAFE_BATCH)
    for job in jobs:
        if cancel is not None and cancel.is_set():
            return
        try:
            result = engine.run(
                job.path,
                job.options,
                progress=lambda stage, fraction, row=job.row: events.fire(
                    "progress", row, stage, fraction
                ),
                cancel=cancel,
            )
            events.fire("done", job.row, result)
        except Cancelled:
            return
        except Exception as error:
            events.fire("failed", job.row, f"{error}")


def drain(channel, timeout: float = 0.1):
    """把队列里已有的消息取出来，取不到就返回空。"""
    messages = []
    while True:
        try:
            messages.append(channel.get(timeout=timeout))
        except queue_module.Empty:
            return messages
        timeout = 0  # 第一条等一下，后面有多少拿多少
