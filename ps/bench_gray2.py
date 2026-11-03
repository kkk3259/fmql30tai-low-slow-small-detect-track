# -*- coding: utf-8 -*-
"""比较四种「彩色帧 -> 640x360 灰度」写法在板子上的耗时。"""
import time

import cv2

cap = cv2.VideoCapture("/root/photos.mp4")
ok, f = cap.read()
print("frame", f.shape)

CASES = [
    ("cvtColor->resize AREA", lambda x: cv2.resize(
        cv2.cvtColor(x, cv2.COLOR_BGR2GRAY), (640, 360), interpolation=cv2.INTER_AREA)),
    ("cvtColor->resize LINEAR", lambda x: cv2.resize(
        cv2.cvtColor(x, cv2.COLOR_BGR2GRAY), (640, 360), interpolation=cv2.INTER_LINEAR)),
    ("cvtColor->resize NEAREST", lambda x: cv2.resize(
        cv2.cvtColor(x, cv2.COLOR_BGR2GRAY), (640, 360), interpolation=cv2.INTER_NEAREST)),
    ("resize_first->cvtColor", lambda x: cv2.cvtColor(
        cv2.resize(x, (640, 360), interpolation=cv2.INTER_LINEAR), cv2.COLOR_BGR2GRAY)),
]

for name, fn in CASES:
    for _ in range(3):
        fn(f)
    t0 = time.time()
    for _ in range(20):
        fn(f)
    print("  %-26s %.2f ms" % (name, (time.time() - t0) / 20 * 1000))
