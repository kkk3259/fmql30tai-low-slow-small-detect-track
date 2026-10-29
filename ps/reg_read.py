# -*- coding: utf-8 -*-
"""reg_read.py —— 读 PL 寄存器并打印关键字段（用于确认 IP 是否活着、帧状态如何）

用法: python3 reg_read.py [base_hex]   默认 0x43C00000
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


ver = r(0x14)
st = r(0x0C)
print("BASE=0x%08X" % BASE)
print("VERSION = 0x%08X  (%s)" % (ver, "IP 活着" if ver == 0x00010000 else "!!! 不是我们的 IP"))
print("STATUS  = 0x%08X  busy=%d done=%d err=%d n_cand=%d frm_cnt=%d"
      % (st, st & 1, (st >> 1) & 1, (st >> 2) & 1, (st >> 8) & 0xFF, (st >> 16) & 0xFF))
print("CTRL=0x%08X FRAME_ADDR=0x%08X RESULT_ADDR=0x%08X FRAME_ID=0x%08X"
      % (r(0x00), r(0x04), r(0x08), r(0x10)))
for name, addr in (("DBG0", 0x18), ("DBG1", 0x1C), ("DBG2", 0x20), ("DBG3", 0x24)):
    print("%s = 0x%08X" % (name, r(addr)))
m.close()
os.close(f)
