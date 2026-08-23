"""打包入口：不带参数开图形界面，带参数走命令行。

命令行分支不只是方便脚本化，也让 CI 能无头验证打出来的程序真的加载得起
PyAV / CTranslate2 这些原生库——只启动窗口是验不出来的。
"""

import multiprocessing
import sys

if __name__ == "__main__":
    # CTranslate2 / onnxruntime 的工作进程在 Windows 上会重新执行本文件，
    # 不冻结的话会不断弹出新窗口
    multiprocessing.freeze_support()

    # 这两件事要赶在别的东西之前：窗口模式下没有标准流，任何一次 print 都会炸；
    # 覆盖安装留下的旧 .pyd 可能被抢先加载
    from subtitle_tool import runtime

    runtime.silence_missing_streams()
    runtime.clean_leftovers()

    if len(sys.argv) > 1:
        from subtitle_tool.cli import main
    else:
        from subtitle_tool.gui import main
    raise SystemExit(main())
