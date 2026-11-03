# -*- coding: utf-8 -*-
"""CFAR 参数标定的完整 Pd-Fa 权衡表（真实图，PC 端）

问题：CFAR 的 k 与统计窗决定「召回」与「虚警」的权衡。P 的当前配置
      （TopHat, k=4.0, win=31, SE=21）在真实图上检出率偏低。
      本脚本在 100 张真实图上扫 k × win × 形态学方向，同时给出召回与虚警代价。

实测结果（2026-10-29，deploy/eval_roi_448 100 张，缩放到 640×360，SE=21）：

  模式    k    win   15-35  35-70  70-150  150-400  合计    候选/帧
  TopHat  4.0   31    40%    56%    48%     76%     55.0%   34.7   ← P 当前配置
  TopHat  3.0   31    60%    68%    84%     88%     75.0%   99.4
  TopHat  2.5   31    72%    84%    92%     96%     86.0%  175.5
  TopHat  2.0   51    80%    96%   100%    100%     94.0%  286.6
  Black   4.0   31    76%    52%    40%     76%     61.0%   15.9
  Black   3.0   31    84%    76%    84%    100%     86.0%   47.5   ← 推荐
  Black   2.5   31    80%    84%    96%    100%     90.0%   88.4
  Black   2.0   51    88%    88%   100%    100%     94.0%  183.3

结论：
  ① 当前配置（TopHat k=4.0）只有 55% 召回 —— 参数太严，不是硬件问题
  ② 同样 86% 召回下，Black-Hat 的候选数（47.5）只有 Top-Hat（175.5）的 1/3.7
     —— 真实场景目标是暗点，Black-Hat 的背景估计更干净
  ③ 推荐工作点：Black-Hat + k=3.0 + win=31（召回 86%、候选 47.5 < 64 格）
  ④ 若追求 94% 召回：Black + k=2.0 + win=51，但候选涨到 183（需 3 次 forward）
  ⑤ 降 k 的代价是虚警增加，但本架构后接 NPU 判真假，可承受较高虚警

用法：
  python tools/bench_cfar_tradeoff.py
"""
import os
import csv
import numpy as np
import cv2
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(REPO, "deploy", "eval_roi_448")
W, H = 640, 360
SE, FLOOR = 21, 3.0
MIN_AREA, MAX_AREA = 2, 200


def imread_cn(p):
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)


def load_cache():
    with open(os.path.join(BASE, "manifest.csv"), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    cache = []
    for r in rows:
        img = imread_cn(os.path.join(BASE, "images", r["文件"]))
        if img is None:
            continue
        h0, w0 = img.shape[:2]
        g = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (W, H),
                       interpolation=cv2.INTER_AREA)
        sx, sy = W / float(w0), H / float(h0)
        lp = os.path.join(BASE, "labels", r["文件"].replace(".jpg", ".txt"))
        gts = []
        for line in open(lp, encoding="utf-8"):
            p = line.split()
            if len(p) < 5:
                continue
            cx, cy, bw, bh = [float(x) for x in p[1:5]]
            gts.append((cx * w0 * sx, cy * h0 * sy, bw * w0 * sx, bh * h0 * sy))
        cache.append((r["尺寸档"], g, gts))
    return cache


def main():
    cache = load_cache()
    print("  预加载 %d 张（已缩放到 %d×%d，与 PL 输入一致）" % (len(cache), W, H))

    ker = cv2.getStructuringElement(cv2.MORPH_RECT, (SE, SE))

    def morph(g, mode):
        return cv2.morphologyEx(
            g, cv2.MORPH_TOPHAT if mode == "top" else cv2.MORPH_BLACKHAT, ker)

    def cfar(enh, win, k):
        f = enh.astype(np.float32)
        mu = cv2.boxFilter(f, -1, (win, win), normalize=True,
                           borderType=cv2.BORDER_REFLECT)
        mu2 = cv2.boxFilter(f * f, -1, (win, win), normalize=True,
                            borderType=cv2.BORDER_REFLECT)
        sd = np.sqrt(np.maximum(mu2 - mu * mu, 0))
        return ((f > mu + k * sd + FLOOR)).astype(np.uint8) * 255

    def run(mode, k, win, tol=2.0):
        stat = defaultdict(lambda: {"n": 0, "hit": 0, "nc": 0})
        for tier, g, gts in cache:
            binary = cfar(morph(g, mode), win, k)
            n, _lab, stats, cents = cv2.connectedComponentsWithStats(
                binary, connectivity=8)
            pts = []
            for i in range(1, n):
                a = stats[i, cv2.CC_STAT_AREA]
                if a < MIN_AREA or a > MAX_AREA:
                    continue
                pts.append((cents[i][0], cents[i][1]))
            s = stat[tier]
            s["n"] += 1
            s["nc"] += len(pts)
            hit = any(abs(x - gx) <= gw * tol / 2 and abs(y - gy) <= gh * tol / 2
                      for (gx, gy, gw, gh) in gts for (x, y) in pts)
            if hit:
                s["hit"] += 1
        tiers = ["15-35px", "35-70px", "70-150px", "150-400px"]
        vals = [stat[t]["hit"] / stat[t]["n"] * 100 if stat[t]["n"] else 0
                for t in tiers]
        tn = sum(stat[t]["n"] for t in tiers)
        th = sum(stat[t]["hit"] for t in tiers)
        nc = sum(stat[t]["nc"] for t in tiers) / max(tn, 1)
        return vals, th / tn * 100, nc

    print()
    print(" %-6s %-5s %-5s %8s %8s %8s %9s %9s %12s"
          % ("模式", "k", "win", "15-35", "35-70", "70-150", "150-400",
             "合计", "候选/帧"))
    print(" " + "-" * 94)
    for mode, mname in (("top", "TopHat"), ("black", "Black")):
        for win in (31, 51):
            for k in (4.0, 3.0, 2.5, 2.0):
                vals, tot, nc = run(mode, k, win)
                print(" %-6s %-5.1f %-5d %7.0f%% %7.0f%% %7.0f%% %8.0f%% %8.1f%% %12.1f"
                      % (mname, k, win, vals[0], vals[1], vals[2], vals[3], tot, nc))
        print(" " + "-" * 94)
    print()
    print("  推荐：Black-Hat + k=3.0 + win=31 → 召回 86%、候选 47.5（< 64 格，1 次 forward）")
    print("  权衡：降 k 提召回，代价是候选数增加；本架构后接 NPU 判真假，可承受")


if __name__ == "__main__":
    main()