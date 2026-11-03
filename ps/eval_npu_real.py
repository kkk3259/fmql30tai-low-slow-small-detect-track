#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真实背景集上的端到端评测：PL 出候选 → 聚类 → 取 topN → 裁片 → NPU 判别

只有 NPU 判为无人机（p >= CONF）的才计入检出，用来衡量
"靠 NPU 压杂波"这条路线到底能把召回/精确做到多少。

用法：python3 eval_npu_real.py [dir] [ROI_MAX] [CONF]
"""
import glob
import json
import sys

import cv2
import numpy as np

sys.path.insert(0, "/root/ip2")
from cam3d_test import PL3D          # noqa: E402
from yolo_det import Yolo            # noqa: E402

W, H = 640, 360
DIR = sys.argv[1] if len(sys.argv) > 1 else "/root/ts_real"
ROI_MAX = int(sys.argv[2]) if len(sys.argv) > 2 else 10
CONF = float(sys.argv[3]) if len(sys.argv) > 3 else 0.40
SHIFT = 64
MAXF = 30


def cluster(cs):
    """按 peak 降序，半径内的合并"""
    g = []
    for c in sorted(cs, key=lambda z: -z["peak"]):
        r = min(40.0, max(14.0, 2.5 * (c["area"] ** 0.5)))
        for x in g:
            if ((c["x"] - x["x"]) ** 2 + (c["y"] - x["y"]) ** 2) ** 0.5 <= r:
                break
        else:
            g.append(dict(c))
    return g


def crop_pad(gray, cx, cy, side, n):
    half = side // 2
    x0, y0 = cx - half, cy - half
    x1, y1 = x0 + side, y0 + side
    out = np.full((side, side), 114, np.uint8)
    sx0, sy0 = max(0, x0), max(0, y0)
    sx1, sy1 = min(W, x1), min(H, y1)
    if sx1 > sx0 and sy1 > sy0:
        out[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = gray[sy0:sy1, sx0:sx1]
    n[0] += 1
    return out


def main():
    scenes = sorted(glob.glob(DIR + "/scene_*.mp4"))
    print("场景 %d  ROI_MAX=%d CONF=%.2f SHIFT=%d" % (len(scenes), ROI_MAX, CONF, SHIFT))

    hw = PL3D()
    y = Yolo(dev=hw.dev)

    tot_tp = tot_fp = tot_gt = 0
    for mp4 in scenes:
        with open(mp4[:-4] + ".json") as f:
            meta = json.load(f)
        size = int(meta["size"])
        tol = max(6, size)
        gt_by_f = {}
        for g in meta["gt"]:
            gt_by_f.setdefault(g["f"], []).append(g)

        cap = cv2.VideoCapture(mp4)
        f = 0
        tp = fp = ngt = 0
        while f < MAXF:
            ok, img = cap.read()
            if not ok:
                break
            gray = cv2.cvtColor(cv2.resize(img, (W, H)), cv2.COLOR_BGR2GRAY)
            cands, st, dt = hw.run(gray)
            gs = gt_by_f.get(f, [])
            if gs:
                ngt += len(gs)
                cs = cluster(cands)[:ROI_MAX]
                hits = []
                if cs:
                    n = [0]
                    crops = [crop_pad(gray, (c["x"] + SHIFT) % W, c["y"],
                                      max(24, min(96, int(3.0 * c["area"] ** 0.5))), n)
                             for c in cs]
                    try:
                        # 返回 [(k, x1, y1, x2, y2, score), ...]，k = 格子序号
                        boxes = y.detect_mosaic(crops, grid=4)
                    except Exception:
                        boxes = []
                    best = {}
                    for it in boxes:
                        k = int(it[0])
                        sc = float(it[5])
                        if sc >= CONF and sc > best.get(k, -1.0):
                            best[k] = sc
                    for k in best:
                        if 0 <= k < len(cs):
                            hits.append(((cs[k]["x"] + SHIFT) % W, cs[k]["y"]))
                for gx, gy in [(g["x"], g["y"]) for g in gs]:
                    if any(((hx - gx) ** 2 + (hy - gy) ** 2) ** 0.5 <= tol
                           for hx, hy in hits):
                        tp += 1
                fp += max(0, len(hits) - tp)
            f += 1
        cap.release()
        tot_tp += tp
        tot_fp += fp
        tot_gt += ngt
        print("  %-26s %2dpx  召回 %5.1f%%  精确 %5.1f%%  (%d/%d)" %
              (meta["name"], size, 100.0 * tp / max(1, ngt),
               100.0 * tp / max(1, tp + fp), tp, ngt))

    print("\n合计: 召回 %.2f%%  精确 %.2f%%  TP=%d FP=%d GT=%d" %
          (100.0 * tot_tp / max(1, tot_gt),
           100.0 * tot_tp / max(1, tot_tp + tot_fp), tot_tp, tot_fp, tot_gt))
    print("NPU_EVAL_DONE")


if __name__ == "__main__":
    main()
