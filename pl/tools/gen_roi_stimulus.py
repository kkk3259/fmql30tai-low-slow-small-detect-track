# -*- coding: utf-8 -*-
"""IP4 roi_pack 测试：160x160 灰度图 + 候选列表 → 每个候选裁 128x128 ROI（越界补 0）。
产出：pl/sim/input_roi_gray.hex（灰度图）、input_roi_cand.hex（36 字节候选）、ref_roi.hex（ROI 数据）
"""
import os
import numpy as np

W, H, ROI = 160, 160, 128
MAX_CAND = 5
sim_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "sim"))

rng = np.random.default_rng(5)
gray = rng.integers(0, 256, (H, W)).astype(np.uint8)

# 候选（含中心 + 边界候选，测越界补 0）: (x, y, area, peak)
cands = [(80, 80, 10, 50), (10, 10, 5, 40), (150, 150, 8, 45), (5, 90, 6, 42)]


def w57(cands):
    out = [len(cands)]
    for i in range(MAX_CAND):
        if i < len(cands):
            x, y, a, p = cands[i]
            out += [x >> 8, x & 255, y >> 8, y & 255, a >> 8, a & 255, p]
        else:
            out += [0] * 7
    return out


# 参考 ROI（与 ps_app.py::crop_roi 一致）
half = ROI // 2
ref = []
for cx, cy, a, p in cands:
    x0, y0 = cx - half, cy - half
    for j in range(ROI):
        for i in range(ROI):
            gx, gy = x0 + i, y0 + j
            ref.append(int(gray[gy, gx]) if (0 <= gx < W and 0 <= gy < H) else 0)

os.makedirs(sim_dir, exist_ok=True)
with open(os.path.join(sim_dir, "input_roi_gray.hex"), "w") as f:
    for v in gray.ravel():
        f.write("%02X\n" % int(v))
with open(os.path.join(sim_dir, "input_roi_cand.hex"), "w") as f:
    for v in w57(cands):
        f.write("%02X\n" % v)
with open(os.path.join(sim_dir, "ref_roi.hex"), "w") as f:
    for v in ref:
        f.write("%02X\n" % v)

print("OK: 灰度 %dx%d | %d 个候选 | ROI 数据 %d 字节" % (W, H, len(cands), len(ref)))
