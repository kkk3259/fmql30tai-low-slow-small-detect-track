# -*- coding: utf-8 -*-
"""prof2.py —— 在板上把主循环各段耗时打出来（不含 web）。"""
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, "/root/ip2")

W, H = 640, 360
cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))

for i in range(5):
    cap.read()

acc = {"cap": 0.0, "gray": 0.0, "enc": 0.0}
n = 20
for i in range(n):
    t0 = time.time()
    ok, f = cap.read()
    t1 = time.time()
    g = cv2.cvtColor(f[60:420, :], cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, (W, H), interpolation=cv2.INTER_LINEAR)
    t2 = time.time()
    vis = cv2.resize(f, (W, H))
    ok2, buf = cv2.imencode(".jpg", vis, [cv2.IMWRITE_JPEG_QUALITY, 65])
    t3 = time.time()
    acc["cap"] += (t1 - t0) * 1000
    acc["gray"] += (t2 - t1) * 1000
    acc["enc"] += (t3 - t2) * 1000
cap.release()
for k, v in acc.items():
    print("%-6s %.1f ms" % (k, v / n))
print("串行合计 %.1f ms -> %.1f fps" % (sum(acc.values()) / n, 1000.0 / (sum(acc.values()) / n)))
