# -*- coding: utf-8 -*-
"""生成 CCL 候选提取测试激励 + OpenCV 参考。
产出：pl/sim/input_bin.hex（64x64 二值图 0/255）
      pl/sim/input_enh.hex（64x64 增强图，算 peak 用）
      pl/sim/ref_ccl.hex（n_cand + 8×(x,y,area,peak)，每值一行 %02X）
"""
import os
import numpy as np
import cv2

W, H = 64, 64
sim_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "sim"))

rng = np.random.default_rng(7)
yy, xx = np.mgrid[0:H, 0:W]
enh = rng.normal(40, 5, (H, W)).astype(np.float32)
# 5 个分离的亮斑（幅度不同 → peak 有区分度，便于验证排序）
blobs = [(10, 10, 3, 190), (40, 20, 4, 210), (20, 50, 2, 170), (55, 55, 3, 230), (30, 38, 2, 150)]
for cx, cy, r, amp in blobs:
    enh += amp * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2.0 * r * r))
enh = np.clip(enh, 0, 255).astype(np.uint8)
binary = (enh > 120).astype(np.uint8) * 255

# OpenCV 8 连通 CCL（与 baseline detect_v1.py 的 extract_candidates 一致）
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
    peak = int(enh[m].max())
    # 与 Verilog 的 (x_sum + area/2)/area 完全一致
    cands.append(((sum_x + area // 2) // area, (sum_y + area // 2) // area, area, peak))
cands.sort(key=lambda c: -c[3])   # peak 降序
cands = cands[:8]

os.makedirs(sim_dir, exist_ok=True)
with open(os.path.join(sim_dir, "input_bin.hex"), "w") as f:
    for y in range(H):
        for x in range(W):
            f.write("%02X\n" % (255 if binary[y, x] > 0 else 0))
with open(os.path.join(sim_dir, "input_enh.hex"), "w") as f:
    for y in range(H):
        for x in range(W):
            f.write("%02X\n" % int(enh[y, x]))
with open(os.path.join(sim_dir, "ref_ccl.hex"), "w") as f:
    f.write("%02X\n" % len(cands))
    for i in range(8):
        if i < len(cands):
            x, y, a, p = cands[i]
            f.write("%02X\n%02X\n%02X\n%02X\n%02X\n%02X\n%02X\n" % (x >> 8, x & 255, y >> 8, y & 255, a >> 8, a & 255, p))
        else:
            f.write("00\n00\n00\n00\n00\n00\n00\n")

print("OK: 连通域=%d（过滤后） 候选=%d  peak顺序=%s" % (n - 1, len(cands), [c[3] for c in cands]))
