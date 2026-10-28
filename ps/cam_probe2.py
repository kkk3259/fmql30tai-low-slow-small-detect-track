#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# cam_probe2.py —— 测不同采集分辨率下的吞吐，找最快的配置
import time, sys
import cv2

W, H = 640, 360

def bench(cw, ch, fourcc, n=20):
    cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, cw)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, ch)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    if not cap.isOpened():
        return None
    ok, f = cap.read()
    if not ok:
        cap.release()
        return None
    real = (f.shape[1], f.shape[0])
    t0 = time.time()
    cnt = 0
    for _ in range(n):
        ok, f = cap.read()
        if not ok:
            continue
        g = cv2.cvtColor(cv2.resize(f, (W, H), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        cnt += 1
    dt = time.time() - t0
    cap.release()
    return real, cnt / dt * 1000.0 / max(cnt, 1), cnt / dt

def main():
    for cw, ch, fourcc in [(1280, 720, "MJPG"), (640, 480, "MJPG"), (960, 540, "MJPG"),
                           (640, 480, "YUYV"), (1280, 720, "YUYV")]:
        r = bench(cw, ch, fourcc)
        if r is None:
            print("%-5s 请求 %dx%d → 打不开/无帧" % (fourcc, cw, ch))
            continue
        real, ms, fps = r
        print("%-5s 请求 %4dx%-4d → 实际 %4dx%-4d  每帧 %6.1f ms  %5.1f fps" %
              (fourcc, cw, ch, real[0], real[1], ms, fps))
    return 0

if __name__ == "__main__":
    sys.exit(main())
