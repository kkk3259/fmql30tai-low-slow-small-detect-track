#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""offline_yolo.py —— 用 yolo11n 离线跑视频，输出带框 mp4。

用法：offline_yolo.py <in.mp4> <out.mp4> [max_frames]
"""
import os
import subprocess
import sys

import cv2

sys.path.insert(0, "/root/ip2")
from yolo_det import Yolo  # noqa: E402


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "/root/bird.mp4"
    dst = sys.argv[2] if len(sys.argv) > 2 else "/root/yolo_vid.mp4"
    maxn = int(sys.argv[3]) if len(sys.argv) > 3 else 300

    cap = cv2.VideoCapture(src)
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    y = Yolo()
    ff = ("ffmpeg -y -f rawvideo -pix_fmt bgr24 -s %dx%d -r 15 -i - "
          "-c:v libx264 -crf 18 -pix_fmt yuv420p %s" % (W, H, dst))
    proc = subprocess.Popen(ff.split(), stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    n = 0
    tot = 0
    while n < maxn:
        ok, f = cap.read()
        if not ok:
            break
        bs = y.detect(f)
        tot += len(bs)
        for b in bs:
            x1, y1, x2, y2 = [int(v) for v in b[:4]]
            cv2.rectangle(f, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(f, "%.2f" % b[4], (x1, max(12, y1 - 5)), 0, 0.6, (0, 255, 0), 2)
        cv2.putText(f, "yolo11n  f%d  n=%d" % (n, len(bs)), (10, 28), 0, 0.8, (0, 255, 255), 2)
        proc.stdin.write(f.tobytes())
        n += 1
        if n % 30 == 0:
            print("  %d frames  cand/frame=%.1f" % (n, tot / max(1, n)), flush=True)
    proc.stdin.close()
    proc.wait()
    print("VID done %d frames cand/frame=%.1f -> %s" % (n, tot / max(1, n), dst))


if __name__ == "__main__":
    main()
