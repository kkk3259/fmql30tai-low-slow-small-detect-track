#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scale_test.py —— 验证"PS 先缩小再送 PL"能否恢复中等目标的检出。

对同一张图跑三种尺度：
  全尺度 640x360   （现状）
  1/2     320x180  → 放大回 640 显示
  1/3     213x120
"""
import sys

import cv2

sys.path.insert(0, "/root/ip2")
from cam3d_test import PL3D  # noqa: E402
from yolo_det import Yolo   # noqa: E402

W, H = 640, 360
pl = PL3D()
y = Yolo(dev=pl.dev)
print("ready", flush=True)


def run_scale(gray, scale, shift):
    """scale=1 表示原尺度；返回 (候选, 判出数, top)"""
    if scale == 1:
        small, xf = gray, 1.0
    else:
        sw, sh = int(W * scale) // 1, int(H * scale) // 1
        small = cv2.resize(gray, (sw, sh), interpolation=cv2.INTER_AREA)
        small = cv2.copyMakeBorder(small, 0, H - sh, 0, W - sw,
                                   cv2.BORDER_CONSTANT, value=0)
        xf = 1.0 / scale
    c, _s, _dt = pl.run(small)
    c = [k for k in c if k["peak"] >= 8]
    out = []
    for k in c:
        x = (k["x"] + shift) % W
        xx, yy = int(x * xf), int(k["y"] * xf)
        if not (4 <= yy < H - 4 and 4 <= xx < W - 4):
            continue
        out.append({"x": xx, "y": yy, "area": int(k["area"] * xf * xf), "peak": k["peak"]})
    out.sort(key=lambda z: -z["peak"])
    keep = out[:16]
    hits = 0
    top = 0.0
    if keep:
        crops, meta = [], []
        for k in keep:
            side = 96
            x0 = int(min(max(k["x"] - side // 2, 0), W - side))
            y0 = int(min(max(k["y"] - side // 2, 0), H - side))
            crops.append(gray[y0:y0 + side, x0:x0 + side].copy())
        res = y.detect_mosaic(crops, grid=4)
        sc = [r[5] for r in res]
        top = max(sc) if sc else 0.0
        hits = len([v for v in sc if v >= 0.45])
    return out, hits, top


names = ("t4_fourdrones", "t6_plane_bird", "t2_twodrones", "t3_field_drone")
for name in names:
    img = cv2.imread("/root/ip2/%s.png" % name)
    if img is None:
        continue
    g = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (W, H), interpolation=cv2.INTER_AREA)
    line = []
    for sc in (1.0, 0.5, 1.0 / 3.0):
        cands, hits, top = run_scale(g, sc, 0)
        line.append("x%.2f:n=%2d/hit=%2d/top=%.2f" % (1 / sc, len(cands), hits, top))
    print("%-16s %s" % (name, "  ".join(line)), flush=True)
print("SCALE_DONE")
