# -*- coding: utf-8 -*-
"""ROI 尺寸 vs 目标可判别性实验（PC 端，不需要板子）

问题：PL 按候选质心裁 ROI 送 NPU，ROI 裁多大？
      太小 → 大目标被切断；太大 → 小目标占比低，NPU 看不见。

指标：
  完整率   = ROI 能否完整包住目标（100% 才行，否则目标被切断）
  目标占比 = 目标边长 / ROI 边长（太低说明目标太小）
  信噪比   = (目标均值 - 背景均值) / 背景标准差

实测结论（2026-10-27，100 张真实图）：

  尺寸档      ROI   完整率   目标占比
  15-35px      32    28.0%     94.5%     ← 32 不够
  15-35px      48   100.0%     63.0%
  15-35px      64   100.0%     47.3%     ← 64 可用
  15-35px     128   100.0%     23.6%

  35-70px      48    44.0%     92.6%     ← 48 不够
  35-70px      64    96.0%     69.4%     ← 64 基本够
  35-70px     128   100.0%     34.7%

  70-150px     64     3.3%    161.5%     ← 64 完全不够
  70-150px    128    66.7%     80.8%     ← 128 也不够
  150-400px   128     3.8%    196.4%     ← 需要 >256

⇒ 结论：单一大小的 ROI 覆盖不了全尺度。
        64×64 能覆盖 15-70px（前两档，占样本 50%），
        更大的目标必须靠 Top-Hat 通道或全图检测补。

⇒ 架构含义：8×8=64 个候选、每个 64×64、拼 512×512 灰度网格，
            正好填满一次 NPU forward，覆盖 15-70px 目标。

用法：
  python tools/bench_roi_size.py
"""
import os, csv, numpy as np, cv2
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(REPO, "deploy", "eval_roi_448")
ROI_LIST = [32, 48, 64, 128]
TOL = 2


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


def main():
    with open(os.path.join(BASE, "manifest.csv"), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    stat = defaultdict(lambda: defaultdict(list))

    for r in rows:
        fn, tier = r["文件"], r["尺寸档"]
        img = imread_cn(os.path.join(BASE, "images", fn))
        if img is None:
            continue
        H, W = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        for (gx, gy, gw, gh) in load_gt(fn, W, H):
            half_max = max(gw, gh) / 2.0
            for roi in ROI_LIST:
                half = roi / 2.0
                complete = (half >= half_max + TOL)
                ratio = max(gw, gh) / roi
                stat[tier][roi].append((complete, ratio))

    print("  ════ ROI 尺寸 vs 目标完整性 ════")
    print("  %-12s %6s %10s %14s %8s" % ("尺寸档", "ROI", "完整率", "目标占比", "样本数"))
    for tier in ["15-35px", "35-70px", "70-150px", "150-400px"]:
        if tier not in stat:
            continue
        for roi in ROI_LIST:
            d = stat[tier][roi]
            if not d:
                continue
            comp = sum(1 for c, _ in d if c) / len(d) * 100
            ratio = np.mean([r for _, r in d]) * 100
            print("  %-12s %6d %9.1f%% %13.1f%% %8d" % (tier, roi, comp, ratio, len(d)))
        print()

    print("  结论：")
    print("    64×64 覆盖 15-70px（前两档），完整率 100% / 96%")
    print("    70-150px 需要 128×128 以上，且完整率只 66.7%")
    print("    150-400px 需要 >256，单一大小的 ROI 覆盖不了全尺度")


if __name__ == "__main__":
    main()