"""把打包出来的 exe 的线程默认栈调大。

Windows 上线程栈的默认大小写在 PE 头的 ``SizeOfStackReserve`` 里，PyInstaller 的引导器
给的是 1.91MB；Linux 的线程默认 8MB。同一份代码在 Linux 上怎么跑都没事、到 Windows 上
转写长片时却以 0xC00000FD（STATUS_STACK_OVERFLOW）整个进程消失，差的就是这个。

CTranslate2 / onnxruntime 自己起的工作线程不指定栈大小，拿的也是这个默认值，所以只能从
PE 头上改。exe 没有签名（改字节不会破坏签名），校验和按标准算法重算。
"""

import struct
import sys

#: 调到 16MB。这是保留的地址空间不是真占内存，64 位下随便留
STACK_RESERVE = 16 * 1024 * 1024


def checksum(data: bytes, field: int) -> int:
    """PE 校验和：校验和字段按 0 算，16 位累加回卷，最后加上文件长度。"""
    total = 0
    for index in range(0, len(data) - len(data) % 2, 2):
        if field <= index < field + 4:
            continue
        total += data[index] | (data[index + 1] << 8)
        total = (total & 0xFFFF) + (total >> 16)
    if len(data) % 2:
        total += data[-1]
        total = (total & 0xFFFF) + (total >> 16)
    total = (total & 0xFFFF) + (total >> 16)
    return (total + len(data)) & 0xFFFFFFFF


def patch(path: str, reserve: int = STACK_RESERVE) -> int:
    """就地调大 ``path`` 的栈保留大小，返回原来的值。非 PE 文件直接返回 0。"""
    with open(path, "rb") as handle:
        data = bytearray(handle.read())
    if data[:2] != b"MZ":
        return 0
    header = struct.unpack_from("<I", data, 0x3C)[0]
    if bytes(data[header : header + 4]) != b"PE\0\0":
        return 0
    optional = header + 24
    wide = struct.unpack_from("<H", data, optional)[0] == 0x20B
    field = optional + 72
    before = struct.unpack_from("<Q" if wide else "<I", data, field)[0]
    if before >= reserve:
        return before
    struct.pack_into("<Q" if wide else "<I", data, field, reserve)

    csum = optional + 64
    struct.pack_into("<I", data, csum, checksum(bytes(data), csum))
    with open(path, "wb") as handle:
        handle.write(data)
    return before


if __name__ == "__main__":
    for target in sys.argv[1:]:
        was = patch(target)
        print(f"{target}: stack reserve {was / 1048576:.2f}MB -> {STACK_RESERVE / 1048576:.0f}MB")
