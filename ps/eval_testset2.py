#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在板上跑测试集 v2（真剪影 + 多目标），算召回 / 精确 / 定位误差 / 尺寸分档。

配套 tools/gen_testset2.py 生成的 <name>.mp4 + <name>.json。

真值格式（v2）：
    {"name":..., "bg":..., "kind":..., "gt":[{"frame":0,"targets":[{cx,cy,size,ct,pol}]}, ...]}

用法（板上）：
    python3 eval_testset2.py                       # 正反两种极性都跑
    python3 eval_testset2.py --inv 1               # 只跑取反（找暗目标）
    python3 eval_testset2.py --pmin 40 --amin 4    # 加过滤
    python3 eval_testset2.py --dir /root/testset2 --out /root/ts2.csv

口径：
    匹配 = 候选中心落在真值 max(6, 1.2×size) 像素内，且一对一（贪心最近优先）
    召回 = TP / 真值总数
    精确 = TP / 候选总数
"""
import argparse
import glob
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, "/root/ip2")
import cam_pipe as cp

W, H = 640, 360
BINS = [(2, 5), (6, 9), (10, 15), (16, 24), (25, 40)]


def greedy_match(cands, gts):
    """一对一贪心匹配：返回 [(gt, cand, dist)] 和未匹配候选下标集合。"""
    pairs = []
    for gi, g in enumerate(gts):
        tol = max(6.0, g["size"] * 1.2)
        for ci, c in enumerate(cands):
            d = ((c["x"] - g["cx"]) ** 2 + (c["y"] - g["cy"]) ** 2) ** 0.5
            if d <= tol:
                pairs.append((d, gi, ci))
    pairs.sort()
    used_g, used_c, out = set(), set(), []
    for d, gi, ci in pairs:
        if gi in used_g or ci in used_c:
            continue
        used_g.add(gi)
        used_c.add(ci)
        out.append((gts[gi], cands[ci], d))
    return out, used_c


def run_scene(hw, path, meta, inv, pmin, amin, track=False):
    cap = cv2.VideoCapture(path)
    gt_by_f = {g["frame"]: g["targets"] for g in meta["gt"]}
    n_tp = n_fp = n_cand = n_gt = 0
    errs = []
    per_bin = {b: [0, 0] for b in BINS}   # bin -> [tp, gt]
    f = 0
    trk = cp.Tracker() if track else None
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        gray = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
        if gray.shape[:2] != (H, W):
            gray = cv2.resize(gray, (W, H))
        if inv:
            gray = (255 - gray).astype(np.uint8)
        st, cands, dt = hw.run(gray)
        cands = [c for c in (cands or [])
                 if c["area"] >= amin and c["peak"] >= pmin]
        if track:
            cands = cp.nms_tracks(trk.update(cands, 20.0), 0.3)

        gs = gt_by_f.get(f, [])
        matched, used_c = greedy_match(cands, gs)
        for g in gs:
            n_gt += 1
            for b in BINS:
                if b[0] <= g["size"] <= b[1]:
                    per_bin[b][1] += 1
                    break
        for g, c, d in matched:
            n_tp += 1
            errs.append(d)
            for b in BINS:
                if b[0] <= g["size"] <= b[1]:
                    per_bin[b][0] += 1
                    break
        n_cand += len(cands)
        n_fp += len(cands) - len(used_c)
        f += 1
    cap.release()

    recall = 100.0 * n_tp / n_gt if n_gt else 0.0
    prec = 100.0 * n_tp / n_cand if n_cand else 0.0
    return dict(frames=f, n_gt=n_gt, n_cand=n_cand, tp=n_tp, fp=n_fp,
                recall=recall, prec=prec,
                cand_per_frame=(n_cand / f if f else 0.0),
                err=float(np.mean(errs)) if errs else -1.0,
                per_bin={("%d-%d" % b): (100.0 * v[0] / v[1] if v[1] else -1.0)
                         for b, v in per_bin.items()})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="/root/testset2")
    ap.add_argument("--inv", default="auto")
    ap.add_argument("--pmin", type=int, default=0)
    ap.add_argument("--amin", type=int, default=2)
    ap.add_argument("--track", type=int, default=0)
    ap.add_argument("--out", default="/root/ts2_result.csv")
    a = ap.parse_args()

    hw = cp.HW()
    modes = [0, 1] if a.inv == "auto" else [int(a.inv)]

    rows = []
    for jf in sorted(glob.glob(os.path.join(a.dir, "*.json"))):
        if os.path.basename(jf) == "index.json":
            continue
        meta = json.load(open(jf, encoding="utf-8"))
        mp4 = jf[:-5] + ".mp4"
        if not os.path.exists(mp4):
            continue
        for inv in modes:
            r = run_scene(hw, mp4, meta, inv, a.pmin, a.amin, bool(a.track))
            rows.append(dict(name=meta["name"], bg=meta["bg"], kind=meta["kind"],
                             inv=inv, **r))
            print("%-18s inv=%d  召回 %5.1f%%  精确 %5.1f%%  候选 %4.1f/帧  误差 %4.1fpx"
                  % (meta["name"], inv, r["recall"], r["prec"],
                     r["cand_per_frame"], r["err"]))
            for k, v in r["per_bin"].items():
                if v >= 0:
                    print("      %-6s %5.1f%%" % (k, v))

    if rows:
        import csv
        with open(a.out, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()), extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        print("\n=== 平均 ===")
        for inv in modes:
            sel = [r for r in rows if r["inv"] == inv]
            if sel:
                print("inv=%d  平均召回 %.1f%%  平均精确 %.1f%%  平均候选 %.1f/帧"
                      % (inv,
                         np.mean([r["recall"] for r in sel]),
                         np.mean([r["prec"] for r in sel]),
                         np.mean([r["cand_per_frame"] for r in sel])))
        print("明细:", a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
