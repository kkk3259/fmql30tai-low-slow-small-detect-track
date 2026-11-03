#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对比两次 RTL 仿真（不同 K/FLOOR）在真实测试帧上的候选输出，并与真值对齐。

候选字节流（与 candidate_extract_stream 一致）：
    byte0           = n_comp
    每个候选 7 字节 = x_hi x_lo y_hi y_lo area_hi area_lo peak

用法：
    python tools/analyze_kcmp.py D:\\firstharness\\dl\\kframes
"""
import json
import os
import sys

FRAME_IDX = 60      # 抽的是第 60 帧


def load_bytes(path):
    with open(path) as f:
        return [int(x, 16) for x in f if x.strip()]


def decode(bs):
    if not bs:
        return 0, []
    n = bs[0]
    cands = []
    for i in range(n):
        o = 1 + i * 7
        if o + 6 >= len(bs):
            break
        x = (bs[o] << 8) | bs[o + 1]
        y = (bs[o + 2] << 8) | bs[o + 3]
        area = (bs[o + 4] << 8) | bs[o + 5]
        peak = bs[o + 6]
        cands.append(dict(x=x, y=y, area=area, peak=peak))
    return n, cands


def match(cands, gts, tol=12):
    """一对一贪心匹配：候选中心距真值 <= tol 视为命中。"""
    used = set()
    hit = 0
    for g in gts:
        best, bd = -1, 1e9
        for i, c in enumerate(cands):
            if i in used:
                continue
            d = ((c["x"] - g["cx"]) ** 2 + (c["y"] - g["cy"]) ** 2) ** 0.5
            if d < bd:
                bd, best = d, i
        if best >= 0 and bd <= tol:
            used.add(best)
            hit += 1
    return hit, len(cands) - hit


def main():
    d = sys.argv[1] if len(sys.argv) > 1 else r"./data/kframes"
    scenes = ["sky_tiny", "clouds_bird", "sky_bird_multi"]
    print("%-16s %-6s %6s %6s %6s %6s %s" % ("场景", "配置", "字节", "候选", "命中", "虚警", "召回"))
    print("-" * 68)
    rows = []
    for sc in scenes:
        gt_path = os.path.join(r"./data/testset2", sc + ".json")
        gts = []
        if os.path.exists(gt_path):
            j = json.load(open(gt_path, encoding="utf-8"))
            for fr in j["gt"]:
                if fr["frame"] == FRAME_IDX:
                    gts = fr["targets"]
                    break
        for cfg in ("k1", "k0"):
            p = os.path.join(d, "%s_%s.txt" % (cfg, sc))
            if not os.path.exists(p):
                print("%-16s %-6s  (缺文件)" % (sc, cfg))
                continue
            bs = load_bytes(p)
            n, cands = decode(bs)
            hit, fp = match(cands, gts)
            rec = 100.0 * hit / len(gts) if gts else 0.0
            print("%-16s %-6s %6d %6d %6d %6d %5.1f%%  (真值 %d)"
                  % (sc, cfg, len(bs), len(cands), hit, fp, rec, len(gts)))
            rows.append((sc, cfg, len(cands), hit, fp, rec))
    print()
    for cfg, label in (("k1", "K=1/FLOOR=3"), ("k0", "K=0/FLOOR=2")):
        r = [x for x in rows if x[1] == cfg]
        if r:
            print("%s: 候选合计 %d, 命中 %d, 虚警 %d, 平均召回 %.1f%%"
                  % (label, sum(x[2] for x in r), sum(x[3] for x in r),
                     sum(x[4] for x in r), sum(x[5] for x in r) / len(r)))


if __name__ == "__main__":
    main()
