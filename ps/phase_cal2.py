#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""phase_cal2.py —— 自适应列相位校准（互相关投票法）。

原理：PL 报的候选坐标与"我们送进 PL 的那张图"之间只差一个整体位移 s。
对每个候选试不同 s，看 (x+s, y) 处图上是否真有局部亮斑；按亮度证据加权投票，
得分最高的 s 就是当前相位偏移。不依赖任何参照物，也不需要真值。
"""
import cv2
import numpy as np

RING = 9          # 环带半径（像素）
SRCH = 90         # 搜索范围 ±SRCH


def _blob_score(gray, x, y, r=RING):
    """中心 3x3 均值 − 环带均值；返回 0~1 的正值。"""
    h, w = gray.shape
    if not (r <= x < w - r and r <= y < h - r):
        return 0.0
    patch = gray[y - r:y + r + 1, x - r:x + r + 1].astype(np.float32)
    c = patch[r - 1:r + 2, r - 1:r + 2].mean()
    ring = patch.copy()
    ring[r - 2:r + 3, r - 2:r + 3] = np.nan
    m = float(np.nanmean(ring))
    return max(0.0, (c - m) / 255.0)


def estimate_shift(gray, cands, W=640, H=360, srch=SRCH):
    """返回 (shift, score)。shift 应加在候选 x 上。"""
    use = [c for c in cands if c.get("peak", 0) > 0][:24]
    if not use:
        return 0, 0.0
    best_s, best_v = 0, -1.0
    for s in range(-srch, srch + 1):
        v = 0.0
        for c in use:
            xx = (c["x"] + s) % W
            v += _blob_score(gray, xx, c["y"]) * min(c["peak"], 120)
        if v > best_v:
            best_v, best_s = v, s
    return best_s, best_v


def estimate_shift_robust(gray, cands, W=640, H=360):
    """两个相位候选下取更可信的那个；返回 (shift, 置信度)。"""
    s, v = estimate_shift(gray, cands, W, H)
    # 与 s 相差 >12px 的所有位移里最好的那个，用来判断优势是否明显
    best_other = -1.0
    for s2 in range(-SRCH, SRCH + 1):
        if abs(s2 - s) <= 12:
            continue
        v2 = 0.0
        for c in (c for c in cands[:24] if c.get("peak", 0) > 0):
            xx = (c["x"] + s2) % W
            v2 += _blob_score(gray, xx, c["y"]) * min(c["peak"], 120)
        best_other = max(best_other, v2)
    conf = (v - best_other) / v if v > 0 else 0.0
    return s, conf


if __name__ == "__main__":
    import sys

    sys.path.insert(0, "/root/ip2")
    from cam3d_test import PL3D  # noqa: E402

    W, H = 640, 360
    pl = PL3D()
    for name in ("t2_twodrones", "t3_field_drone", "t5_plane_drone"):
        img = cv2.imread("/root/ip2/%s.png" % name)
        if img is None:
            print(name, "MISS")
            continue
        g = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (W, H), interpolation=cv2.INTER_AREA)
        c1, _s, _d = pl.run(g)
        c1 = [c for c in c1 if c["peak"] >= 8]
        s, conf = estimate_shift_robust(g, c1)
        print("%-16s n=%2d  shift=%+4d  conf=%.2f" % (name, len(c1), s, conf), flush=True)
    print("CAL2_DONE")
