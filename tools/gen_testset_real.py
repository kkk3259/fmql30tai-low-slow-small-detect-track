#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用**真实视频帧**当背景，生成带真值的小目标测试集（替掉 numpy 合成背景）。

为什么换：原来 grass/sea/night 三种背景是随机噪声造的，纹理统计不真实，
检测器在那种"假纹理"上全 0 候选，不能代表真实场景能力。

做法：从真实视频里取帧当背景 → 在上面画已知尺寸/对比度的目标 → 记录每帧真值。

用法：python3 gen_testset_real.py /root/ts_real
"""
import json
import os
import sys

import cv2
import numpy as np

W, H, FPS, NFRAME = 640, 360, 30, 60

# 背景源：真实视频（取中间段，避开片头片尾）
SOURCES = [
    ("bird", "/root/bird.mp4"),
    ("user2", "/root/user2.mp4"),
    ("photos", "/root/photos.mp4"),
]

# (名字, 源序号, 明暗, 尺寸px, 对比度, 起点, 速度)
CASES = [
    ("real_bird_bright_12_hi", 0, False, 12, 160, (60, 60), (4.0, 1.2)),
    ("real_bird_dark_12_hi",   0, True,  12, 160, (60, 300), (4.0, -1.0)),
    ("real_bird_dark_6_mid",   0, True,   6, 60,  (100, 80), (3.0, 0.6)),
    ("real_user2_bright_24",   1, False, 24, 90,  (80, 100), (3.5, 0.8)),
    ("real_user2_dark_12",     1, True,  12, 70,  (120, 240), (4.0, -0.8)),
    ("real_user2_dark_6_low",  1, True,   6, 18,  (200, 120), (3.0, 0.5)),
    ("real_photos_bright_12",  2, False, 12, 80,  (300, 200), (3.0, -0.7)),
    ("real_photos_bright_6",   2, False,  6, 70,  (100, 180), (3.5, 0.6)),
    ("real_photos_dark_24_low",2, True,  24, 30,  (400, 100), (-3.0, 0.9)),
    ("real_bird_dark_3_hi",    0, True,   3, 170, (60, 200), (4.5, 0.3)),
    ("real_user2_bright_40_hi",1, False, 40, 150, (60, 60), (5.0, 1.0)),
]


def grab_backgrounds(path, n=3):
    """从视频里均匀取 n 帧当背景（灰度 640x360）。"""
    cap = cv2.VideoCapture(path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    out = []
    if total <= 0:
        cap.release()
        return out
    for k in range(n):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * (0.2 + 0.3 * k)))
        ok, img = cap.read()
        if not ok:
            continue
        g = cv2.cvtColor(cv2.resize(img, (W, H)), cv2.COLOR_BGR2GRAY)
        out.append(g)
    cap.release()
    return out


def draw_target(bg, cx, cy, size, contrast, dark):
    img = bg.copy()
    half = size // 2
    x0, x1 = max(0, cx - half), min(W, cx + half)
    y0, y1 = max(0, cy - half), min(H, cy + half)
    if x1 <= x0 or y1 <= y0:
        return img
    bgv = float(np.mean(bg[y0:y1, x0:x1]))
    v = bgv - contrast if dark else bgv + contrast
    v = int(np.clip(v, 0, 255))
    img[y0:y1, x0:x1] = v
    return img


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "/root/ts_real"
    os.makedirs(out, exist_ok=True)
    bgs = {}
    for name, path in SOURCES:
        bgs[name] = grab_backgrounds(path)
        print("背景 %-8s 取到 %d 帧" % (name, len(bgs[name])))

    index = []
    for i, (name, src, dark, size, contrast, start, vel) in enumerate(CASES):
        frames = bgs[SOURCES[src][0]]
        if not frames:
            print("跳过 %s（无背景）" % name)
            continue
        vw = cv2.VideoWriter(os.path.join(out, "scene_%02d.mp4" % i),
                             cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
        gt = []
        x, y = float(start[0]), float(start[1])
        for f in range(NFRAME):
            bg = frames[(f // 20) % len(frames)]
            cx = int(round(x)) % W
            cy = int(round(y)) % H
            img = draw_target(bg, cx, cy, size, contrast, dark)
            vw.write(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR))
            gt.append({"f": f, "x": cx, "y": cy, "size": size})
            x += vel[0]
            y += vel[1]
        vw.release()
        with open(os.path.join(out, "scene_%02d.json" % i), "w") as fp:
            json.dump({"name": name, "bg": SOURCES[src][0], "dark": dark,
                       "size": size, "contrast": contrast, "gt": gt}, fp)
        index.append({"idx": i, "name": name, "bg": SOURCES[src][0],
                      "dark": dark, "size": size, "contrast": contrast,
                      "frames": NFRAME, "gt_frames": len(gt)})
        print("  生成 %-24s %2dpx c=%3d" % (name, size, contrast))

    with open(os.path.join(out, "index.json"), "w") as fp:
        json.dump(index, fp, indent=1)
    print("DONE %d 场景 -> %s" % (len(index), out))


if __name__ == "__main__":
    main()
