#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""phase_rep.py —— 同一张图连跑 6 次，看结果是否可复现。"""
import sys

import cv2

sys.path.insert(0, "/root/ip2")
from cam3d_test import PL3D  # noqa: E402
from yolo_det import Yolo   # noqa: E402

W, H = 640, 360
img = cv2.imread("/root/ip2/t2_twodrones.png")
gray = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (W, H), interpolation=cv2.INTER_AREA)
pl = PL3D()
y = Yolo(dev=pl.dev)
print("ready", flush=True)

for shift in (0, 62):
    line = []
    for k in range(6):
        cands, st, dt = pl.run(gray)
        xs = sorted([(c["x"] + shift) % W for c in cands if c["area"] >= 4 and c["peak"] >= 8])
        hits = 0
        if 0 < len(cands) <= 16:
            keep = [c for c in cands if c["area"] >= 4 and c["peak"] >= 8][:16]
            crops, meta = [], []
            for c in keep:
                cx = (c["x"] + shift) % W
                x0 = int(min(max(cx - 48, 0), W - 96))
                y0 = int(min(max(c["y"] - 48, 0), H - 96))
                crops.append(gray[y0:y0 + 96, x0:x0 + 96].copy())
                meta.append((x0, y0))
            res = y.detect_mosaic(crops, grid=4)
            hits = len([r for r in res if r[5] >= 0.45])
        line.append("n=%d hit=%d xs=%s" % (len(cands), hits, xs[:4]))
    print("shift=%-3d %s" % (shift, " | ".join(line)), flush=True)
print("PHASE_REP_DONE")
