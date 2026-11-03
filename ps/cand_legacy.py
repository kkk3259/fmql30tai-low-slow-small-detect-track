# -*- coding: utf-8 -*-
"""cand_legacy.py —— 从 0x18 的 9 字兼容视图解码候选（适配 6 位地址的旧构建）

输出: n=总数, 以及表里前 5 个候选 (x, y, area, peak)
"""
import mmap
import os
import struct

BASE = 0x43C00000
f = os.open('/dev/mem', os.O_RDWR | os.O_SYNC)
m = mmap.mmap(f, 4096, offset=BASE)


def r(a):
    return struct.unpack('<I', m[a:a + 4])[0]


st = r(0x0C)
words = [r(0x18 + 4 * i) for i in range(9)]
raw = b''.join(struct.pack('<I', w) for w in words)
n_total = raw[0]
print("STATUS=0x%08X busy=%d done=%d err=%d n_cand=%d frm_cnt=%d"
      % (st, st & 1, (st >> 1) & 1, (st >> 2) & 1, (st >> 8) & 0xFF, (st >> 16) & 0xFF))
print("兼容视图字节0 (n) = %d" % n_total)
n_show = min(5, n_total)
for i in range(n_show):
    b = raw[1 + 7 * i: 1 + 7 * i + 7]
    x = (b[0] << 8) | b[1]
    y = (b[2] << 8) | b[3]
    area = (b[4] << 8) | b[5]
    print("  #%d  (x=%3d, y=%3d)  area=%4d  peak=%3d" % (i + 1, x, y, area, b[6]))
m.close()
os.close(f)
