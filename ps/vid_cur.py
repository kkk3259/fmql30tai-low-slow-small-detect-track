#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vid_cur.py —— 用“现在的算法形态”跑视频：
   PL 粗筛（真隔帧双极性，每帧只跑一种极性，复用上一帧另一极性）
   → 裁 96x96 → mosaic 一次判 → 去重 → 画框
   启动时用 phase_cal3 自校准列相位（不写死）。
"""
import subprocess
import sys

import cv2
import numpy as np

sys.path.insert(0, "/root/ip2")
import phase_cal3 as cal  # noqa: E402
from cam3d_test import PL3D  # noqa: E402
from yolo_det import Yolo   # noqa: E402

W, H = 640, 360
SIDE, GRID, CONF = 96, 4, 0.45


def merge(cs):
    kept = []
    for c in sorted(cs, key=lambda z: -z["p"]):
        w = max(8.0, 2.0 * (c["area"] ** 0.5))
        r = max(18.0, min(0.55 * w, 60.0))
        if all(((c["x"] - k["x"]) ** 2 + (c["y"] - k["y"]) ** 2) ** 0.5 > r for k in kept):
            kept.append(c)
    return kept


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "/root/bird.mp4"
    dst = sys.argv[2] if len(sys.argv) > 2 else "/root/vid_cur.mp4"
    maxn = int(sys.argv[3]) if len(sys.argv) > 3 else 240

    cap = cv2.VideoCapture(src)
    vw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    vh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    pl = PL3D()
    y = Yolo(dev=pl.dev)

    ok, f0 = cap.read()
    g0 = cv2.resize(cv2.cvtColor(f0, cv2.COLOR_BGR2GRAY), (W, H), interpolation=cv2.INTER_AREA)
    c0, _s, _d = pl.run(g0)
    shift, conf, _v = cal.estimate(g0, c0, W, H)
    print("CAL shift=%+d conf=%.2f" % (shift, conf), flush=True)
    if conf < 0.50:                 # 置信度不足时不采用，避免整段视频偏 64px
        print("CAL 置信度不足，按 0 处理", flush=True)
        shift = 0
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    ff = ("ffmpeg -y -f rawvideo -pix_fmt bgr24 -s %dx%d -r 15 -i - "
          "-c:v libx264 -crf 18 -pix_fmt yuv420p %s" % (W, H, dst))
    proc = subprocess.Popen(ff.split(), stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    prev = None
    n = tot = 0
    while n < maxn:
        ok, f = cap.read()
        if not ok:
            break
        g = cv2.resize(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (W, H),
                       interpolation=cv2.INTER_AREA)
        pol = n % 2
        cur, _s, _d = pl.run(255 - g if pol else g)
        for c in cur:
            c["pol"] = pol
        cs = [dict(c) for c in cur]
        if prev is not None and prev[0] == n - 1:
            for c in prev[1]:
                if c["pol"] != pol and all(
                        abs(c["x"] - k["x"]) + abs(c["y"] - k["y"]) > 12 for k in cs):
                    cs.append(dict(c))
        prev = (n, [dict(c) for c in cur])

        cands = []
        for c in cs:
            x = (c["x"] + shift) % W
            if not (8 <= x < W - 8 and 4 <= c["y"] < H - 4) or c["peak"] < 8:
                continue
            cands.append({"x": x, "y": c["y"], "area": c["area"], "peak": c["peak"]})
        cands.sort(key=lambda z: -z["peak"])
        keep = cands[:GRID * GRID]

        hits = []
        if keep:
            crops = []
            for k in keep:
                x0 = int(min(max(k["x"] - SIDE // 2, 0), W - SIDE))
                y0 = int(min(max(k["y"] - SIDE // 2, 0), H - SIDE))
                crops.append(g[y0:y0 + SIDE, x0:x0 + SIDE].copy())
            res = y.detect_mosaic(crops, grid=GRID)
            for slot, x1, y1, x2, y2, sc in res:
                if sc < CONF:
                    continue
                k = keep[slot] if slot < len(keep) else None
                if k is None:
                    continue
                cx = k["x"] + (x1 + x2) / 2.0 - SIDE / 2.0
                cy = k["y"] + (y1 + y2) / 2.0 - SIDE / 2.0
                hits.append({"x": cx, "y": cy, "area": k["area"], "p": sc})
        hits = merge(hits)
        tot += len(hits)

        vis = cv2.resize(f, (W, H))
        for k in keep:
            cv2.rectangle(vis, (k["x"] - 14, k["y"] - 14), (k["x"] + 14, k["y"] + 14),
                          (170, 170, 170), 1)
        for k in hits:
            cv2.rectangle(vis, (int(k["x"]) - 18, int(k["y"]) - 18),
                          (int(k["x"]) + 18, int(k["y"]) + 18), (60, 210, 60), 2)
            cv2.putText(vis, "%.0f%%" % (k["p"] * 100), (int(k["x"]) - 18, int(k["y"]) - 22),
                        0, 0.55, (60, 210, 60), 2)
        cv2.putText(vis, "PL=%d hit=%d shift=%+d  f%d" % (len(cands), len(hits), shift, n),
                    (10, 26), 0, 0.75, (0, 255, 255), 2)
        proc.stdin.write(vis.tobytes())
        n += 1
        if n % 40 == 0:
            print("  %d frames hit/f=%.2f" % (n, tot / n), flush=True)
    proc.stdin.close()
    proc.wait()
    print("VID done %d frames hit/f=%.2f -> %s" % (n, tot / max(1, n), dst))


if __name__ == "__main__":
    main()
