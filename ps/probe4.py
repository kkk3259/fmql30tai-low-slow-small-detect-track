#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe4.py —— 验证 prt-2 是否真的是 bug：
把 BORDER 临时改成 0 再调 run()，如果返回 8 条，说明 run() 的读窗口没问题，
只是 unpack 的边界过滤把全部候选滤掉了（因为它们都在 y=359）。"""
import sys

import cv2

sys.path.insert(0, "/root/ip2")
import cam3d_test as C  # noqa: E402

print("BORDER 原值 =", C.BORDER, flush=True)
pl = C.PL3D()
img = cv2.imread("/root/ip2/t2_twodrones.png")
g = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (640, 360),
               interpolation=cv2.INTER_AREA)

c, st, dt = pl.run(g)
print("BORDER=24 -> n=%d  STATUS=0x%08x" % (len(c), st), flush=True)

C.BORDER = 0
c2, st2, dt2 = pl.run(g)
print("BORDER=0  -> n=%d  STATUS=0x%08x" % (len(c2), st2), flush=True)
for k in c2[:8]:
    print("     x=%4d y=%3d area=%4d peak=%3d" % (k["x"], k["y"], k["area"], k["peak"]), flush=True)
C.BORDER = 24
print("PROBE4_DONE")
