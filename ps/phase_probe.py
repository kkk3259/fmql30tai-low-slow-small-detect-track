#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""phase_probe.py —— 单次进程内测一次相位：跑 t2，打印候选 x。

用法：连跑多次（每次都是新进程），看 x 是否恒定。
"""
import sys

import cv2

sys.path.insert(0, "/root/ip2")
from cam3d_test import PL3D  # noqa: E402

W, H = 640, 360
img = cv2.imread("/root/ip2/t2_twodrones.png")
gray = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (W, H),
                  interpolation=cv2.INTER_AREA)
pl = PL3D()
c, st, dt = pl.run(gray)
xs = sorted([(z["peak"], z["x"], z["y"]) for z in c], reverse=True)[:4]
print("n=%d dt=%.1f  top=%s" % (len(c), dt, xs))
