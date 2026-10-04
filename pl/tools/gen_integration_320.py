# -*- coding: utf-8 -*-
"""IP2 全链 320x180 真实分辨率测试（宽 320 > 255，验证 16 位坐标）。
产出：pl/sim/input_integration_320.hex（320x180 灰度）
      pl/sim/ref_integration_320.hex（57 字节候选列表）
"""
import os
import numpy as np
import cv2

W, H = 320, 180
sim_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "sim"))

rng = np.random.default_rng(9)
yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
base = 120 + 0.2 * xx + 0.1 * yy
for _ in range(10):
    cx, cy = rng.integers(0, W), rng.integers(0, H)
    sx, sy = rng.integers(40, 100), rng.integers(20, 60)
    amp = rng.uniform(-30, 35)
    base += amp * np.exp(-((xx - cx) ** 2 / (2 * sx ** 2) + (yy - cy) ** 2 / (2 * sy ** 2)))
gray = base + rng.normal(0, 2, (H, W))
# 6 个小目标，含 x>255（测 16 位坐标）
for cx, cy, amp in [(60, 40, 20), (120, 80, 22), (180, 130, 18), (260, 60, 24), (300, 140, 20), (80, 160, 16)]:
    gray += amp * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * 1.5 ** 2))
gray = np.clip(gray, 0, 255).astype(np.uint8)

kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
th = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, kernel)
img_i = th.astype(np.int32)
HH, WW = img_i.shape
HALF = 15
integ = cv2.integral(th)
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

n, lab, stats, cents = cv2.connectedComponentsWithStats(binary, connectivity=8)
cands = []
for i in range(1, n):
    x, y, w, h, area = stats[i]
    if area < 2 or area > 200:
        continue
    m = (lab == i)
    sum_x = int(np.sum(xx[m])); sum_y = int(np.sum(yy[m]))
    area = int(m.sum()); peak = int(th[m].max())
    cands.append(((sum_x + area // 2) // area, (sum_y + area // 2) // area, area, peak))
cands.sort(key=lambda c: -c[3])
cands = cands[:8]

os.makedirs(sim_dir, exist_ok=True)
with open(os.path.join(sim_dir, "input_integration_320.hex"), "w") as fw:
    for y in range(H):
        for x in range(W):
            fw.write("%02X\n" % int(gray[y, x]))
with open(os.path.join(sim_dir, "ref_integration_320.hex"), "w") as fw:
    fw.write("%02X\n" % len(cands))
    for i in range(8):
        if i < len(cands):
            x, y, a, p = cands[i]
            fw.write("%02X\n%02X\n%02X\n%02X\n%02X\n%02X\n%02X\n" %
                     (x >> 8, x & 255, y >> 8, y & 255, a >> 8, a & 255, p))
        else:
            fw.write("00\n00\n00\n00\n00\n00\n00\n")

print("OK: 图 %dx%d | 检测到 %d 个候选: %s" % (W, H, len(cands), [(c[0], c[1], c[3]) for c in cands]))
