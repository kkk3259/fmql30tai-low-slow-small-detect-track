# -*- coding: utf-8 -*-
"""生成 IP2 的 Top-Hat 测试激励 + OpenCV 参考。
产出：pl/sim/input_gray.hex（32x32 灰度图，每行一个字节）
      pl/sim/ref_tophat.hex（5x5 Top-Hat 结果，每行一个字节）
"""
import os
import numpy as np
import cv2

W, H = 32, 32
sim_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "sim"))

rng = np.random.default_rng(7)
yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
gray = 100 + 1.5 * xx + 1.0 * yy                      # 渐变背景
blob = 80.0 * np.exp(-((xx - 16) ** 2 + (yy - 16) ** 2) / (2 * 2.0 ** 2))  # 亮点
gray = np.clip(gray + blob + rng.normal(0, 2.0, (H, W)), 0, 255).astype(np.uint8)

# OpenCV 参考：5x5 矩形结构元的 Top-Hat（与 baseline detect_v1.py 一致）
kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
tophat = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, kernel)  # uint8，已 clip 到 [0,255]

os.makedirs(sim_dir, exist_ok=True)
with open(os.path.join(sim_dir, "input_gray.hex"), "w") as f:
    for y in range(H):
        for x in range(W):
            f.write("%02X\n" % int(gray[y, x]))
with open(os.path.join(sim_dir, "ref_tophat.hex"), "w") as f:
    for y in range(H):
        for x in range(W):
            f.write("%02X\n" % int(tophat[y, x]))

print("OK: input_gray.hex=%d | ref_tophat.hex=%d" % (W * H, W * H))
