#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""phase_cal3.py —— 自适应列相位校准 v3。

改进（相对 v2）：
  1. 只在 64 的整数倍上搜索（FIFO 残留必为 64 字节 = 64 像素的整数倍）
  2. 只用 top-5 候选（按 peak），虚警多是低 peak
  3. 环带半径随目标面积自适应 r = clamp(2*sqrt(area), 9, 40)
  4. 得分取峰值平台的加权质心，不做单点 argmax
"""
import cv2
import numpy as np

CANDS = (-64, 0, 64)


def _blob_score(gray, x, y, r):
    h, w = gray.shape
    if not (r <= x < w - r and r <= y < h - r):
        return 0.0
    patch = gray[y - r:y + r + 1, x - r:x + r + 1].astype(np.float32)
    ci = r
    core = patch[ci - 1:ci + 2, ci - 1:ci + 2].mean()
    ring = patch.copy()
    rr = max(2, r // 3)
    ring[ci - rr:ci + rr + 1, ci - rr:ci + rr + 1] = np.nan
    m = float(np.nanmean(ring))
    return max(0.0, (core - m) / 255.0)


def _vote(gray, cands, W, H):
    if not cands:
        return []
    out = []
    for s in CANDS:
        v = 0.0
        for c in cands:
            r = int(min(max(2.0 * (c["area"] ** 0.5), 9), 40))
            xx = (c["x"] + s) % W
            v += _blob_score(gray, xx, c["y"], r) * min(c["peak"], 120)
        out.append((s, v))
    return out


def estimate(gray, cands, W=640, H=360):
    top = sorted([c for c in cands if c.get("peak", 0) >= 8],
                 key=lambda c: -c["peak"])[:5]
    if not top:
        return 0, 0.0, []
    votes = _vote(gray, top, W, H)
    vs = sorted(votes, key=lambda t: -t[1])
    best_s, best_v = vs[0]
    second = vs[1][1] if len(vs) > 1 else 0.0
    conf = (best_v - second) / best_v if best_v > 0 else 0.0
    return best_s, conf, votes


if __name__ == "__main__":
    import sys

    sys.path.insert(0, "/root/ip2")
    from cam3d_test import PL3D  # noqa: E402

    W, H = 640, 360
    pl = PL3D()
    names = ("t1_birds", "t2_twodrones", "t3_field_drone",
             "t4_fourdrones", "t5_plane_drone", "t6_plane_bird")
    res = []
    for name in names:
        img = cv2.imread("/root/ip2/%s.png" % name)
        if img is None:
            print(name, "MISS")
            continue
        g = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (W, H),
                       interpolation=cv2.INTER_AREA)
        c1, _s, _d = pl.run(g)
        s, conf, votes = estimate(g, c1)
        res.append(s)
        vt = " ".join("%+d:%.0f" % (a, b) for a, b in votes)
        print("%-16s n=%2d  shift=%+4d conf=%.2f   [%s]"
              % (name, len(c1), s, conf, vt), flush=True)
    if res:
        from collections import Counter
        print("多数票 =", Counter(res).most_common(2), flush=True)
    print("CAL3_DONE")
