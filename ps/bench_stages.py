#!/usr/bin/env python3
# bench_stages.py —— 在板上逐段计时，找出帧率瓶颈
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, "/root/ip2")
import cam_pipe as cp


def bench(n=40):
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    for _ in range(5):
        cap.read()
    hw = cp.HW()
    tr = cp.Tracker()
    t_cap = t_gray = t_pl = t_mv = t_trk = t_draw = t_enc = 0.0
    for i in range(n):
        t0 = time.time()
        ok, frame = cap.read()
        t_cap += time.time() - t0
        t0 = time.time()
        if frame.shape[0] >= cp.H:
            top = (frame.shape[0] - cp.H) // 2
            frame = frame[top:top + cp.H, :, :]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        t_gray += time.time() - t0
        t0 = time.time()
        st, cands, dt = hw.run_ms(gray)
        t_pl += time.time() - t0
        t0 = time.time()
        if hasattr(tr, "peek"):
            pass
        t_mv += time.time() - t0
        t0 = time.time()
        shown = tr.update(cands)
        t_trk += time.time() - t0
        t0 = time.time()
        color = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        for t in shown:
            x, y = int(t["x"]), int(t["y"])
            cv2.rectangle(color, (x - 5, y - 5), (x + 5, y + 5), (0, 255, 0), 2)
        t_draw += time.time() - t0
        t0 = time.time()
        cv2.imencode(".jpg", color, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        t_enc += time.time() - t0
    print("帧数 %d，每帧均值(ms):" % n)
    print("  cap  %6.2f" % (t_cap * 1000 / n))
    print("  gray %6.2f" % (t_gray * 1000 / n))
    print("  PL   %6.2f  (run_ms=两遍)" % (t_pl * 1000 / n))
    print("  trk  %6.2f" % (t_trk * 1000 / n))
    print("  draw %6.2f" % (t_draw * 1000 / n))
    print("  enc  %6.2f" % (t_enc * 1000 / n))
    tot = (t_cap + t_gray + t_pl + t_trk + t_draw + t_enc) * 1000 / n
    print("  合计 %6.2f  -> 理论 %.1f fps" % (tot, 1000.0 / tot))


if __name__ == "__main__":
    bench()
