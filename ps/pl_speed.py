#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pl_speed.py —— 单独测 PL 单遍耗时（排除服务循环干扰）。"""
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, "/root/ip2")
from cam3d_test import PL3D  # noqa: E402

W, H = 640, 360
cap = cv2.VideoCapture(0)
print("cap opened:", cap.isOpened(), flush=True)
ok, f = cap.read()
if not ok:
    print("no frame from camera")
    sys.exit(1)
gray = cv2.resize(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (W, H), interpolation=cv2.INTER_AREA)
cap.release()
print("camera frame ok %s" % (gray.shape,), flush=True)

pl = PL3D()
print("PL3D ready", flush=True)
# 1) 单遍
ts = []
for i in range(6):
    _c, _st, dt = pl.run(gray)
    ts.append(dt)
print("单遍 dt: " + " ".join("%.1f" % t for t in ts), flush=True)
# 2) 连续两遍（模拟双极性）
ts2 = []
for i in range(4):
    t0 = time.time()
    pl.run(gray)
    pl.run(255 - gray)
    ts2.append((time.time() - t0) * 1000)
print("连两遍 dt: " + " ".join("%.1f" % t for t in ts2), flush=True)
print("PLSPEED_DONE")
