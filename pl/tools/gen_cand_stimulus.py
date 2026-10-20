# -*- coding: utf-8 -*-
"""生成候选提取测试激励 + 参考。
产出：pl/sim/input_cand.hex（64x64 二值图，0/255）
      pl/sim/ref_cand.hex（64 个 8x8 块的亮点个数）
"""
import os
import numpy as np

W, H = 64, 64
sim_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "sim"))

binary = np.zeros((H, W), np.uint8)
yy, xx = np.mgrid[0:H, 0:W]
for cx, cy, r in [(10, 10, 2), (40, 20, 3), (20, 50, 1), (55, 55, 2)]:
    binary[(xx - cx) ** 2 + (yy - cy) ** 2 <= r ** 2] = 255

areas = []
for br in range(8):
    for bc in range(8):
        blk = binary[br * 8:(br + 1) * 8, bc * 8:(bc + 1) * 8]
        areas.append(int((blk > 0).sum()))

os.makedirs(sim_dir, exist_ok=True)
with open(os.path.join(sim_dir, "input_cand.hex"), "w") as f:
    for y in range(H):
        for x in range(W):
            f.write("%02X\n" % int(binary[y, x]))
with open(os.path.join(sim_dir, "ref_cand.hex"), "w") as f:
    for a in areas:
        f.write("%02X\n" % a)

print("OK: input_cand.hex=%d | ref_cand.hex=%d 块 | 非零块=%d" % (W * H, len(areas), sum(1 for a in areas if a > 0)))
