# -*- coding: utf-8 -*-
"""IP2 全链整合测试：真实感 16:9 灰度图 + 参考候选列表（Top-Hat -> CFAR -> CCL）。
产出：pl/sim/input_integration.hex（128x72 灰度）
      pl/sim/ref_integration.hex（33 字节：n_cand + 8×(x,y,area,peak)）
参考与 baseline/detect_v1.py 完全一致（Top-Hat 5x5 + CFAR win31 k4 floor3 + CCL 8连通）。
"""
import os
import numpy as np
import cv2

W, H = 128, 72
sim_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "sim"))

# ---- 真实感图像：天空渐变 + 云团 + 传感器噪声 + 小目标 ----
rng = np.random.default_rng(5)
yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
base = 120 + 0.3 * xx + 0.2 * yy
for _ in range(6):
    cx, cy = rng.integers(0, W), rng.integers(0, H)
    sx, sy = rng.integers(15, 40), rng.integers(8, 20)
    amp = rng.uniform(-30, 35)
    base += amp * np.exp(-((xx - cx) ** 2 / (2 * sx ** 2) + (yy - cy) ** 2 / (2 * sy ** 2)))
gray = base + rng.normal(0, 2, (H, W))
# 4 个小目标（半径 1.5px，放在内部避开 15px 的 CFAR 边界）
for cx, cy, amp in [(30, 20, 18), (70, 45, 22), (100, 30, 15), (45, 55, 20)]:
    gray += amp * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * 1.5 ** 2))
gray = np.clip(gray, 0, 255).astype(np.uint8)

# ---- 参考链路（= detect_v1.py：Top-Hat -> CFAR -> CCL）----
kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
th = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, kernel)
f = th.astype(np.float32)
mu = cv2.boxFilter(f, -1, (31, 31), normalize=True, borderType=cv2.BORDER_REFLECT)
mu2 = cv2.boxFilter(f * f, -1, (31, 31), normalize=True, borderType=cv2.BORDER_REFLECT)
var = np.maximum(mu2 - mu * mu, 0.0)
sd = np.sqrt(var)
thr = mu + 4.0 * sd + 3.0
binary = (f > thr).astype(np.uint8) * 255

n, lab, stats, cents = cv2.connectedComponentsWithStats(binary, connectivity=8)
cands = []
for i in range(1, n):
    x, y, w, h, area = stats[i]
    if area < 2 or area > 200:
        continue
    m = (lab == i)
    sum_x = int(np.sum(xx[m]))
    sum_y = int(np.sum(yy[m]))
    area = int(m.sum())
    peak = int(th[m].max())
    cands.append(((sum_x + area // 2) // area, (sum_y + area // 2) // area, area, peak))
cands.sort(key=lambda c: -c[3])
cands = cands[:8]

os.makedirs(sim_dir, exist_ok=True)
with open(os.path.join(sim_dir, "input_integration.hex"), "w") as fw:
    for y in range(H):
        for x in range(W):
            fw.write("%02X\n" % int(gray[y, x]))
with open(os.path.join(sim_dir, "ref_integration.hex"), "w") as fw:
    fw.write("%02X\n" % len(cands))
    for i in range(8):
        if i < len(cands):
            x, y, a, p = cands[i]
            fw.write("%02X\n%02X\n%02X\n%02X\n%02X\n%02X\n%02X\n" % (x >> 8, x & 255, y >> 8, y & 255, a >> 8, a & 255, p))
        else:
            fw.write("00\n00\n00\n00\n00\n00\n00\n")

print("OK: 图 %dx%d | 检测到 %d 个候选: %s" % (W, H, len(cands), [(c[0], c[1], c[2], c[3]) for c in cands]))
