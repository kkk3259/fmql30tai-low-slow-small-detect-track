#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成“像真的”小目标测试集（v2）。

相比 v1（纯色底 + 白方块）的提升：
  1. 目标不再是方块 —— 鸟/四旋翼/飞机/车/人的**剪影**，带旋转
  2. 抗锯齿 —— 8 倍超采样后缩回，边缘是真实的灰度过渡
  3. 距离模糊 —— 高斯 PSF，σ 随目标尺寸增大（模拟大气/散焦）
  4. 运动模糊 —— 沿速度方向做线性卷积
  5. 传感器噪声 —— 泊松 + 高斯，模拟低照度
  6. JPEG 压缩 —— 按 q88 重编码，模拟相机输出
  7. 一帧多个目标 —— 3~9 个同时出现，尺寸/对比度各不相同
  8. 背景在动 —— 云缓慢漂移（不只目标在动）

输出（每段 120 帧 640×360）：
  D:/firstharness/dl/testset2/scene_XX.mp4
  D:/firstharness/dl/testset2/scene_XX.json   每帧真值
  D:/firstharness/dl/testset2/index.json
  D:/firstharness/dl/testset2_sheet.jpg       拼图预览

用法：
  python tools/gen_testset2.py                # 全部生成
  python tools/gen_testset2.py --scenes 4     # 只生成前 4 段
"""
import argparse
import json
import os

import cv2
import numpy as np

W, H = 640, 360
FPS = 30
FRAMES = 120
OUT = r"D:\firstharness\dl\testset2"
SS = 8  # 超采样倍数


# --------------------------------------------------------------------------
# 背景
# --------------------------------------------------------------------------
def _smooth_noise(shape, scale, octaves=5, seed=0):
    """多倍频平滑噪声（近似 Perlin），返回 0~1。"""
    rng = np.random.default_rng(seed)
    acc = np.zeros(shape, np.float32)
    amp, tot = 1.0, 0.0
    for o in range(octaves):
        h = max(2, int(shape[0] / (scale / (2 ** o))))
        w = max(2, int(shape[1] / (scale / (2 ** o))))
        g = rng.random((h, w)).astype(np.float32)
        acc += cv2.resize(g, (shape[1], shape[0]), interpolation=cv2.INTER_CUBIC) * amp
        tot += amp
        amp *= 0.55
    acc /= tot
    acc -= acc.min()
    acc /= max(acc.max(), 1e-6)
    return acc


def bg_sky(seed):
    base = np.linspace(200, 130, H, dtype=np.float32)[:, None] * np.ones((1, W), np.float32)
    cloud = _smooth_noise((H, W), 90, 6, seed)
    cloud = np.clip((cloud - 0.42) * 2.6, 0, 1)
    img = base + cloud * 55
    return np.clip(img, 0, 255).astype(np.uint8)


def bg_grass(seed):
    """草地：大块明暗（树影/地形）+ 细密草叶（拉长的高频）。"""
    big = _smooth_noise((H, W), 120, 4, seed)
    blade = _smooth_noise((H // 3, W), 4, 4, seed + 3)
    blade = cv2.resize(blade, (W, H), interpolation=cv2.INTER_LINEAR)   # 竖向拉长 = 草叶感
    thin = _smooth_noise((H, W), 2, 3, seed + 5)
    img = 42 + big * 55 + blade * 60 + thin * 25
    return np.clip(img, 0, 255).astype(np.uint8)


def bg_sea(seed):
    """海面：水平长条 + 细碎波光（横向拉长，纵向压缩）。"""
    n = _smooth_noise((H, W // 24), 12, 4, seed)          # 先窄后拉宽 -> 横条
    n = cv2.resize(n, (W, H), interpolation=cv2.INTER_CUBIC)
    speck = _smooth_noise((H, W), 3, 3, seed + 7)
    img = 88 + n * 55 + speck * 22 + np.linspace(34, -26, H, dtype=np.float32)[:, None]
    return np.clip(img, 0, 255).astype(np.uint8)


def bg_night(seed):
    n = _smooth_noise((H, W), 50, 5, seed)
    img = 18 + n * 22
    return np.clip(img, 0, 255).astype(np.uint8)


BACKGROUNDS = {"sky": bg_sky, "grass": bg_grass, "sea": bg_sea, "night": bg_night}


# --------------------------------------------------------------------------
# 目标剪影（画在 SS 倍大小的画布上，再缩回 → 抗锯齿）
# --------------------------------------------------------------------------
def _canvas(sz):
    c = np.zeros((sz * SS, sz * SS), np.uint8)
    s = sz * SS
    return c, s


def draw_bird(sz):
    c, s = _canvas(sz)
    cx, cy = s // 2, s // 2
    # 双翼（两段弧）+ 身体
    pts_l = np.array([[cx, cy], [cx - s * 0.48, cy - s * 0.26], [cx - s * 0.30, cy + s * 0.02]], np.int32)
    pts_r = np.array([[cx, cy], [cx + s * 0.48, cy - s * 0.26], [cx + s * 0.30, cy + s * 0.02]], np.int32)
    cv2.fillPoly(c, [pts_l, pts_r], 255)
    cv2.ellipse(c, (cx, cy + s // 12), (s // 7, s // 5), 0, 0, 360, 255, -1)
    cv2.line(c, (cx, cy + s // 8), (cx, cy + s // 2), 255, max(2, s // 10))
    return c


def draw_drone(sz):
    c, s = _canvas(sz)
    cx, cy = s // 2, s // 2
    cv2.circle(c, (cx, cy), s // 7, 255, -1)
    for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
        ex, ey = cx + dx * s // 3, cy + dy * s // 3
        cv2.line(c, (cx, cy), (ex, ey), 255, max(2, s // 8))
        cv2.circle(c, (ex, ey), s // 9, 160, max(2, s // 14))
    return c


def draw_plane(sz):
    c, s = _canvas(sz)
    cx, cy = s // 2, s // 2
    cv2.line(c, (cx - s // 2, cy), (cx + s // 2, cy), 255, max(2, s // 6))
    cv2.line(c, (cx, cy - s // 3), (cx, cy + s // 3), 255, max(2, s // 7))
    cv2.line(c, (cx - s // 2, cy - s // 6), (cx - s // 3, cy), 255, max(2, s // 8))
    return c


def draw_car(sz):
    c, s = _canvas(sz)
    cv2.rectangle(c, (s // 8, s // 3), (s - s // 8, s - s // 4), 255, -1)
    cv2.rectangle(c, (s // 3, s // 5), (s - s // 3, s // 2), 255, -1)
    return c


def draw_man(sz):
    c, s = _canvas(sz)
    cv2.circle(c, (s // 2, s // 5), max(1, s // 5), 255, -1)
    cv2.rectangle(c, (s // 3, s // 3), (s - s // 3, s - s // 3), 255, -1)
    cv2.line(c, (s // 2, s - s // 3), (s // 3, s - s // 10), 255, max(2, s // 7))
    cv2.line(c, (s // 2, s - s // 3), (s - s // 3, s - s // 10), 255, max(2, s // 7))
    return c


SHAPES = {"bird": draw_bird, "drone": draw_drone, "plane": draw_plane,
          "car": draw_car, "man": draw_man}


def sprite(kind, sz, angle):
    big = SHAPES[kind](sz)
    m = cv2.getRotationMatrix2D((big.shape[1] / 2, big.shape[0] / 2), angle, 1.0)
    big = cv2.warpAffine(big, m, (big.shape[1], big.shape[0]), flags=cv2.INTER_CUBIC)
    small = cv2.resize(big, (sz, sz), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    # 距离模糊：目标越小越接近点扩散
    sigma = 0.35 + 0.02 * sz
    k = int(max(3, sigma * 6)) | 1
    small = cv2.GaussianBlur(small, (k, k), sigma)
    m = float(small.max())
    if m > 1e-6:
        small = small / m          # 峰值归一化：保证合成后目标中心真的偏离 ct 个灰度
    return small


def motion_blur(alpha, vx, vy):
    """沿速度方向做线性卷积（长度 ∝ 速度）。"""
    v = float(np.hypot(vx, vy))
    if v < 0.6:
        return alpha
    L = int(min(9, max(3, round(v * 1.4)))) | 1
    kern = np.zeros((L, L), np.float32)
    cv2.line(kern, (0, L // 2), (L - 1, L // 2), 1.0, 1)
    M = cv2.getRotationMatrix2D((L / 2 - 0.5, L / 2 - 0.5), -np.degrees(np.arctan2(vy, vx)), 1.0)
    kern = cv2.warpAffine(kern, M, (L, L))
    kern /= max(kern.sum(), 1e-6)
    return cv2.filter2D(alpha, -1, kern)


# --------------------------------------------------------------------------
# 场景
# --------------------------------------------------------------------------
SCENES = [
    # (名字, 背景, 目标种类, 尺寸范围, 对比度范围, 目标数, 亮/暗)
    ("sky_bird_multi", "sky", "bird", (4, 16), (60, 170), 5, "dark"),
    ("sky_drone_multi", "sky", "drone", (6, 22), (50, 150), 4, "both"),
    ("sky_plane_far", "sky", "plane", (8, 30), (40, 130), 3, "both"),
    ("sky_tiny", "sky", "bird", (2, 6), (80, 180), 7, "dark"),
    ("clouds_bird", "sky", "bird", (5, 18), (50, 140), 5, "both"),
    ("clouds_drone", "sky", "drone", (6, 20), (40, 120), 5, "both"),
    ("grass_man", "grass", "man", (6, 20), (40, 110), 4, "both"),
    ("grass_car", "grass", "car", (8, 26), (40, 120), 4, "both"),
    ("sea_plane", "sea", "plane", (6, 24), (40, 110), 4, "both"),
    ("sea_bird", "sea", "bird", (4, 14), (50, 130), 5, "both"),
    ("night_drone", "night", "drone", (6, 20), (70, 160), 4, "bright"),
    ("night_bird", "night", "bird", (4, 14), (80, 170), 5, "bright"),
]


def make_scene(name, bg_name, kind, sz_rng, ct_rng, count, polarity, seed):
    rng = np.random.default_rng(seed)
    base = BACKGROUNDS[bg_name](seed)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    path = os.path.join(OUT, name + ".mp4")
    vw = cv2.VideoWriter(path, fourcc, FPS, (W, H))
    if not vw.isOpened():
        raise RuntimeError("VideoWriter 打不开: " + path)

    objs = []
    for i in range(count):
        sz = int(rng.integers(sz_rng[0], sz_rng[1] + 1))
        ang = float(rng.uniform(0, 360))
        pol = polarity
        if polarity == "both":
            pol = "bright" if rng.random() < 0.5 else "dark"
        objs.append(dict(
            kind=kind, sz=sz, angle=ang, ang_v=float(rng.uniform(-6, 6)),
            x=float(rng.uniform(40, W - 40)), y=float(rng.uniform(40, H - 40)),
            vx=float(rng.uniform(-2.2, 2.2)), vy=float(rng.uniform(-1.2, 1.2)),
            ct=float(rng.uniform(*ct_rng)), pol=pol,
            sprite=None, last_ang=None))

    gts = []
    for f in range(FRAMES):
        # 背景缓慢漂移
        M = np.float32([[1, 0, -f * 0.25], [0, 1, -f * 0.06]])
        img = cv2.warpAffine(base, M, (W, H), borderMode=cv2.BORDER_REFLECT)
        img = img.astype(np.float32)

        gt = []
        for o in objs:
            o["x"] += o["vx"]
            o["y"] += o["vy"]
            if o["x"] < o["sz"] or o["x"] > W - o["sz"]:
                o["vx"] = -o["vx"]
                o["x"] = float(np.clip(o["x"], o["sz"], W - o["sz"]))
            if o["y"] < o["sz"] or o["y"] > H - o["sz"]:
                o["vy"] = -o["vy"]
                o["y"] = float(np.clip(o["y"], o["sz"], H - o["sz"]))
            o["angle"] += o["ang_v"]

            if o["sprite"] is None or abs(o["angle"] - o["last_ang"]) > 12:
                o["sprite"] = sprite(o["kind"], o["sz"], o["angle"])
                o["last_ang"] = o["angle"]
            a = motion_blur(o["sprite"], o["vx"], o["vy"])

            s = o["sz"]
            x0 = int(round(o["x"] - s / 2))
            y0 = int(round(o["y"] - s / 2))
            x0 = int(np.clip(x0, 0, W - s))
            y0 = int(np.clip(y0, 0, H - s))
            patch = img[y0:y0 + s, x0:x0 + s]
            sign = 1.0 if o["pol"] == "bright" else -1.0
            # 剪影只占 bbox 的一部分，合成前按 3.0 倍补偿，使“可测量的反差”落在 20~80 灰度
            img[y0:y0 + s, x0:x0 + s] = np.clip(patch + sign * o["ct"] * 3.0 * a, 0, 255)
            gt.append(dict(cx=round(float(o["x"]), 1), cy=round(float(o["y"]), 1),
                           size=int(s), ct=round(o["ct"], 1), pol=o["pol"]))

        # 传感器噪声 + 暗角 + JPEG
        x = img.astype(np.float32)
        x = x * (1.0 - 0.25 * ((np.linspace(-1, 1, W)[None, :] ** 2 +
                                np.linspace(-1, 1, H)[:, None] ** 2) / 2))
        noise = rng.normal(0, 2.2 + (8.0 if bg_name == "night" else 0.0), x.shape)
        x = np.clip(x + noise, 0, 255).astype(np.uint8)
        ok, enc = cv2.imencode(".jpg", x, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
        frame = cv2.imdecode(enc, cv2.IMREAD_GRAYSCALE)
        vw.write(cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR))
        gts.append({"frame": f, "targets": gt})

    vw.release()
    with open(os.path.join(OUT, name + ".json"), "w", encoding="utf-8") as fh:
        json.dump({"name": name, "bg": bg_name, "kind": kind,
                   "w": W, "h": H, "fps": FPS, "frames": FRAMES, "gt": gts}, fh)
    return path, gts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenes", type=int, default=len(SCENES))
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    index = []
    shots = []
    for i, (name, bg, kind, sz_rng, ct_rng, cnt, pol) in enumerate(SCENES[:a.scenes]):
        path, gts = make_scene(name, bg, kind, sz_rng, ct_rng, cnt, pol, seed=1000 + i)
        index.append({"name": name, "file": os.path.basename(path),
                      "json": name + ".json", "bg": bg, "kind": kind,
                      "targets_per_frame": cnt})
        print("[%2d/%d] %-18s %s/%s 目标%d  平均%.1f个/帧"
              % (i + 1, a.scenes, name, bg, kind, cnt,
                 np.mean([len(g["targets"]) for g in gts])))
        mp4 = cv2.VideoCapture(path)
        mp4.set(cv2.CAP_PROP_POS_FRAMES, 40)
        ok, fr = mp4.read()
        mp4.release()
        if ok:
            cv2.putText(fr, "%s %s %dpx" % (name, kind, cnt), (6, 16),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1, cv2.LINE_AA)
            shots.append(cv2.resize(fr, (320, 180)))

    with open(os.path.join(OUT, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False, indent=1)

    if shots:
        cols = 4
        rows = (len(shots) + cols - 1) // cols
        sheet = np.zeros((rows * 180, cols * 320, 3), np.uint8)
        for i, s in enumerate(shots):
            r, c = divmod(i, cols)
            sheet[r * 180:(r + 1) * 180, c * 320:(c + 1) * 320] = s
        p = r"D:\firstharness\dl\testset2_sheet.jpg"
        cv2.imwrite(p, sheet)
        print("拼图:", p)
    print("输出目录:", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
