# -*- coding: utf-8 -*-
"""彩色输出前提下，测 JPEG 质量/分辨率对编码耗时的影响。"""
import time

import cv2
import numpy as np

cap = cv2.VideoCapture("/root/photos.mp4")
ok, f = cap.read()
f = cv2.resize(f, (640, 360))


def t(fn, n=15):
    fn()
    t0 = time.time()
    for _ in range(n):
        fn()
    return (time.time() - t0) / n * 1000


for q in (85, 80, 70, 60, 50):
    ms = t(lambda: cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, q]))
    kb = len(cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, q])[1]) / 1024.0
    print("  640x360 q%-3d  %.1f ms  %.1f KB" % (q, ms, kb))

for w, h in ((480, 270), (512, 288)):
    g = cv2.resize(f, (w, h))
    ms = t(lambda: cv2.imencode(".jpg", g, [cv2.IMWRITE_JPEG_QUALITY, 75]))
    print("  %dx%d    q75   %.1f ms" % (w, h, ms))
