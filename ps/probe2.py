#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe2.py —— PL 已在跑（15.5ms、frm_cnt=1、n_cand=8）但候选表窗口读回 0。
逐个排查：是否需要在索引写与数据读之间加延时。"""
import sys
import time

import cv2

sys.path.insert(0, "/root/ip2")
import cam3d_test as C  # noqa: E402
from cam3d_test import PL3D  # noqa: E402

pl = PL3D()
img = cv2.imread("/root/ip2/t2_twodrones.png")
g = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (640, 360),
               interpolation=cv2.INTER_AREA)
c, st, dt = pl.run(g)
print("run: n=%d st=0x%08x dt=%.1fms" % (len(c), st, dt), flush=True)

# 直接读原始窗口字，看是什么
for delay in (0.0, 0.0005, 0.002, 0.010):
    words = []
    for i in range(4):
        pl.reg.write(C.REG + C.R_WIN, i)
        if delay:
            time.sleep(delay)
        pl.reg.read(C.REG + C.R_WIN)
        words.append(pl.reg.read(C.REG + C.R_WIN) & 0xFFFFFFFF)
    print("delay=%.4f words=%s" % (delay, ["%08x" % w for w in words]), flush=True)

st = pl.reg.read(C.REG + C.R_STATUS) & 0xFFFFFFFF
print("STATUS=0x%08x  frm=%d ncand=%d" % (st, (st >> 16) & 0xFF, (st >> 8) & 0xFF), flush=True)
print("PROBE2_DONE")
