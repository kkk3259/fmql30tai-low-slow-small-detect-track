#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扫描列相位偏移：每帧只跑一次 PL，把所有候选存下来，
然后在 Python 里对多个 SHIFT 值离线重算召回，避免重复跑硬件。

用法：python3 shift_scan.py [scene_glob]
"""
import glob
import json
import sys

import cv2
import numpy as np

sys.path.insert(0, "/root/ip2")
from cam3d_test import PL3D  # noqa: E402

W, H = 640, 360
SHIFTS = [-128, -96, -64, -32, 0, 32, 64, 96, 128]
MAXF = 30          # 每场景最多取 30 帧（够统计）


def load_gt(path):
    with open(path) as f:
        meta = json.load(f)
    by_f = {}
    for g in meta["gt"]:
        by_f.setdefault(g["f"], []).append(g)
    return meta, by_f


def main():
    pat = sys.argv[1] if len(sys.argv) > 1 else "/root/testset/scene_*.mp4"
    scenes = sorted(glob.glob(pat))
    print("场景数:", len(scenes))

    hw = PL3D()
    print("PL3D ready, VERSION=0x%08x" % 0x00010000)

    # 收集：每场景每帧的 (cands, gt)
    data = []
    for mp4 in scenes:
        js = mp4[:-4] + ".json"
        meta, by_f = load_gt(js)
        cap = cv2.VideoCapture(mp4)
        frames = []
        f = 0
        while f < MAXF:
            ok, img = cap.read()
            if not ok:
                break
            gray = cv2.cvtColor(cv2.resize(img, (W, H)), cv2.COLOR_BGR2GRAY)
            cands, st, dt = hw.run(gray)
            gs = by_f.get(f, [])
            if gs:
                frames.append(([(c["x"], c["y"]) for c in cands],
                               [(g["x"], g["y"]) for g in gs],
                               max(6, int(meta["size"]))))
            f += 1
        cap.release()
        data.append((meta["name"], meta["size"], frames))
        print("  %-20s %2dpx  帧 %d  候选均 %.1f" %
              (meta["name"], meta["size"], len(frames),
               np.mean([len(c) for c, _, _ in frames]) if frames else 0))

    print("\n%-8s %-10s %-10s" % ("SHIFT", "平均召回", "TP总数"))
    best = (None, -1)
    for s in SHIFTS:
        n_tp = n_gt = 0
        for name, size, frames in data:
            for cands, gts, tol in frames:
                n_gt += len(gts)
                cs = [((x + s) % W, y) for x, y in cands]
                for gx, gy in gts:
                    if any(((cx - gx) ** 2 + (cy - gy) ** 2) ** 0.5 <= tol
                           for cx, cy in cs):
                        n_tp += 1
        rec = 100.0 * n_tp / max(1, n_gt)
        print("%-8d %-10.2f %-10d" % (s, rec, n_tp))
        if rec > best[1]:
            best = (s, rec)
    print("\n最佳 SHIFT = %d  召回 %.2f%%" % best)


if __name__ == "__main__":
    main()
