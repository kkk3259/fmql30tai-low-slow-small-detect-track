#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# probe_bg.py —— 用“纯背景 / 单个大方块”两种图，判断链上数据到底对不对
import sys, time
sys.path.insert(0, '/tmp')
import pl_debug as P

W, H = 640, 360
m, phys, size = P.open_udmabuf()
rm = P.RegMap()
rm.wr(0x04, 0x30100000)
rm.wr(0x08, 0x30240000)

DBGS = (("DBG0", 0x18), ("DBG1", 0x1C), ("DBG2", 0x20), ("DBG3", 0x24),
        ("DBG4", 0x28), ("DBG5", 0x2C), ("DBG6", 0x30), ("DBG7", 0x34))


def run(tag):
    rm.wr(0x00, 1)
    t0 = time.time()
    st = 0
    while time.time() - t0 < 3.0:
        st = rm.rd(0x0C)
        if st & 0x2:
            break
        time.sleep(0.002)
    print("%s  STATUS=0x%08X  n=%d err=%d" % (tag, st, (st >> 8) & 0xFF, (st >> 2) & 1))
    for name, a in DBGS:
        print("    %s = 0x%08X" % (name, rm.rd(a)))
    raw = bytes(m[0x140000:0x140000 + 36])
    print("    RES = %s" % raw.hex())
    n = raw[0]
    for k in range(min(n, 5)):
        e = raw[1 + 7 * k: 8 + 7 * k]
        print("      #%d x=%d y=%d area=%d peak=%d" % (k + 1, (e[0] << 8) | e[1],
              (e[2] << 8) | e[3], (e[4] << 8) | e[5], e[6]))


print("=== 1) 全背景 (=8)，理论上应该 0 个候选 ===")
m[0:W * H] = bytes([8]) * (W * H)
run("背景")

print("")
print("=== 2) 20x20 大方块 240 @ (300,180)，应该检出 1 个 ===")
buf = bytearray([8]) * (W * H)
for y in range(170, 190):
    for x in range(290, 310):
        buf[y * W + x] = 240
m[0:W * H] = bytes(buf)
run("方块")

print("")
print("=== 3) 回读帧缓冲头部 16 字节（确认写入生效）===")
print("    " + bytes(m[0:16]).hex())
