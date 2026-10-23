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

# ---- 参考：真实标准差（与 cfar_threshold_stream.v 同一整数判决，不开方）----
from gen_cfar_std_ref import cfar_std
binary = cfar_std(gray.reshape(-1).astype(np.int64), W, H)[0].astype(np.uint8) * 255

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
