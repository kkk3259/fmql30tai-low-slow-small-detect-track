# -*- coding: utf-8 -*-
"""粗筛「按 peak 截 top-N」的召回曲线（PC 端，不需要板子）

问题：NPU 网格判别一次只能判 N 个候选（grid16 判 16、grid64 判 64）。
      「截到前 N 个」会丢多少召回？这决定网格规模怎么选。

实测结论（2026-10-28，100 张真实图，容差 2 倍 GT 框，双路粗筛）：

  截断   15-35px  35-70px  70-150px  150-400px  合计    平均候选数
  4       12%      20%       60%       88%       45.0%    4.0
  8       32%      24%       72%      100%       57.0%    8.0
  16      36%      40%       80%      100%       64.0%   16.0
  24      44%      40%       84%      100%       67.0%   23.7
  32      64%      48%       88%      100%       75.0%   31.1
  64      80%      68%       92%      100%       85.0%   60.1
  不截断  92%      88%       96%      100%       94.0%   82.0

⇒ 三个关键判断：

  ① 「截 top-16 + grid16 一次判」召回只有 64%（小目标档 36%），
     乘上判别准确率 93% 后约 60%，比现状全图 YOLO 的 48.5% 只好一点，不值得。

  ② 「截 top-64 + grid64 一次判」召回 85%（15-35px 档 80%），
     乘 93% ≈ 79%，是当前几何约束下的最佳点。
     几何依据：512×512 画布正好放 8×8 个 64×64 格；
     而 64×64 格对 15-35px 完整率 100%、35-70px 96%（见 bench_roi_size.py）。

  ③ 「不截断（82 个候选）」召回 94%，但 NPU 需要 6 次 forward 才判完，
     端到端会掉到 10 fps 以下，不划算。

⇒ 所以候选数 64 是「召回 vs 实时性」的最佳交点。

补充对比（单路 vs 双路，topk=64 时）：
  Black-Hat 单路 topk=64         : 80/80/88/100，合计 87%
  双路各 64 合并后截 64          : 80/68/92/100，合计 85%
  ⇒ 候选数受限时单路反而更好（双路的 Top-Hat 候选占名额，挤掉 Black-Hat 好候选）

用法：
  python tools/bench_topn_recall.py
  python tools/bench_topn_recall.py --tol 1.5
"""
import os
import sys
import csv
import argparse
import numpy as np
import cv2
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(REPO, "deploy", "eval_roi_448")

DOWN, WIN, K, FLOOR, SE = 2, 31, 4.0, 3.0, 5


def imread_cn(path):
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


def load_gt(fn, W, H):
    lp = os.path.join(BASE, "labels", fn.replace(".jpg", ".txt"))
    out = []
    for line in open(lp, encoding="utf-8"):
        p = line.split()
        if len(p) < 5:
            continue
        cx, cy, bw, bh = [float(x) for x in p[1:5]]
        out.append((cx * W, cy * H, bw * W, bh * H))
    return out


def cfar(img):
    f = img.astype(np.float32)
    mu = cv2.boxFilter(f, -1, (WIN, WIN), normalize=True,
                       borderType=cv2.BORDER_REFLECT)
    mu2 = cv2.boxFilter(f * f, -1, (WIN, WIN), normalize=True,
                        borderType=cv2.BORDER_REFLECT)
    sd = np.sqrt(np.maximum(mu2 - mu * mu, 0))
    return ((f > mu + K * sd + FLOOR)).astype(np.uint8) * 255


def cands_of(binary, enh, topk):
    n, lab, stats, cents = cv2.connectedComponentsWithStats(binary, connectivity=8)
    out = []
    for i in range(1, n):
        a = stats[i, cv2.CC_STAT_AREA]
        if a < 2 or a > 200:
            continue
        m = (lab == i)
        peak = float(enh[m].max()) if m.any() else 0.0
        out.append((float(cents[i][0]), float(cents[i][1]), int(a), peak))
    out.sort(key=lambda c: -c[3])
    return out[:topk]


def detect(gray_ds, per_side_topk, total_cap):
    """双路粗筛，合并去重后按 peak 截前 total_cap 个（0=不截断）"""
    k5 = cv2.getStructuringElement(cv2.MORPH_RECT, (SE, SE))
    top = cv2.morphologyEx(gray_ds, cv2.MORPH_TOPHAT, k5)
    blk = cv2.morphologyEx(gray_ds, cv2.MORPH_BLACKHAT, k5)
    cs = cands_of(cfar(top), top, per_side_topk) + cands_of(cfar(blk), blk, per_side_topk)
    cs.sort(key=lambda c: -c[3])
    kept = []
    for c in cs:
        if all((c[0] - o[0]) ** 2 + (c[1] - o[1]) ** 2 > 64 for o in kept):
            kept.append(c)
    if total_cap:
        kept = kept[:total_cap]
    return [(x * DOWN, y * DOWN, a) for x, y, a, _ in kept]


def evaluate(rows, cap, tol):
    stat = defaultdict(lambda: {"n": 0, "hit": 0, "nc": []})
    for r in rows:
        fn, tier = r["文件"], r["尺寸档"]
        img = imread_cn(os.path.join(BASE, "images", fn))
        if img is None:
            continue
        h, w = img.shape[:2]
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)[::DOWN, ::DOWN]
        pts = detect(g, 64, cap)
        s = stat[tier]
        s["n"] += 1
        s["nc"].append(len(pts))
        hit = any(abs(x - gx) <= gw * tol / 2 and abs(y - gy) <= gh * tol / 2
                  for (gx, gy, gw, gh) in load_gt(fn, w, h) for (x, y, a) in pts)
        if hit:
            s["hit"] += 1
    return stat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tol", type=float, default=2.0, help="GT 框容差倍数")
    a = ap.parse_args()

    with open(os.path.join(BASE, "manifest.csv"), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print("  样本 %d 张，容差 %.1f 倍 GT 框，双路粗筛" % (len(rows), a.tol))

    tiers = ["15-35px", "35-70px", "70-150px", "150-400px"]
    print()
    print("  %-10s %9s %9s %9s %10s %9s %10s"
          % ("截断", *tiers, "合计", "候选数"))
    for cap in (4, 8, 16, 24, 32, 64, 0):
        s = evaluate(rows, cap, a.tol)
        vals = [s[t]["hit"] / s[t]["n"] * 100 if t in s else 0 for t in tiers]
        tn = sum(s[t]["n"] for t in s)
        th = sum(s[t]["hit"] for t in s)
        nc = np.mean([np.mean(s[t]["nc"]) for t in s])
        label = "不截断" if cap == 0 else str(cap)
        print("  %-10s %8.0f%% %8.0f%% %8.0f%% %9.0f%% %8.1f%% %10.1f"
              % (label, vals[0], vals[1], vals[2], vals[3], th / tn * 100, nc))

    print()
    print("  结论：")
    print("    top-16 → 召回 64%（不够，小目标档仅 36%）")
    print("    top-64 → 召回 85%（grid64 的配置，512×512 放 8×8 个 64×64）")
    print("    不截断 → 召回 94%（但需 6 次 forward，端到端掉到 10fps 以下）")
    print("    ⇒ 候选数 64 是「召回 vs 实时性」的最佳交点")


if __name__ == "__main__":
    main()
