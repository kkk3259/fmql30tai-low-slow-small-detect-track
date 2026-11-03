#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""纯 NPU（yolo11n 整帧）在测试集上的召回/精确评测。

用法：python3 eval_yolo_real.py [dir] [CONF]
"""
import glob
import json
import sys

import cv2

sys.path.insert(0, "/root/ip2")
from yolo_det import Yolo  # noqa: E402

W, H = 640, 360
DIR = sys.argv[1] if len(sys.argv) > 1 else "/root/ts_real"
CONF = float(sys.argv[2]) if len(sys.argv) > 2 else 0.25
MAXF = 30


def main():
    scenes = sorted(glob.glob(DIR + "/scene_*.mp4"))
    print("场景 %d  CONF=%.2f" % (len(scenes), CONF))
    y = Yolo()

    T = dict(tp=0, fp=0, gt=0)
    for mp4 in scenes:
        with open(mp4[:-4] + ".json") as f:
            meta = json.load(f)
        size = int(meta["size"])
        tol = max(6, size)
        gt_by_f = {}
        for g in meta["gt"]:
            gt_by_f.setdefault(g["f"], []).append(g)

        cap = cv2.VideoCapture(mp4)
        f = tp = fp = ngt = 0
        while f < MAXF:
            ok, img = cap.read()
            if not ok:
                break
            gs = gt_by_f.get(f, [])
            if gs:
                ngt += len(gs)
                boxes = y.detect(img)          # [(x1,y1,x2,y2,score), ...] 原图坐标
                pts = [((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)
                       for b in boxes if float(b[4]) >= CONF]
                hitn = 0
                for g in gs:
                    if any(((px - g["x"]) ** 2 + (py - g["y"]) ** 2) ** 0.5 <= tol
                           for px, py in pts):
                        hitn += 1
                tp += hitn
                fp += max(0, len(pts) - hitn)
            f += 1
        cap.release()
        T["tp"] += tp
        T["fp"] += fp
        T["gt"] += ngt
        print("  %-26s %2dpx  召回 %5.1f%%  精确 %5.1f%%  (%d/%d)" %
              (meta["name"], size, 100.0 * tp / max(1, ngt),
               100.0 * tp / max(1, tp + fp), tp, ngt))

    tp, fp, gt = T["tp"], T["fp"], T["gt"]
    print("\n合计: 召回 %.2f%%  精确 %.2f%%  TP=%d FP=%d GT=%d" %
          (100.0 * tp / max(1, gt), 100.0 * tp / max(1, tp + fp), tp, fp, gt))
    print("YOLO_EVAL_DONE")


if __name__ == "__main__":
    main()
