# -*- coding: utf-8 -*-
"""生成 IP1 的测试激励 + OpenCV 参考输出（"标准答案"）。
产出：pl/sim/input.hex（32x32 RGB，每行一个 24bit RRGGBB）
      pl/sim/ref.hex  （16x16 灰度图，3x3 高斯后）
"""
import os
import numpy as np
import cv2

W, H = 32, 32
sim_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "sim"))

rng = np.random.default_rng(42)
yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
# 渐变背景 + 一个亮点（模拟低小慢目标），贴近 baseline 的合成思路
R = np.clip(90 + 3.0 * xx + 1.5 * yy, 0, 255)
G = np.clip(60 + 2.0 * xx - 1.0 * yy, 0, 255)
B = np.clip(120 - 1.0 * xx + 2.0 * yy, 0, 255)
blob = 90.0 * np.exp(-((xx - 22.0) ** 2 + (yy - 9.0) ** 2) / (2 * 2.5 ** 2))
noise = rng.normal(0, 3.0, (H, W))
rgb = np.clip(np.stack([R + blob, G + blob, B + blob], axis=2) + noise[..., None], 0, 255).astype(np.uint8)

# OpenCV 参考（与 baseline/detect_v1.py 的 gauss=0 一致：BGR2GRAY -> [::2,::2]，无高斯）
bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
gauss = gray[::2, ::2]

os.makedirs(sim_dir, exist_ok=True)
with open(os.path.join(sim_dir, "input.hex"), "w") as f:
    for y in range(H):
        for x in range(W):
            r, g, b = int(rgb[y, x, 0]), int(rgb[y, x, 1]), int(rgb[y, x, 2])
            f.write("%06X\n" % ((r << 16) | (g << 8) | b))

with open(os.path.join(sim_dir, "ref.hex"), "w") as f:
    for y in range(gauss.shape[0]):
        for x in range(gauss.shape[1]):
            f.write("%02X\n" % int(gauss[y, x]))

print("OK: input.hex = %d pixels | ref.hex = %d pixels (%dx%d)"
      % (W * H, gauss.size, gauss.shape[1], gauss.shape[0]))
