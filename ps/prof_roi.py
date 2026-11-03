# -*- coding: utf-8 -*-
"""prof_roi.py — 拆解网页 ROI 路径（PL / 聚类 / 裁剪 / mosaic / 融合）耗时。"""
import sys
import time

import cv2

sys.path.insert(0, "/root/ip2")
from cam3d_test import PL3D  # noqa: E402
from yolo_det import Yolo  # noqa: E402

VID = sys.argv[1] if len(sys.argv) > 1 else "/root/user2.mp4"
W, H = 640, 360

cap = cv2.VideoCapture(VID)
pl = PL3D()
y = Yolo(dev=pl.dev)
print("ready", flush=True)

for k in range(3):
    ok, f = cap.read()
    if not ok:
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        ok, f = cap.read()
    f = cv2.resize(f, (640, 480))
    t0 = time.time()
    gray = cv2.cvtColor(f[60:420, :], cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, (W, H), interpolation=cv2.INTER_LINEAR)
    t1 = time.time()
    cands, _st, _dt = pl.run(gray)
    t2 = time.time()
    c1, _s2, _dt2 = pl.run(255 - gray)
    t3 = time.time()
    all_c = cands + c1
    for c in all_c:
        c["x"] = (c["x"] + 64) % W
    keep = sorted([c for c in all_c if c["area"] >= 4 and c["peak"] >= 8],
                  key=lambda z: -z["peak"])[:16]
    t4 = time.time()
    crops, meta = [], []
    for c in keep:
        sd = int(min(max(96, 3.0 * (c["area"] ** 0.5)), 128))
        x0 = int(min(max(c["x"] - sd // 2, 0), W - sd))
        y0 = int(min(max(c["y"] - sd // 2, 0), H - sd))
        crops.append(gray[y0:y0 + sd, x0:x0 + sd].copy())
        meta.append((x0, y0, sd))
    t5 = time.time()
    res = y.detect_mosaic(crops, grid=4) if crops else []
    t6 = time.time()
    print("f%d cand=%d crops=%d hits=%d | gray %.1f pl1 %.1f pl2 %.1f "
          "select %.1f crop %.1f mosaic %.1f ms" % (
              k, len(all_c), len(crops), len(res),
              (t1 - t0) * 1000, (t2 - t1) * 1000, (t3 - t2) * 1000,
              (t4 - t3) * 1000, (t5 - t4) * 1000, (t6 - t5) * 1000), flush=True)
    if res:
        print("   top scores:", [round(r[5], 3) for r in sorted(res, key=lambda z: -z[5])[:5]],
              flush=True)
