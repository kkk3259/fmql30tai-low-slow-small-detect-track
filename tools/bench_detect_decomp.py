# -*- coding: utf-8 -*-
"""拆解 PS 侧双路检测的耗时构成（PC 端，不需要板子）

回答：stream_cascade.py 的 sim 后端 17 ms 花在哪？
结论（2026-10-27，640×360 灰度，PC，50 次均值）：

  ① 双路形态学 Top+Black   0.11 ms    0.7%
  ② CFAR × 2                5.22 ms   30.8%
  ③ CCL × 2 + 排序          8.39 ms   49.5%   ← 最大单项
  ④ 合并去重                0.93 ms    5.5%
  ⑤ 裁 64 个 64×64 + 拼网格 2.30 ms   13.6%
  合计                      16.96 ms

关键结论：
  · CFAR + CCL 占 80%（13.6 ms），是真正的大头，也是 PL 该加速的部分。
    PL 做这两件事全链只要 5.0 ms（P 实测），加速约 2.7×。
  · 裁图拼网格只有 2.3 ms（13.6%），之前"把裁剪移到 PL"的收益很小。
    真正该移到 PL 的是检测（CFAR+CCL），不是裁剪。
  · CCL（connectedComponentsWithStats 8 连通）是最大单项 8.39 ms，
    对应 PL 的 candidate_extract_stream.v。

用法：
  python tools/bench_detect_decomp.py
"""
import os
import sys
import time

import numpy as np
import cv2

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "ps"))
from stream_cascade import DualDetector, build_canvas, W, H, MAX_CAND, ROI  # noqa: E402

BASE = os.path.join(REPO, "deploy", "eval_roi_448")


def imread_cn(p):
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)


def bench(fn, n=50, warm=5):
    for _ in range(warm):
        fn()
    t = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        t.append((time.perf_counter() - t0) * 1e3)
    return float(np.mean(t)), float(np.min(t))


def main():
    # 取一张真实图当帧，缩到 640×360 灰度
    with open(os.path.join(BASE, "manifest.csv"), encoding="utf-8") as f:
        import csv
        rows = list(csv.DictReader(f))
    src = None
    for r in rows:
        if r["尺寸档"] == "15-35px":
            src = imread_cn(os.path.join(BASE, "images", r["文件"]))
            if src is not None:
                break
    gray = cv2.cvtColor(src, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, (W, H), interpolation=cv2.INTER_AREA)
    print("  帧 %dx%d 灰度" % (gray.shape[1], gray.shape[0]))

    det = DualDetector(topk=64)
    kern = det.kernel

    print()
    print("  ════ 分环节拆解（50 次均值 / 最小值，ms）════")
    print("  %-28s %10s %10s" % ("环节", "均值", "最小"))

    def f_morph():
        top = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, kern)
        blk = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, kern)
        return top, blk
    m, lo = bench(f_morph)
    print("  %-28s %10.2f %10.2f" % ("① 双路形态学 Top+Black", m, lo))

    top, blk = f_morph()

    def f_cfar():
        a = det._cfar(top)
        b = det._cfar(blk)
        return a, b
    m2, lo2 = bench(f_cfar)
    print("  %-28s %10.2f %10.2f" % ("② CFAR × 2", m2, lo2))

    ba, bb = f_cfar()

    def f_ccl():
        a = det._cands(ba, top)
        b = det._cands(bb, blk)
        return a, b
    m3, lo3 = bench(f_ccl)
    print("  %-28s %10.2f %10.2f" % ("③ CCL × 2 + 排序", m3, lo3))

    ca, cb = f_ccl()

    def f_merge():
        cs = ca + cb
        cs.sort(key=lambda c: -c["peak"])
        kept = []
        for c in cs:
            if all((c["x"] - o["x"]) ** 2 + (c["y"] - o["y"]) ** 2 > 64 for o in kept):
                kept.append(c)
        return kept[:MAX_CAND]
    m4, lo4 = bench(f_merge)
    print("  %-28s %10.2f %10.2f" % ("④ 合并去重", m4, lo4))

    merged = f_merge()
    print("      → 合并后 %d 个候选" % len(merged))

    def f_canvas():
        return build_canvas(gray, merged)
    m5, lo5 = bench(f_canvas, n=30)
    print("  %-28s %10.2f %10.2f"
          % ("⑤ 裁 %d 个 %d×%d + 拼网格" % (len(merged), ROI, ROI), m5, lo5))

    def f_all():
        cs = det(gray)
        return build_canvas(gray, cs)
    m6, lo6 = bench(f_all, n=30)
    print("  %-28s %10.2f %10.2f" % ("⑥ 整体（det + canvas）", m6, lo6))

    print()
    print("  ════ 占比 ════")
    total = m + m2 + m3 + m4 + m5
    for name, v in [("双路形态学", m), ("CFAR×2", m2), ("CCL×2", m3),
                    ("合并去重", m4), ("裁图拼网格", m5)]:
        print("  %-16s %7.2f ms  %5.1f%%   %s"
              % (name, v, v / total * 100, "#" * int(v / total * 40)))
    print("  %-16s %7.2f ms" % ("分项合计", total))
    print("  %-16s %7.2f ms" % ("实测整体", m6))
    print()
    print("  结论：CFAR+CCL 占 80%，是 PL 该加速的部分（PL 全链 5.0 ms）。")
    print("        裁图只占 2.3 ms，不值得为它改 PL。")


if __name__ == "__main__":
    main()
