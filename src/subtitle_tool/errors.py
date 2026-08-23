"""跨模块共用的异常。放在依赖链最底层，谁都 import 得到。"""


class Cancelled(Exception):
    """用户中途取消任务。"""


class DownloadError(RuntimeError):
    """模型下载失败。消息里带着照着做就能解决的办法。"""
