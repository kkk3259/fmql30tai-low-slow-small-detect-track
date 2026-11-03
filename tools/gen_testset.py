#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成“带真值”的小目标检测测试集（多场景，防单一性）。

为什么不用网上视频：网上视频没有真值，只能“看着像”；本脚本每帧都记录
目标真实坐标/尺寸/对比度，才能算召回率、精确率、定位误差这些硬指标。

场景矩阵（10 段）：
  背景  sky / clouds / grass / sea / night
  目标  dark / bright
  尺寸  3 / 6 / 12 / 24 / 40 px
  对比  高(160) / 中(60) / 低(18)
  运动  匀速 / 轻微加速

输出：
  <out>/scene_XX.mp4       （640×360，30 fps）
  <out>/scene_XX.json      （每帧的目标真值列表）
  <out>/index.json         （场景参数汇总）
"""
import argparse
import json
import os

import cv2
import numpy as np

W, H = 640, 360
FPS = 30


def bg_sky(rng, w, h):
    """晴朗天空：上深下浅的渐变 + 轻微噪声。"""
    grad = np.linspace(60, 200, h).astype(np.float32)[:, None]
    img = np.repeat(grad, w, axis=1) + rng.normal(0, 1.5, (h, w))
    return np.clip(img, 0, 255).astype(np.uint8)


def bg_clouds(rng, w, h):
    """有云的天空：低频噪声当云团，对比更强。"""
    img = bg_sky(rng, w, h).astype(np.float32)
    small = rng.normal(128, 46, (h // 24 + 1, w // 24 + 1)).astype(np.float32)
    cloud = cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC)
    cloud = np.clip(cloud, 0, 255)
    return np.clip(0.55 * img + 0.45 * cloud, 0, 255).astype(np.uint8)


def bg_grass(rng, w, h):
    """草地：高频纹理，模拟复杂地物背景。"""
    base = rng.normal(95, 26, (h, w)).astype(np.float32)
    tex = rng.normal(0, 14, (h // 2, w // 2)).astype(np.float32)
    tex = cv2.resize(tex, (w, h), interpolation=cv2.INTER_NEAREST)
    return np.clip(base + tex, 0, 255).astype(np.uint8)


def bg_sea(rng, w, h):
    """海面：横向波纹。"""
    yy = np.arange(h)[:, None]
    wave = 18 * np.sin(yy / 7.0) + 10 * np.sin(yy / 2.3)
    img = np.repeat(wave + 110, w, axis=1) + rng.normal(0, 5, (h, w))
    return np.clip(img, 0, 255).astype(np.uint8)


def bg_night(rng, w, h):
    """夜间低照度：整体暗 + 高噪点（考验阈值）。"""
    img = rng.normal(38, 12, (h, w))
    return np.clip(img, 0, 255).astype(np.uint8)


BG = {"sky": bg_sky, "clouds": bg_clouds, "grass": bg_grass, "sea": bg_sea, "night": bg_night}


def put_target(img, x, y, size, contrast, dark):
    """在 (x,y) 处放一个 size×size 的目标，对比度 contrast（相对背景均值）。"""
    h, w = img.shape
    x0, y0 = int(x - size // 2), int(y - size // 2)
    x1, y1 = x0 + size, y0 + size
    if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
        return None
    roi = img[y0:y1, x0:x1].astype(np.int16)
    m = int(roi.mean())
    v = m - contrast if dark else m + contrast
    v = max(0, min(255, v))
    img[y0:y1, x0:x1] = v
    return {"x": int(x), "y": int(y), "size": int(size), "peak": int(abs(contrast)), "dark": bool(dark)}


SCENES = [
    # (名字, 背景, 暗/亮, 尺寸, 对比度, 起点, 速度)
    ("sky_bright_12_hi",  "sky",    False, 12, 160, (60, 60),    (4.0, 1.2)),
    ("sky_dark_12_hi",    "sky",    True,  12, 160, (60, 300),   (4.0, -1.0)),
    ("sky_dark_6_mid",    "sky",    True,   6, 60,  (100, 80),   (3.0, 0.6)),
    ("clouds_bright_24",  "clouds", False, 24, 90,  (40, 60),    (2.0, 1.0)),
    ("clouds_dark_12",    "clouds", True,  12, 70,  (80, 320),   (2.5, -0.8)),
    ("grass_dark_6_low",  "grass",  True,   6, 18,  (60, 100),   (3.5, 0.5)),
    ("grass_bright_12",   "grass",  False, 12, 80,  (50, 260),   (4.5, -0.4)),
    ("sea_bright_6",      "sea",    False,  6, 70,  (80, 150),   (3.0, 0.2)),
    ("sea_dark_24_low",   "sea",    True,  24, 30,  (60, 200),   (2.0, 0.3)),
    ("night_bright_12",   "night",  False, 12, 90,  (90, 180),   (2.5, 0.9)),
    ("sky_dark_3_hi",     "sky",    True,   3, 170, (120, 120),  (3.0, 0.8)),
    ("sky_bright_40_hi",  "sky",    False, 40, 150, (100, 150),  (2.0, 0.0)),
]


def make_scene(out_dir, idx, name, bg, dark, size, contrast, start, vel, nframes=90):
    rng = np.random.default_rng(1000 + idx)
    vw = cv2.VideoWriter(os.path.join(out_dir, "scene_%02d.mp4" % idx),
                         cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    gt = []
    for f in range(nframes):
        img = BG[bg](rng, W, H)
        # 轻微加速
        t = f
        x = start[0] + vel[0] * t + 0.004 * vel[0] * t * t
        y = start[1] + vel[1] * t + 0.004 * vel[1] * t * t
        g = put_target(img, x, y, size, contrast, dark)
        if g is not None:
            g["f"] = f
            gt.append(g)
        vw.write(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR))
    vw.release()
    meta = {"idx": idx, "name": name, "bg": bg, "dark": bool(dark), "size": int(size),
            "contrast": int(contrast), "frames": nframes, "gt": gt}
    with open(os.path.join(out_dir, "scene_%02d.json" % idx), "w", encoding="utf-8") as fh:
        json.dump(meta, fh)
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=r"./data/testset")
    ap.add_argument("--frames", type=int, default=90)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    index = []
    for i, (name, bg, dark, size, contrast, start, vel) in enumerate(SCENES):
        m = make_scene(a.out, i, name, bg, dark, size, contrast, start, vel, a.frames)
        n_gt = len(m["gt"])
        print("scene_%02d %-20s bg=%-6s %s %2dpx c=%3d 有效帧=%d"
              % (i, name, bg, "暗" if dark else "亮", size, contrast, n_gt))
        index.append({k: m[k] for k in ("idx", "name", "bg", "dark", "size", "contrast", "frames")})
        index[-1]["gt_frames"] = n_gt
    with open(os.path.join(a.out, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False, indent=1)
    print("共 %d 段，输出目录 %s" % (len(index), a.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
