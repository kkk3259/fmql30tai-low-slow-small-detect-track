#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""决定性实验：同一张灰度图连续跑 5 次 PL，比较原始候选表是否完全一致。

绕开 cam3d_pipe 的 cluster/ROI/NPU，直接看 PL 的裸输出。
"""
import sys
import time

sys.path.insert(0, "/root/ip2")
import cv2
import numpy as np

import cam3d_test as ct


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "/root/ip2/dataset/ds01.png"
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        print("读图失败", path)
        return
    h, w = img.shape[:2]
    nw = 640
    nh = max(1, int(round(h * (640.0 / w))))
    r = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
    if nh >= 480:
        y0 = (nh - 480) // 2
        r = r[y0:y0 + 480, :]
    else:
        out = np.zeros((480, 640, 3), np.uint8)
        y0 = (480 - nh) // 2
        out[y0:y0 + nh, :] = r
        r = out
    g = cv2.cvtColor(r[60:420, :], cv2.COLOR_BGR2GRAY)
    print("图 %s -> gray %s" % (path, g.shape))

    pl = ct.PL3D()

    runs = []
    for k in range(5):
        cands, st, dt = pl.run(g)
        sig = [(c["x"], c["y"], c["area"], c["peak"]) for c in cands]
        runs.append(sig)
        print("  第%d次 pl=%.2fms n=%d | %s" % (k, dt, len(cands), sig[:6]))
        time.sleep(0.05)

    same = all(r == runs[0] for r in runs)
    print("=== 5 次是否完全一致:", "是（PL 确定性）" if same else "否（PL 自己就不稳定）")
    if not same:
        xs0 = set((a[0], a[1]) for a in runs[0])
        for k, r in enumerate(runs[1:], 1):
            xs = set((a[0], a[1]) for a in r)
            print("  第%d次 vs 第0次: 多 %s | 少 %s"
                  % (k, sorted(xs - xs0)[:4], sorted(xs0 - xs)[:4]))


if __name__ == "__main__":
    main()
