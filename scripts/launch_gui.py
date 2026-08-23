"""PyInstaller 打包入口。"""

import multiprocessing

from subtitle_tool.gui import main

if __name__ == "__main__":
    # Windows 上 CTranslate2/onnxruntime 的工作进程会重新执行本文件，
    # 不冻结的话会不断弹出新窗口
    multiprocessing.freeze_support()
    raise SystemExit(main())
