#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""prep_sweep.py —— 不需要摄像头：对静态图扫描 PS 侧预处理，看能否让中等目标产生候选。

每次只跑一遍 PL（避免"连跑两遍触发被吞"），预处理变体：
  raw   原灰度
  g1.0/g0.5/g0.3/g0.15   gamma
  clahe CLAHE(4.0)
  clahe+g0.3
统计：候选总数 + 落在目标附近(曼哈顿<40)的候选数 + 其中最大 peak
"""
import sys

import cv2
import numpy as np

sys.path.insert(0, "/root/ip2")
from cam3d_test import PL3D  # noqa: E402

W, H = 640, 360
TARGETS = {
    "t6_plane_bird": [(200, 268), (383, 180)],
    "t4_fourdrones": [(130, 152), (300, 176), (455, 118), (487, 232)],
    "t2_twodrones": [(165, 92), (487, 248)],
}
PL = PL3D()


def preps(g):
    out = [("raw", g)]
    for gm in (1.0, 0.5, 0.3, 0.15):
        tb = np.clip(255.0 * ((np.arange(256, dtype=np.float32) / 255.0) ** gm), 0, 255).astype(np.uint8)
        out.append(("g%.2f" % gm, cv2.LUT(g, tb)))
    cl = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8))
    out.append(("clahe", cl.apply(g)))
    tb3 = np.clip(255.0 * ((np.arange(256, dtype=np.float32) / 255.0) ** 0.3), 0, 255).astype(np.uint8)
    out.append(("clahe+g0.3", cl.apply(cv2.LUT(g, tb3))))
    return out


print("ready", flush=True)
for name, tgt in TARGETS.items():
    img = cv2.imread("/root/ip2/%s.png" % name)
    if img is None:
        print("%-16s IMG_FAIL" % name, flush=True)
        continue
    g0 = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (W, H), interpolation=cv2.INTER_AREA)
    for tag, g in preps(g0):
        c, _st, _dt = PL.run(np.ascontiguousarray(g))
        hit, best = 0, 0
        for tx, ty in tgt:
            near = [k for k in c if abs(k["x"] - tx) + abs(k["y"] - ty) < 40]
            if near:
                hit += 1
                best = max(best, max(k["peak"] for k in near))
        print("%-16s %-11s n=%2d  命中 %d/%d  best_peak=%3d"
              % (name, tag, len(c), hit, len(tgt), best), flush=True)
print("SWEEP_DONE")
