#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# alias_check.py —— 判断 0x4000_00xx 读到的到底是不是我们自己的寄存器（地址别名）
import mmap
import os
import struct

BASE_A = 0x43C00000   # 我们的 IP（BD 里设定的基址）
BASE_B = 0x40000000   # AI_Mate 官方段

fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)


def rd(base, off):
    m = mmap.mmap(fd, 0x1000, mmap.MAP_SHARED, prot=mmap.PROT_READ | mmap.PROT_WRITE, offset=base)
    v = struct.unpack_from("<I", m, off)[0]
    m.close()
    return v


print("off   0x43C00000+off   0x40000000+off   same?")
for off in (0x00, 0x04, 0x0C, 0x14, 0x18, 0x1C, 0x20):
    a = rd(BASE_A, off)
    b = rd(BASE_B, off)
    print("0x%02X  0x%08X       0x%08X       %s" % (off, a, b, "同一寄存器!" if a == b else "不同"))

# 写一个明显不同的值到我们的 FRAME_ADDR，再看 0x40000004 跟不跟着变
m = mmap.mmap(fd, 0x1000, mmap.MAP_SHARED, prot=mmap.PROT_READ | mmap.PROT_WRITE, offset=BASE_A)
struct.pack_into("<I", m, 0x04, 0x30140000)
m.close()
print("写入 0x43C00004 = 0x30140000 后：")
print("  0x43C00004 = 0x%08X" % rd(BASE_A, 0x04))
print("  0x40000004 = 0x%08X" % rd(BASE_B, 0x04))
os.close(fd)
