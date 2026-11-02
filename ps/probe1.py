#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe1.py —— 单跑一次，确认 PL 在 t2 上正常出候选（排除 gamma_sweep 的脚本 bug）。"""
import sys

import cv2

sys.path.insert(0, "/root/ip2")
from cam3d_test import PL3D  # noqa: E402

pl = PL3D()
img = cv2.imread("/root/ip2/t2_twodrones.png")
g = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (640, 360),
               interpolation=cv2.INTER_AREA)
print("shape=%s dtype=%s contig=%s" % (g.shape, g.dtype, g.flags["C_CONTIGUOUS"]), flush=True)
c, st, dt = pl.run(g)
print("plain n=%d st=%s dt=%.1fms" % (len(c), hex(st), dt), flush=True)
for k in c[:6]:
    print("   x=%d y=%d area=%d peak=%d" % (k["x"], k["y"], k["area"], k["peak"]), flush=True)
tb = (255.0 * ((__import__("numpy").arange(256, dtype="float32") / 255.0) ** 0.5))
tb = __import__("numpy").clip(tb, 0, 255).astype("uint8")
g2 = cv2.LUT(g, tb)
print("lut dtype=%s contig=%s" % (g2.dtype, g2.flags["C_CONTIGUOUS"]), flush=True)
c2, st2, dt2 = pl.run(g2)
print("lut n=%d st=%s dt=%.1fms" % (len(c2), hex(st2), dt2), flush=True)
print("PROBE1_DONE")
