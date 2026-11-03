# -*- coding: utf-8 -*-
"""dump_roi.py —— 抓一帧，把每个候选的裁片存成图，并打印 NPU 判定，用肉眼确认裁片里到底有没有目标。"""
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, "/root/ip2")
import cam3d_pipe as M  # noqa

cap = cv2.VideoCapture(M.find_cam() if hasattr(M, "find_cam") else 0)
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
ok = False
for _ in range(10):
    ok, f = cap.read()
    if ok and f is not None and f.shape[0] > 0:
        break
    time.sleep(0.2)
print("cap ok =", ok, None if not ok else f.shape)

W, H = 640, 360
gray = cv2.cvtColor(f[60:420, :], cv2.COLOR_BGR2GRAY)
gray = cv2.resize(gray, (W, H), interpolation=cv2.INTER_AREA)

# 直接调 cam3d_pipe 里的 pl 全局？不一定有，自己建一个
from cam3d_test import PL3D  # noqa
pl = PL3D()
g = 255 - gray if M.INVERT else gray
cands, st, dt = pl.run(g)
print("PL n=%d dt=%.2f" % (len(cands), dt))

sel = []
for c in cands:
    x = (c["x"] + M.SHIFT[0]) % W
    y = c["y"]
    if y < 24 or x < 8 or x > W - 8:
        continue
    sel.append({"x": x, "y": y, "area": c["area"], "peak": c["peak"]})
sel.sort(key=lambda z: -z["peak"])
sel = sel[:5]
print("sel n=%d" % len(sel))

crops, meta = [], []
for c in sel:
    sd = int(min(max(96, 3.0 * (c["area"] ** 0.5)), 128))
    hx = sd // 2
    x0 = int(min(max(c["x"] - hx, 0), max(0, W - sd)))
    y0 = int(min(max(c["y"] - hx, 0), max(0, H - sd)))
    crops.append(gray[y0:y0 + sd, x0:x0 + sd].copy())
    meta.append((x0, y0, sd))
    print("  cand x=%d y=%d area=%d peak=%d -> crop@(%d,%d) sd=%d"
          % (c["x"], c["y"], c["area"], c["peak"], x0, y0, sd))

for i, cr in enumerate(crops):
    cv2.imwrite("/root/ip2/dump/crop_%d.png" % i,
                cv2.resize(cr, (192, 192), interpolation=cv2.INTER_NEAREST))
cv2.imwrite("/root/ip2/dump/frame.png", gray)

if crops:
    from yolo_det import Yolo
    y = Yolo()
    res = y.detect_mosaic(crops, grid=4)
    print("mosaic ->", [(s, round(sc, 3)) for s, _a, _b, _c, _d, sc in res])
