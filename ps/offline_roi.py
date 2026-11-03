#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""offline_roi.py —— 六张图跑「PL 粗筛 + NPU ROI 精判」离线对照。

流程与 cam3d_pipe --mode roi 完全一致：
  640×360 灰度 → PL3D.run() 出候选 → 每候选裁 96×96 → 4×4 拼成 640×640
  → yolo11n 一次前向 → 每 slot 取最高分映射回整帧 → 过滤 ROI_CONF

用法：offline_roi.py t1_birds.png [t2 ...]
"""
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, "/root/ip2")
from cam3d_test import PL3D  # noqa: E402
from yolo_det import Yolo   # noqa: E402

W, H = 640, 360
ROI_SIDE = 96
ROI_CELL = 4
ROI_CONF = 0.45


def run_one(pl, y, name):
    p = "/root/ip2/" + name
    img = cv2.imread(p)
    if img is None:
        print("%-22s IMG_FAIL" % name)
        return
    gray = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (W, H),
                      interpolation=cv2.INTER_AREA)
    c1, st, dt = pl.run(gray)
    c2, _s2, dt2 = pl.run(255 - gray)          # 双极性第二遍
    dt += dt2
    for c in c1:
        c["pol"] = 0
    for c in c2:
        c["pol"] = 1
    for c in c1 + c2:                          # 先补列相位偏移
        c["x"] = (c["x"] + 62) % W
    ok = [c for c in c1 + c2 if c["area"] >= 4 and c["peak"] >= 8
          and 4 <= c["y"] < H - 4 and 4 <= c["x"] < W - 4]
    # 两种极性各取前 8（按 peak），避免一路的虚警把另一路的真目标挤掉
    def _pick(cs, k=8, mind=40.0):
        # 按 peak 降序贪心，且彼此间隔 >= mind，避免树线/云边一堆挤满格子
        out = []
        for c in sorted(cs, key=lambda z: -z["peak"]):
            if all(((c["x"]-o["x"])**2 + (c["y"]-o["y"])**2) ** 0.5 >= mind for o in out):
                out.append(c)
            if len(out) >= k:
                break
        return out

    a = _pick([c for c in ok if c["pol"] == 0], 8)
    b = _pick([c for c in ok if c["pol"] == 1], 8)
    cands = c1 + c2
    keep = a + b
    cands_in = keep[:ROI_CELL * ROI_CELL]

    fused = []
    if cands_in:
        crops, meta = [], []
        for c in cands_in:
            hx = ROI_SIDE // 2
            x0 = int(min(max(c["x"] - hx, 0), max(0, W - ROI_SIDE)))
            y0 = int(min(max(c["y"] - hx, 0), max(0, H - ROI_SIDE)))
            crops.append(gray[y0:y0 + ROI_SIDE, x0:x0 + ROI_SIDE].copy())
            meta.append((x0, y0))
        res = y.detect_mosaic(crops, grid=ROI_CELL)
        best = {}
        for slot, x1, y1, x2, y2, sc in res:
            if slot >= len(meta):
                continue
            if slot not in best or sc > best[slot][4]:
                best[slot] = (x1, y1, x2, y2, sc)
        for i, c in enumerate(cands_in):
            if i in best:
                x1, y1, x2, y2, sc = best[i]
                x0, y0 = meta[i]
                fused.append({"x": int(x0 + (x1 + x2) / 2), "y": int(y0 + (y1 + y2) / 2),
                              "area": int(max(4.0, (x2 - x1) * (y2 - y1) / 4)),
                              "p": float(sc), "roi": 1})
            else:
                fused.append({"x": c["x"], "y": c["y"], "area": c["area"],
                              "p": 0.0, "roi": 0})

    hit = [c for c in fused if c["roi"] and c["p"] >= ROI_CONF]
    # 去重：半径按目标尺寸自适应（封顶 60px），保留高分框，不取并集
    kept = []
    for c in sorted(hit, key=lambda z: -z["p"]):
        w = max(8.0, 2.0 * (c["area"] ** 0.5))
        r = max(18.0, min(0.55 * w, 60.0))
        if all(((c["x"] - k["x"]) ** 2 + (c["y"] - k["y"]) ** 2) ** 0.5 > r for k in kept):
            kept.append(c)
    fused = [c for c in fused if (not c["roi"]) or c["p"] < ROI_CONF] + kept
    top = max([c["p"] for c in fused], default=0.0)
    print("%-22s PL=%2d  ROI判=%2d  过阈=%-2d  top=%.2f  PL耗时=%.1fms"
          % (name, len(cands), len([c for c in fused if c["roi"]]), len(hit), top, dt))

    vis = cv2.resize(img, (W, H))          # 用原彩色图做底，别画在灰度上
    for c in fused:
        if c["roi"] and c["p"] >= ROI_CONF:
            col, lab = (80, 230, 60), "%.0f%%" % (c["p"] * 100)
        elif c["roi"]:
            col, lab = (40, 150, 240), "%.0f%%" % (c["p"] * 100)
        else:
            col, lab = (200, 200, 200), "PL"
        r = max(8, int(1.1 * (c["area"] ** 0.5)))
        cv2.rectangle(vis, (c["x"] - r, c["y"] - r), (c["x"] + r, c["y"] + r), col, 2)
        cv2.putText(vis, lab, (c["x"] - r, max(12, c["y"] - r - 4)), 0, 0.55, col, 2)
    cv2.putText(vis, "roi  PL=%d  hit=%d" % (len(cands), len(hit)),
                (8, 26), 0, 0.8, (0, 235, 255), 2)
    cv2.imwrite("/root/ip2/roi_%s" % name, vis)


def main():
    names = sys.argv[1:] or ["t1_birds.png", "t2_twodrones.png", "t3_field_drone.png",
                             "t4_fourdrones.png", "t5_plane_drone.png", "t6_plane_bird.png"]
    pl = PL3D()
    y = Yolo(dev=pl.dev)
    print("PL3D + Yolo ready (shared dev)", flush=True)
    for n in names:
        try:
            run_one(pl, y, n)
        except Exception as e:                                    # noqa: BLE001
            print("%-22s ERR %s" % (n, e))
    print("ROI_TABLE_DONE")


if __name__ == "__main__":
    main()
