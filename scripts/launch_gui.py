"""打包入口：不带参数开图形界面，带参数走命令行。

命令行分支不只是方便脚本化，也让 CI 能无头验证打出来的程序真的加载得起
PyAV / CTranslate2 这些原生库——只启动窗口是验不出来的。
"""

import multiprocessing
import sys

if __name__ == "__main__":
    # 补标准流必须排在 freeze_support 之前：窗口模式下没有标准流，任何一次 print 都会炸，
    # 而 freeze_support 在子进程里根本不会返回——排在后面的话子进程就补不上了
    from subtitle_tool import runtime

    runtime.silence_missing_streams()

    # 流水线和 CTranslate2 / onnxruntime 的工作进程都会重新执行本文件，
    # 不冻结的话会不断弹出新窗口
    multiprocessing.freeze_support()

    runtime.report_crashes()
    runtime.clean_leftovers()

    if len(sys.argv) > 1:
        from subtitle_tool.cli import main
    else:
        from subtitle_tool.gui import main
    raise SystemExit(main())
