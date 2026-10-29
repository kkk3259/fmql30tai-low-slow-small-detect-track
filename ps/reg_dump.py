# -*- coding: utf-8 -*-
"""reg_dump.py —— 把 0x00~0x7C 全部读一遍（排查哪个视图有数据）

用法: python3 reg_dump.py [base_hex]
"""
import mmap
import os
import struct
import sys

BASE = int(sys.argv[1], 16) if len(sys.argv) > 1 else 0x43C00000
f = os.open('/dev/mem', os.O_RDWR | os.O_SYNC)
m = mmap.mmap(f, 4096, offset=BASE)


def r(a):
    return struct.unpack('<I', m[a:a + 4])[0]


print("BASE=0x%08X" % BASE)
for a in range(0x00, 0x80, 4):
    print("  [0x%02X] = 0x%08X" % (a, r(a)))
m.close()
os.close(f)
