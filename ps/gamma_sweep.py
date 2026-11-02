#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gamma_sweep.py —— 扫描 PS 侧 gamma，看能否让中等目标的边缘响应过 CFAR 门限。

原理：k/floor 是 RTL 编译期参数，改不了；但 gamma 变换会改变局部对比度，
      是 PS 侧唯一能立刻试的等效手段。
对每张图跑多个 gamma，统计"落在目标附近"的候选数与 peak。
"""
import sys

import cv2
import numpy as np

sys.path.insert(0, "/root/ip2")
from cam3d_test import PL3D  # noqa: E402

W, H = 640, 360
# 各图目标真值位置（640x360 坐标，人工读图得到）
TARGETS = {
    "t6_plane_bird": [(200, 268), (383, 180)],
    "t4_fourdrones": [(130, 152), (300, 176), (455, 118), (487, 232)],
    "t2_twodrones": [(165, 92), (487, 248)],
}
PL = PL3D()


def lut(g):
    x = np.arange(256, dtype=np.float32) / 255.0
    return [(gamma, np.clip(255.0 * (x ** gamma), 0, 255).astype(np.uint8)) for gamma in
            (1.0, 0.5, 0.3, 0.15, 0.08)]


L = lut(0)[0:0]
TABLES = [(gm, np.clip(255.0 * ((np.arange(256, dtype=np.float32) / 255.0) ** gm), 0, 255)
                  .astype(np.uint8)) for gm in (1.0, 0.5, 0.3, 0.15, 0.08)]

print("ready", flush=True)
for name, tgt in TARGETS.items():
    img = cv2.imread("/root/ip2/%s.png" % name)
    if img is None:
        print("%-16s IMG_FAIL" % name, flush=True)
        continue
    g0 = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (W, H), interpolation=cv2.INTER_AREA)
    for gm, tb in TABLES:
        g = cv2.LUT(g0, tb)
        cands, _s, _d = PL.run(g)
        for pol, gg in ((1, cv2.LUT(g0, np.clip(255 - tb, 0, 255).astype(np.uint8))),):
            c2, _s2, _d2 = PL.run(gg)
            cands = list(cands) + list(c2)
        hit, best = 0, 0
        for tx, ty in tgt:
            near = [c for c in cands if abs(c["x"] - tx) + abs(c["y"] - ty) < 40]
            if near:
                hit += 1
                best = max(best, max(c["peak"] for c in near))
        print("%-16s gamma=%.2f  n=%2d  命中目标位置 %d/%d  best_peak=%d"
              % (name, gm, len(cands), hit, len(tgt), best), flush=True)
print("GAMMA_DONE")
