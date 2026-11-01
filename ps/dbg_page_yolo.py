#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查网页同一帧在 yolo 下的原始分数分布，定位 n=0 的原因。"""
import sys

import cv2
import numpy as np

sys.path.insert(0, "/root/ip2")
from yolo_det import Yolo, sig, read_tensor  # noqa: E402

base = cv2.imread("/root/ip2/t4_fourdrones.png")
ih, iw = base.shape[:2]
s = min(640.0 / iw, 480.0 / ih)
r = cv2.resize(base, (int(iw * s), int(ih * s)), interpolation=cv2.INTER_AREA)
canvas = np.zeros((480, 640, 3), np.uint8)
y0, x0 = (480 - r.shape[0]) // 2, (640 - r.shape[1]) // 2
canvas[y0:y0 + r.shape[0], x0:x0 + r.shape[1]] = r
crop = canvas[60:420, :]
gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
cv2.imwrite("/root/tpy_frame.png", crop)

print("FRAME", crop.shape, "gray", gray.shape, flush=True)

yy = Yolo()
bs = yy.detect(gray)
print("DETECT", len(bs), flush=True)
for b in bs:
    print("   BOX %.0f,%.0f %.0f,%.0f %.2f" % (b[0], b[1], b[2], b[3], b[4]), flush=True)

# 原始分数分布（不套阈值）
g3 = cv2.cvtColor(cv2.resize(gray, (640, 640), interpolation=cv2.INTER_AREA), cv2.COLOR_GRAY2RGB)
t = yy.xrt.Tensor(np.ascontiguousarray(g3[None].astype(np.uint8)), yy.tt)
outs = yy.sess.forward([t])
o0 = read_tensor(outs[0])[0]
o1 = read_tensor(outs[1])[0, 0]
sc = sig(o1) * sig(o0[4:].max(axis=0))
order = np.argsort(-sc)[:8]
print("TOP8:", flush=True)
for i in order:
    print("   #%d  %.3f   obj=%.3f" % (int(i), float(sc[i]), float(sig(o1[i]))), flush=True)
print("NPU_DONE", flush=True)
