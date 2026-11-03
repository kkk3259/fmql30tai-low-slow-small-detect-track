#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# bench_cap.py —— 分开量：capture.read() / 裁剪+灰度 / JPEG 编码，各多少毫秒
import time, sys
import cv2
import numpy as np

W, H = 640, 360

def bench(cw, ch, fourcc, n=25):
    cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, cw)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, ch)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    if not cap.isOpened():
        return None
    # 预热
    for _ in range(3):
        cap.read()
    t_read = t_prep = t_enc = 0.0
    cnt = 0
    real = (0, 0)
    for _ in range(n):
        t0 = time.time()
        ok, f = cap.read()
        t1 = time.time()
        if not ok:
            continue
        real = (f.shape[1], f.shape[0])
        fh = f.shape[0]
        if fh >= H:
            top = (fh - H) // 2
            f = f[top:top + H, :, :]
        else:
            f = cv2.resize(f, (W, H), interpolation=cv2.INTER_AREA)
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        t2 = time.time()
        cv2.imencode(".jpg", f, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
        t3 = time.time()
        t_read += t1 - t0
        t_prep += t2 - t1
        t_enc += t3 - t2
        cnt += 1
    cap.release()
    if not cnt:
        return None
    return real, t_read / cnt * 1000, t_prep / cnt * 1000, t_enc / cnt * 1000, cnt / (t_read + t_prep + t_enc) * cnt

def main():
    for cw, ch, fourcc in [(640, 480, "MJPG"), (640, 480, "YUYV"),
                           (800, 600, "MJPG"), (1280, 720, "MJPG"),
                           (640, 360, "MJPG"), (640, 360, "YUYV")]:
        r = bench(cw, ch, fourcc)
        if r is None:
            print("%-5s %dx%d → 打不开/无帧" % (fourcc, cw, ch))
            continue
        real, rd, prep, enc, fps = r
        print("%-5s 请求 %4dx%-4d 实际 %4dx%-4d | read %6.2f ms | 裁+灰 %6.2f ms | 编码 %6.2f ms | 合计上限 %5.1f fps"
              % (fourcc, cw, ch, real[0], real[1], rd, prep, enc, fps))
    return 0

if __name__ == "__main__":
    sys.exit(main())
