#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""phase_test.py —— 检查同一张图连续跑时 x 坐标是否稳定（是否交替偏移）。

背景：视频里出现"框在鸟右边、间隔固定、约一半时间"的现象，
怀疑是 正/反 两次触发之间坐标基准不一致，或帧间相位差。
用法：python3 phase_test.py [图片] [真值x]
"""
import sys
import time

import cv2
import numpy as np

import cam3d_test as ct


def best(gray, pl, invert=False):
    g = gray if not invert else (255 - gray).astype(np.uint8)
    try:
        r = pl.run(g)
    except TypeError:
        r = pl.run(g)
    cands = r[0] if isinstance(r, tuple) else r
    out = []
    for c in cands:
        if isinstance(c, dict):
            out.append((c.get("x", 0), c.get("y", 0), c.get("area", 0), c.get("peak", 0)))
        elif isinstance(c, (tuple, list)) and len(c) >= 4:
            out.append((c[0], c[1], c[2], c[3]))
    return sorted(out, key=lambda t: -t[3])[:3]


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "/root/ip2/vs_300.png"
    tx = int(sys.argv[2]) if len(sys.argv) > 2 else 300
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        print("FLAG read_fail")
        return
    if img.shape[:2] != (360, 640):
        img = cv2.resize(img, (640, 360), interpolation=cv2.INTER_AREA)

    pl = ct.PL3D()
    print("GT x=%d" % tx)
    # 预热
    best(img, pl, False)
    for k in range(4):
        a = best(img, pl, False)
        b = best(img, pl, True)
        print("ROUND %d  pos=%s  inv=%s" % (k, a[:1], b[:1]))


if __name__ == "__main__":
    main()
