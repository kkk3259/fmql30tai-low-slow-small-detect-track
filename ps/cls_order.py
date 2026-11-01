#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cls_order.py —— 查两件事：(1) cls128 输出两个元素分别是哪一类；(2) yolo11n_drone 能不能用。

用法（板上）：python3 cls_order.py /root/ip2/t2_twodrones.png
"""
import sys
import numpy as np
import cv2
import cam3d_test as C

IMG = sys.argv[1] if len(sys.argv) > 1 else "/root/ip2/t2_twodrones.png"

img = cv2.imread(IMG, cv2.IMREAD_GRAYSCALE)
h0, w0 = img.shape[:2]
g = cv2.resize(img, (640, 360), interpolation=cv2.INTER_AREA)
g = (255.0 * (g.astype(np.float32) / 255.0) ** 0.08).astype(np.uint8)

pl = C.PL3D()
print("PL init ok")
cands, st, dt = pl.run(g)
print("cands=%d dt=%.2fms" % (len(cands), dt))

# ---- (1) cls128 两个输出元素 ----
npu = C.NPU("/root/npu/cls128_drone_ZG.json", "/root/npu/cls128_drone_ZG.raw", dev=pl.dev)
print("\n=== cls128 原始输出（每个候选两个元素） ===")
for i, c in enumerate(cands[:6]):
    if isinstance(c, dict):
        x, y, area, peak = c.get("x", 0), c.get("y", 0), c.get("area", 0), c.get("peak", 0)
    else:
        x, y, area, peak = c[0], c[1], c[2], c[3]
    side = max(24, min(128, int(round(1.7 * 2 * (area ** 0.5)))))
    p = C.crop(g, int(x), int(y), side=side)
    r = np.ravel(np.asarray(npu.predict(p), dtype=np.float64))
    print("  #%d (%d,%d) area=%d side=%d  ->  %s" % (i, x, y, area, side, np.array2string(r, precision=4)))

# ---- (2) yolo11n_drone ----
print("\n=== yolo11n_drone 试跑 ===")
try:
    yolo = C.NPU("/root/npu/yolo11n_drone_trunc_ZG.json",
                 "/root/npu/yolo11n_drone_trunc_ZG.raw", dev=pl.dev)
    tin = cv2.cvtColor(cv2.resize(img, (640, 640)), cv2.COLOR_GRAY2BGR)
    outp = yolo.predict(tin)
    arr = np.ravel(np.asarray(outp, dtype=np.float64))
    print("  out count = %s" % (len(outp) if hasattr(outp, "__len__") else "?"))
    print("  ravel len = %d" % arr.size)
    print("  head      = %s" % np.array2string(arr[:16], precision=4))
    print("  min/max   = %.4f / %.4f" % (arr.min(), arr.max()))
except Exception as ex:
    print("  yolo FAILED:", repr(ex))

print("DONE")
