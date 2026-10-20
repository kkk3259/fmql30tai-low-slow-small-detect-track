# -*- coding: utf-8 -*-
"""生成流式高斯测试激励 + OpenCV 参考。
产出：pl/sim/input_gauss.hex（16x16 灰度图）
      pl/sim/ref_gauss.hex（3x3 高斯结果）
"""
import os
import numpy as np
import cv2

W, H = 16, 16
sim_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "sim"))

rng = np.random.default_rng(3)
yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
gray = 100 + 2.0 * xx + 1.5 * yy + rng.normal(0, 4, (H, W))
blob = 70.0 * np.exp(-((xx - 8) ** 2 + (yy - 8) ** 2) / (2 * 2.0 ** 2))
gray = np.clip(gray + blob, 0, 255).astype(np.uint8)

gauss = cv2.GaussianBlur(gray, (3, 3), 0)   # OpenCV 默认 REFLECT_101 边界

os.makedirs(sim_dir, exist_ok=True)
with open(os.path.join(sim_dir, "input_gauss.hex"), "w") as f:
    for y in range(H):
        for x in range(W):
            f.write("%02X\n" % int(gray[y, x]))
with open(os.path.join(sim_dir, "ref_gauss.hex"), "w") as f:
    for y in range(H):
        for x in range(W):
            f.write("%02X\n" % int(gauss[y, x]))

print("OK: input_gauss.hex=%d | ref_gauss.hex=%d" % (W * H, W * H))
