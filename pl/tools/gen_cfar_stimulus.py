# -*- coding: utf-8 -*-
"""生成 CFAR 测试激励 + OpenCV 参考。
产出：pl/sim/input_cfar.hex（64x64 灰度图）
      pl/sim/ref_cfar.hex（31x31 CFAR 二值化结果，255/0）
"""
import os
import numpy as np
import cv2

W, H = 64, 64
sim_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "sim"))

rng = np.random.default_rng(11)
yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
gray = 80 + 0.5 * xx + 0.3 * yy + rng.normal(0, 8, (H, W))     # 渐变背景 + 噪声
for cx, cy, amp in [(16, 16, 60), (48, 40, 45), (30, 52, 35)]:  # 三个亮点
    gray = gray + amp * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * 1.5 ** 2))
gray = np.clip(gray, 0, 255).astype(np.uint8)

# 参考：与 cfar_threshold.v 一致（定点 MAD + 积分图裁剪窗口，整数算术）
img_i = gray.astype(np.int32)
HH, WW = img_i.shape
HALF = 15
integ = cv2.integral(gray)
mu = np.zeros((HH, WW), np.int32)
for r in range(HH):
    for c in range(WW):
        x1 = max(c - HALF, 0); x2 = min(c + HALF, WW - 1)
        y1 = max(r - HALF, 0); y2 = min(r + HALF, HH - 1)
        area = (x2 - x1 + 1) * (y2 - y1 + 1)
        s = integ[y2 + 1][x2 + 1] - integ[y1][x2 + 1] - integ[y2 + 1][x1] + integ[y1][x1]
        mu[r, c] = s // area
abs_dev = np.abs(img_i - mu)
integ2 = cv2.integral(abs_dev.astype(np.uint8))
mad = np.zeros((HH, WW), np.int32)
for r in range(HH):
    for c in range(WW):
        x1 = max(c - HALF, 0); x2 = min(c + HALF, WW - 1)
        y1 = max(r - HALF, 0); y2 = min(r + HALF, HH - 1)
        area = (x2 - x1 + 1) * (y2 - y1 + 1)
        s = integ2[y2 + 1][x2 + 1] - integ2[y1][x2 + 1] - integ2[y2 + 1][x1] + integ2[y1][x1]
        mad[r, c] = s // area
thr = mu + 5 * mad + 3
binary = (img_i > thr).astype(np.uint8) * 255

os.makedirs(sim_dir, exist_ok=True)
with open(os.path.join(sim_dir, "input_cfar.hex"), "w") as f:
    for y in range(H):
        for x in range(W):
            f.write("%02X\n" % int(gray[y, x]))
with open(os.path.join(sim_dir, "ref_cfar.hex"), "w") as f:
    for y in range(H):
        for x in range(W):
            f.write("%02X\n" % int(binary[y, x]))

print("OK: input_cfar.hex=%d | ref_cfar.hex=%d | 亮点数=%d" % (W * H, W * H, int((binary > 0).sum())))
