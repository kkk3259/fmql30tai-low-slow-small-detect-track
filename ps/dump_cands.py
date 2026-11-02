#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dump_cands.py —— 打印 PL 输出的全部候选（不排序、不过滤），看真目标排第几。"""
import sys

import cv2

sys.path.insert(0, "/root/ip2")
from cam3d_test import PL3D  # noqa: E402

W, H = 640, 360
pl = PL3D()
for name in ("t4_fourdrones", "t6_plane_bird", "t2_twodrones"):
    img = cv2.imread("/root/ip2/%s.png" % name)
    if img is None:
        continue
    g = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (W, H), interpolation=cv2.INTER_AREA)
    for tag, src in (("正", g), ("反", 255 - g)):
        c, st, dt = pl.run(src)
        print("== %s [%s] n=%d  st=0x%08x dt=%.1f" % (name, tag, len(c), st, dt), flush=True)
        for i, k in enumerate(c):
            print("   #%d x=%3d y=%3d area=%4d peak=%3d" % (i, k["x"], k["y"], k["area"], k["peak"]),
                  flush=True)
print("DUMP_DONE")
