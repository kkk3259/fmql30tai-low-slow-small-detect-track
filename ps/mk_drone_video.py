#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mk_drone_video.py —— 用 t4（四架无人机剪影，真实天空背景）合成一段无人机视频。

做法：以 t4 为源，做一个缓慢的推拉 + 平移镜头，输出 960x544 / 25fps / 240 帧。
这是**合成素材**（相机运动），不是真实航拍，仅用于验证检测链路。
"""
import cv2
import numpy as np
import subprocess

SRC = r"D:\firstharness\dl\t4_fourdrones.png"
DST = r"D:\firstharness\dl\drone_syn.mp4"
W, H, NF = 960, 544, 240

img = cv2.imread(SRC)
ih, iw = img.shape[:2]
print("src", iw, ih)

ff = ("ffmpeg -y -f rawvideo -pix_fmt bgr24 -s %dx%d -r 25 -i - "
      "-c:v libx264 -crf 18 -pix_fmt yuv420p %s" % (W, H, DST))
p = subprocess.Popen(ff.split(), stdin=subprocess.PIPE,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

for n in range(NF):
    t = n / float(NF - 1)
    # 缩放：1.0 -> 0.55（目标变小，模拟远离）再回到 0.75
    s = 1.0 - 0.45 * (t if t < 0.5 else 1.0 - t * 2 * 0.33) if True else 1.0
    s = max(0.55, min(1.0, s))
    # 平移：横向来回
    cx = iw * (0.5 + 0.18 * np.sin(2 * np.pi * t))
    cy = ih * (0.5 + 0.10 * np.cos(2 * np.pi * t * 1.3))
    hw, hh = iw * s / 2.0, iw * s / 2.0 * (H / float(W))
    x0 = int(max(0, min(iw - 2 * hw, cx - hw)))
    y0 = int(max(0, min(ih - 2 * hh, cy - hh)))
    crop = img[y0:y0 + int(2 * hh), x0:x0 + int(2 * hw)]
    if crop.size == 0:
        crop = img
    frame = cv2.resize(crop, (W, H), interpolation=cv2.INTER_AREA)
    cv2.putText(frame, "syn f%d" % n, (10, 28), 0, 0.8, (0, 255, 255), 2)
    p.stdin.write(frame.tobytes())
    if n % 60 == 0:
        print("  %d" % n, flush=True)

p.stdin.close()
p.wait()
print("VID done %d frames -> %s" % (NF, DST))
