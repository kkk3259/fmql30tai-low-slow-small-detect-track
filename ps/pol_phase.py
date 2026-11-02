#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pol_phase.py —— 检查"正极性"与"反极性"两遍的列相位是否一致。

若两遍相位不同，同一目标会在 x 和 x+62 各出一组候选 → 画面看起来双框/跳动。
"""
import sys

import cv2

sys.path.insert(0, "/root/ip2")
from cam3d_test import PL3D  # noqa: E402

W, H = 640, 360
img = cv2.imread("/root/ip2/t2_twodrones.png")
gray = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (W, H), interpolation=cv2.INTER_AREA)
pl = PL3D()
print("ready", flush=True)


def xs(c):
    return sorted([(c["x"], c["peak"]) for c in c if c["peak"] >= 8])


for k in range(5):
    a, _s, _d = pl.run(gray)
    b, _s2, _d2 = pl.run(255 - gray)
    print("round%d  pos=%s  inv=%s" % (k, xs(a)[:6], xs(b)[:6]), flush=True)
print("POL_PHASE_DONE")
