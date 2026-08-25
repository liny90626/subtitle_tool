"""打包后处理：把 exe 的线程栈调大。

Windows 上线程默认栈只有 1.91MB（PyInstaller 引导器写在 PE 头里的），Linux 是 8MB——
转写长片时 CTranslate2 的工作线程会踩爆它，进程以 0xC00000FD 直接消失，而且在 Linux 上
永远复现不出来。这里验证改 PE 头这件事本身是安全的。
"""

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import patch_stack

OPTIONAL = 0x80 + 24


def _fake_exe(reserve=1 << 20):
    """凑一个刚好够解析的 PE32+ 头。"""
    data = bytearray(1024)
    data[0:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<H", data, OPTIONAL, 0x20B)
    struct.pack_into("<Q", data, OPTIONAL + 72, reserve)
    struct.pack_into("<I", data, OPTIONAL + 64, 0)
    return data


def _write(tmp_path, data):
    path = tmp_path / "SubtitleTool.exe"
    path.write_bytes(bytes(data))
    return path


def test_stack_reserve_is_raised(tmp_path):
    path = _write(tmp_path, _fake_exe())
    assert patch_stack.patch(str(path)) == 1 << 20
    data = path.read_bytes()
    assert struct.unpack_from("<Q", data, OPTIONAL + 72)[0] == patch_stack.STACK_RESERVE


def test_the_checksum_is_recomputed(tmp_path):
    path = _write(tmp_path, _fake_exe())
    patch_stack.patch(str(path))
    data = path.read_bytes()
    stored = struct.unpack_from("<I", data, OPTIONAL + 64)[0]
    assert stored == patch_stack.checksum(data, OPTIONAL + 64)


def test_the_file_keeps_its_size(tmp_path):
    path = _write(tmp_path, _fake_exe())
    before = path.stat().st_size
    patch_stack.patch(str(path))
    assert path.stat().st_size == before


def test_an_already_big_stack_is_left_alone(tmp_path):
    path = _write(tmp_path, _fake_exe(reserve=64 << 20))
    before = path.read_bytes()
    assert patch_stack.patch(str(path)) == 64 << 20
    assert path.read_bytes() == before


def test_patching_twice_changes_nothing_the_second_time(tmp_path):
    path = _write(tmp_path, _fake_exe())
    patch_stack.patch(str(path))
    once = path.read_bytes()
    patch_stack.patch(str(path))
    assert path.read_bytes() == once


def test_a_non_pe_file_is_not_touched(tmp_path):
    # Linux 上打出来的是 ELF，同一段代码不能把它写坏
    path = tmp_path / "SubtitleTool"
    path.write_bytes(b"\x7fELF" + b"\0" * 200)
    before = path.read_bytes()
    assert patch_stack.patch(str(path)) == 0
    assert path.read_bytes() == before
