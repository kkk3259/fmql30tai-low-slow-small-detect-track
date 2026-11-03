#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_testset3d.py —— 在三域位流（平台寄存器口 + PL DDR）上跑合成测试集评估。

与 eval_testset2.py 的区别：那条走的是我们自己的 ip2_bd_wrapper（PS DDR + 0x43C00000），
这条走平台自定义算子的 User_Reg（0x400C0000）+ User_Ddr（PL DDR），对应 ours3d_*.bin。

用法（板端）：
    python3 eval_testset3d.py /root/ts2 "*.mp4" --inv both --border 24 --pre gamma --gamma 0.08
"""
import argparse
import glob
import json
import os
import sys

import cv2
import numpy as np

W, H = 640, 360
BINS = [(2, 5), (6, 10), (11, 17), (18, 30), (31, 99)]


def greedy_match(cands, gts, max_dist):
    """一对一贪心匹配：按距离从小到大配。"""
    pairs = []
    for ci, c in enumerate(cands):
        for gi, g in enumerate(gts):
            d = ((c["x"] - g["x"]) ** 2 + (c["y"] - g["y"]) ** 2) ** 0.5
            if d <= max_dist:
                pairs.append((d, ci, gi))
    pairs.sort()
    uc, ug, out = set(), set(), []
    for d, ci, gi in pairs:
        if ci in uc or gi in ug:
            continue
        uc.add(ci)
        ug.add(gi)
        out.append((cands[ci], gts[gi], d))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("pat", nargs="?", default="*.mp4")
    ap.add_argument("--inv", default="both", choices=["0", "1", "both"])
    ap.add_argument("--border", type=int, default=0, help="屏蔽上下各 N 行（压 HUD/边框虚警）")
    ap.add_argument("--pre", default="none", choices=["none", "gamma", "clahe"])
    ap.add_argument("--gamma", type=float, default=0.08)
    ap.add_argument("--pmin", type=int, default=0)
    ap.add_argument("--amin", type=int, default=2)
    ap.add_argument("--maxdist", type=float, default=12.0)
    ap.add_argument("--limit", type=int, default=0, help="每段最多测多少帧（0=全部）")
    a = ap.parse_args()

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import detect3d

    det = detect3d.Det3D()
    print("VERSION = 0x%08X" % det.ver)

    modes = [0, 255] if a.inv == "both" else ([0] if a.inv == "0" else [255])
    rows = []

    for mp4 in sorted(glob.glob(os.path.join(a.root, a.pat))):
        meta_p = mp4.rsplit(".", 1)[0] + ".json"
        if not os.path.exists(meta_p):
            print("跳过（无真值）:", os.path.basename(mp4))
            continue
        meta = json.load(open(meta_p))
        gt_by_f = {g["frame"]: g["targets"] for g in meta["gt"]}

        cap = cv2.VideoCapture(mp4)
        n_tp = n_fp = n_cand = n_gt = 0
        errs = []
        per_bin = {b: [0, 0] for b in BINS}
        fi = 0
        while True:
            ok, fr = cap.read()
            if not ok:
                break
            gray = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
            if gray.shape[:2] != (H, W):
                gray = cv2.resize(gray, (W, H))
            base = gray
            if a.pre == "gamma":
                lut = np.array([min(255, int(round(255.0 * ((i / 255.0) ** a.gamma)))) for i in range(256)],
                               np.uint8)
                base = cv2.LUT(base, lut)
            elif a.pre == "clahe":
                base = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(base)

            cands = []
            for m in modes:
                img = base if m == 0 else (255 - base)
                _st, c, _dt = det.detect(img)      # detect 返回 (status, cands, ms)
                cands += c
            # 合并双极性的重框（多尺度/双极性会重复报同一目标）
            merged = []
            for c in sorted(cands, key=lambda d: -d["peak"]):
                if all(abs(c["x"] - m["x"]) > 8 or abs(c["y"] - m["y"]) > 8 for m in merged):
                    merged.append(c)
            cands = [c for c in merged if c["area"] >= a.amin and c["peak"] >= a.pmin]
            if a.border:
                cands = [c for c in cands if a.border <= c["y"] <= H - a.border]

            gts = gt_by_f.get(fi, [])
            if a.limit and fi >= a.limit:
                break
            fi += 1
            n_cand += len(cands)
            n_gt += len(gts)
            mt = greedy_match(cands, gts, a.maxdist)
            n_tp += len(mt)
            n_fp += len(cands) - len(mt)
            for c, g, d in mt:
                errs.append(d)
                for b in BINS:
                    if b[0] <= g.get("size", 0) <= b[1]:
                        per_bin[b][0] += 1
                        break
            for g in gts:
                for b in BINS:
                    if b[0] <= g.get("size", 0) <= b[1]:
                        per_bin[b][1] += 1
                        break
        cap.release()

        rec = n_tp / max(1, n_gt)
        pre = n_tp / max(1, n_tp + n_fp)
        name = os.path.basename(mp4).replace(".mp4", "")
        rows.append((name, rec, pre, n_cand / max(1, fi), np.mean(errs) if errs else 0.0, per_bin))
        print("%-18s 召回 %5.1f%%  精确 %5.1f%%  候选/f %5.1f  定位 %4.1fpx"
              % (name, 100 * rec, 100 * pre, n_cand / max(1, fi), np.mean(errs) if errs else 0.0))
        sys.stdout.flush()

    if rows:
        print("\n=== 汇总 ===")
        print("平均召回 %.1f%%   平均精确 %.1f%%" %
              (100 * np.mean([r[1] for r in rows]), 100 * np.mean([r[2] for r in rows])))


if __name__ == "__main__":
    main()
