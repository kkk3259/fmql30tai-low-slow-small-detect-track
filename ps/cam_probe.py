#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# cam_probe.py —— 只测摄像头：分辨率、帧率、存一张 JPEG
import time, sys
import cv2, numpy as np

def main():
    cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    if not cap.isOpened():
        print("ERROR: 打不开 /dev/video0")
        return 1
    ok, f = cap.read()
    if not ok:
        print("ERROR: 首帧失败")
        return 1
    print("首帧 %dx%d dtype=%s" % (f.shape[1], f.shape[0], f.dtype))
    cv2.imwrite("/tmp/cam_full.jpg", f)
    small = cv2.resize(f, (640, 360), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    cv2.imwrite("/tmp/cam_gray.jpg", gray)
    print("灰度图 mean=%.1f min=%d max=%d  → /tmp/cam_gray.jpg" %
          (gray.mean(), gray.min(), gray.max()))
    n, t0 = 0, time.time()
    for _ in range(30):
        ok, f = cap.read()
        if not ok:
            continue
        small = cv2.resize(f, (640, 360), interpolation=cv2.INTER_AREA)
        g = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        n += 1
    dt = time.time() - t0
    print("30 帧耗时 %.2f 秒 → %.1f fps（含 resize+gray）" % (dt, n / dt))
    cap.release()
    return 0

if __name__ == "__main__":
    sys.exit(main())
