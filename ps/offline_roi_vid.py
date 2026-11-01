#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""offline_roi_vid.py —— 视频走「PL 粗筛 + NPU ROI 精判」离线出结果。

与 cam3d_pipe --mode roi 完全同一条链路：
  帧→640×360 灰度 → PL3D.run() 出候选 → 每候选裁 96×96 → 4×4 拼 640×640
  → yolo11n 一次 forward → 每 slot 取最高分映射回整帧 → 过滤 ROI_CONF → 画框

用法：offline_roi_vid.py <in.mp4> <out.mp4> [max_frames]
"""
import subprocess
import sys

import cv2
import numpy as np
sys.path.insert(0, "/root/ip2")
from cam3d_test import PL3D  # noqa: E402
from yolo_det import Yolo   # noqa: E402

W, H = 640, 360
# ROI 边长可调：目标只有 10 px 时，96 的裁剪放大 1.67× 仍不够，改 32 得到 5×
ROI_SIDE = int(__import__("os").environ.get("ROI_SIDE", "96"))
ROI_CELL, ROI_CONF = 4, 0.45
INVERT = int(__import__("os").environ.get("INVERT", "1"))   # 默认取反：亮天空里的暗鸟
# PL 的列坐标有固定相位偏移（实测 x_true = x_det + 62），不补正 ROI 会裁到目标旁边
X_SHIFT = int(__import__("os").environ.get("X_SHIFT", "62"))
DUAL = int(__import__("os").environ.get("DUAL", "1"))


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "/root/bird.mp4"
    dst = sys.argv[2] if len(sys.argv) > 2 else "/root/roi_bird.mp4"
    maxn = int(sys.argv[3]) if len(sys.argv) > 3 else 300

    pl = PL3D()
    y = Yolo(dev=pl.dev)
    print("PL3D + Yolo ready (shared dev)", flush=True)

    cap = cv2.VideoCapture(src)
    ow = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    oh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    ff = ("ffmpeg -y -f rawvideo -pix_fmt bgr24 -s %dx%d -r 15 -i - "
          "-c:v libx264 -crf 18 -pix_fmt yuv420p %s" % (ow, oh, dst))
    proc = subprocess.Popen(ff.split(), stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    n = tot_pl = tot_hit = 0
    while n < maxn:
        ok, frame = cap.read()
        if not ok:
            break
        vis = frame.copy()
        gray = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (W, H),
                          interpolation=cv2.INTER_AREA)
        # PL 只认亮目标：暗目标（亮天空里的鸟）必须先取反
        if INVERT:
            gray = 255 - gray
        cands, st, dt = pl.run(gray)
        # 双极性：每 2 帧跑一次取反，合并候选（间距>12px 才加入）
        if DUAL and (n % 2 == 0):
            c2, _s2, dt2 = pl.run(255 - gray)
            dt += dt2
            for c in c2:
                if all(abs(c["x"] - k["x"]) + abs(c["y"] - k["y"]) > 12 for k in cands):
                    cands.append(c)
        keep = [c for c in cands if c["area"] >= 4 and c["peak"] >= 8
                and 8 <= c["y"] < H - 8 and 8 <= c["x"] < W - 8]
        for c in keep:
            c["x"] = (c["x"] + X_SHIFT) % W        # 补列相位偏移
        keep.sort(key=lambda c: -c["peak"])
        cin = keep[:ROI_CELL * ROI_CELL]
        fused = []
        if cin:
            crops, meta = [], []
            for c in cin:
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
            for i, c in enumerate(cin):
                if i in best:
                    x1, y1, x2, y2, sc = best[i]
                    x0, y0 = meta[i]
                    fused.append({"x": x0 + (x1 + x2) / 2, "y": y0 + (y1 + y2) / 2,
                                  "w": x2 - x1, "h": y2 - y1, "p": float(sc), "roi": 1})
                else:
                    fused.append({"x": c["x"], "y": c["y"], "w": 14, "h": 14,
                                  "p": 0.0, "roi": 0})
        hit = [c for c in fused if c["roi"] and c["p"] >= ROI_CONF]
        tot_pl += len(cands)
        tot_hit += len(hit)
        sx, sy = ow / float(W), oh / float(H)
        for c in fused:
            cx, cy = c["x"] * sx, c["y"] * sy
            hw, hh = max(8.0, c["w"] * sx / 2), max(8.0, c["h"] * sy / 2)
            if c["roi"] and c["p"] >= ROI_CONF:
                col, lab = (80, 230, 60), "%.0f%%" % (c["p"] * 100)
            elif c["roi"]:
                col, lab = (40, 150, 240), "%.0f%%" % (c["p"] * 100)
            else:
                col, lab = (190, 190, 190), "PL"
            cv2.rectangle(vis, (int(cx - hw), int(cy - hh)), (int(cx + hw), int(cy + hh)), col, 2)
            cv2.putText(vis, lab, (int(cx - hw), max(14, int(cy - hh) - 5)), 0, 0.7, col, 2)
        cv2.putText(vis, "roi f%d  PL=%d  hit=%d" % (n, len(cands), len(hit)),
                    (10, 32), 0, 0.9, (0, 235, 255), 2)
        proc.stdin.write(vis.tobytes())
        n += 1
        if n % 30 == 0:
            print("  %d frames  PL/f=%.1f hit/f=%.2f" % (n, tot_pl / n, tot_hit / n), flush=True)
    proc.stdin.close()
    proc.wait()
    print("ROIVID done %d frames PL/f=%.1f hit/f=%.2f -> %s"
          % (n, tot_pl / max(1, n), tot_hit / max(1, n), dst))


if __name__ == "__main__":
    main()
