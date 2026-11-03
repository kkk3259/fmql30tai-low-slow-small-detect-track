#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mosaic_test.py —— 验证 detect_mosaic：人工给 4 个 ROI，看能否判出无人机。"""
import sys
import time

import cv2

sys.path.insert(0, "/root/ip2")
from yolo_det import Yolo  # noqa: E402


def main():
    img = cv2.imread("/root/ip2/t4_fourdrones.png")
    print("image", img.shape)
    # t4 四架无人机的大致中心（324x428）
    centers = [(60, 255), (265, 330), (225, 170), (180, 250)]
    crops = []
    for cx, cy in centers:
        x0 = max(0, min(cx - 48, img.shape[1] - 96))
        y0 = max(0, min(cy - 48, img.shape[0] - 96))
        crops.append(img[y0:y0 + 96, x0:x0 + 96].copy())
    print("crops", [c.shape for c in crops])

    y = Yolo()
    for grid in (2, 4):
        t = time.time()
        r = y.detect_mosaic(crops, grid=grid)
        dt = (time.time() - t) * 1000
        print("grid=%d  n=%d  %.1f ms" % (grid, len(r), dt))
        for it in r[:8]:
            print("   slot=%d (%.0f,%.0f)-(%.0f,%.0f) %.0f%%"
                  % (it[0], it[1], it[2], it[3], it[4], it[5] * 100))


if __name__ == "__main__":
    main()
