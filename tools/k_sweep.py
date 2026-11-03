# -*- coding: utf-8 -*-
"""CFAR 的 k 值离线扫描：用 numpy 复现 Top-Hat+CFAR 判决，比较不同 k 的
「真目标是否出候选」与「候选总数（虚警代理）」。

真目标框用人工标注（640x360 坐标系），只标确定无疑的。
"""
import json
import sys

import cv2
import numpy as np

sys.path.insert(0, r"./pl\tools") if False else None

W, H = 640, 360
SE = 5
WIN = 31
HALF = WIN // 2
FLOOR = 3.0

# 人工标注（x, y, 宽, 高），640x360 坐标，只看确定的目标
GT = {
    "t1_birds.png": [(63, 25, 14, 10), (295, 40, 16, 12)],       # 两只飞鸟
    "t2_twodrones.png": [(165, 85, 12, 12), (485, 245, 20, 10)],  # 无人机 + 飞机
    "t3_field_drone.png": [(378, 72, 18, 14)],                   # 无人机
    "t4_fourdrones.png": [(150, 150, 40, 30), (330, 170, 45, 30),
                          (455, 105, 70, 40), (510, 230, 35, 28)],  # 四架
    "t5_plane_drone.png": [(305, 160, 45, 18), (320, 365, 20, 12)],  # 飞机 + 无人机
    "t6_plane_bird.png": [(383, 180, 70, 22), (200, 268, 30, 16)],   # 客机 + 鸟
}


def tophat(gray):
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (SE, SE))
    return cv2.subtract(gray, cv2.morphologyEx(gray, cv2.MORPH_OPEN, k))


def cfar_mask(th, k, floor=FLOOR):
    """滑动窗口均值/标准差，返回过门限的二值图（等价 RTL 的平方判决）。"""
    f = th.astype(np.float32)
    ker = np.ones((WIN, WIN), np.float32)
    s1 = cv2.filter2D(f, -1, ker, borderType=cv2.BORDER_REPLICATE)
    s2 = cv2.filter2D(f * f, -1, ker, borderType=cv2.BORDER_REPLICATE)
    a = float(WIN * WIN)
    mu = s1 / a
    var = np.maximum(s2 / a - mu * mu, 0.0)
    return (f > mu + k * np.sqrt(var) + floor).astype(np.uint8)


def evaluate(mask, gt):
    n, lbl, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    cands = [(stats[i, 0] + stats[i, 2] / 2.0, stats[i, 1] + stats[i, 3] / 2.0,
              stats[i, 4]) for i in range(1, n) if stats[i, 4] >= 4]
    hit = 0
    for (gx, gy, gw, gh) in gt:
        for (cx, cy, ar) in cands:
            if gx - 6 <= cx <= gx + gw + 6 and gy - 6 <= cy <= gy + gh + 6:
                hit += 1
                break
    return hit, len(cands)


def main():
    ks = [3.0, 3.5, 4.0, 4.5, 5.0, 6.0]
    tot_gt = sum(len(v) for v in GT.values())
    print("真目标总数 =", tot_gt)
    print("%-6s %-8s %-10s %-10s" % ("k", "真目标检出", "候选总数", "精确率代理"))
    for k in ks:
        th_all = 0
        c_all = 0
        for name, gt in GT.items():
            p = "./data/" + name
            img = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            g = cv2.resize(img, (W, H), interpolation=cv2.INTER_AREA)
            for pol in (g, 255 - g):
                m = cfar_mask(tophat(pol), k)
                h, c = evaluate(m, gt)
                th_all += h
                c_all += c
        print("%-6.1f %-8d %-10d %-10.2f"
              % (k, th_all, c_all, th_all * 1.0 / max(1, c_all)))


if __name__ == "__main__":
    main()
