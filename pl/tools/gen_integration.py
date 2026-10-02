# -*- coding: utf-8 -*-
"""IP2 整合测试：生成 64x64 灰度帧 + 基线参考（Top-Hat -> CFAR -> 8x8 块面积）。
产出：pl/sim/input_integration.hex（64x64 灰度）
      pl/sim/ref_integration.hex（64 个块面积）
"""
import os
import numpy as np
import cv2

W, H = 64, 64
sim_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "sim"))

rng = np.random.default_rng(5)
yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
gray = 90 + 0.6 * xx + 0.4 * yy + rng.normal(0, 6, (H, W))
for cx, cy, amp in [(20, 20, 55), (50, 35, 40), (15, 55, 30)]:
    gray = gray + amp * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * 1.5 ** 2))
gray = np.clip(gray, 0, 255).astype(np.uint8)

# 基线链路：Top-Hat -> CFAR 阈值 -> 二值
kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
tophat = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, kernel)
f = tophat.astype(np.float32)
mu = cv2.boxFilter(f, -1, (31, 31), normalize=True, borderType=cv2.BORDER_REFLECT)
mu2 = cv2.boxFilter(f * f, -1, (31, 31), normalize=True, borderType=cv2.BORDER_REFLECT)
var = np.maximum(mu2 - mu * mu, 0.0)
sd = np.sqrt(var)
thr = mu + 4.0 * sd + 3.0
binary = (f > thr).astype(np.uint8) * 255

# 8x8 块面积（与 candidate_extract v1 一致）
areas = []
for br in range(8):
    for bc in range(8):
        areas.append(int((binary[br * 8:(br + 1) * 8, bc * 8:(bc + 1) * 8] > 0).sum()))

os.makedirs(sim_dir, exist_ok=True)
with open(os.path.join(sim_dir, "input_integration.hex"), "w") as fw:
    for y in range(H):
        for x in range(W):
            fw.write("%02X\n" % int(gray[y, x]))
with open(os.path.join(sim_dir, "ref_integration.hex"), "w") as fw:
    for a in areas:
        fw.write("%02X\n" % a)

print("OK: input_integration.hex=%d | ref_integration.hex=%d 块 | 非零块=%d" % (W * H, len(areas), sum(1 for a in areas if a > 0)))
