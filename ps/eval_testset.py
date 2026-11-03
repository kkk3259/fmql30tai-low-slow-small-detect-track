#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在板上跑测试集，算召回率 / 精确率 / 定位误差（带真值）。

配套 tools/gen_testset.py 生成的 scene_XX.mp4 + scene_XX.json。

用法（板上）：
    python3 eval_testset.py --dir /root/testset
    python3 eval_testset.py --dir /root/testset --inv auto    # 每种场景正反都跑一遍（默认）
    python3 eval_testset.py --dir /root/testset --inv 1       # 只跑取反（找暗目标）

口径：
    TP = 有一个候选落在真值 max(6, size) 像素内
    召回 = TP / 有真值的帧数
    精确 = TP / 候选总数
    误差 = TP 候选与真值中心的距离均值
"""
import argparse
import glob
import json
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, "/root/ip2")
import cam_pipe as cp

class HW3D(object):
    """三域位流适配器：cam_pipe.HW 用 0x43C00000，本板位流是三域的 0x400C0000。
    直接用 cp.HW() 会读未映射地址，PL 不回 rvalid，PS 挂死。"""

    def __init__(self):
        sys.path.insert(0, "/root/ip2")
        from cam3d_test import PL3D
        self.pl = PL3D()
        self.n = 0

    def run(self, gray):
        cands, st, dt = self.pl.run(gray)   # PL3D 返回 (cands, st, dt)
        return st, cands, dt                # eval 期望 (st, cands, dt)

    def version(self):
        return 0x00010000


W, H = 640, 360


def match(cands, g, tol):
    """候选里离真值最近的那个；超出 tol 视为没匹配上。"""
    best, bd = None, 1e9
    for c in cands:
        d = ((c["x"] - g["x"]) ** 2 + (c["y"] - g["y"]) ** 2) ** 0.5
        if d < bd:
            best, bd = c, d
    if best is None or bd > tol:
        return None, None
    return best, bd


def run_scene(hw, path, meta, inv, track=0, amin=2, pmax=0, pmin=0):
    cap = cv2.VideoCapture(path)
    gt = meta["gt"]
    gt_by_f = {}
    for g in gt:
        gt_by_f.setdefault(g["f"], []).append(g)

    n_tp = n_fp = n_cand = n_gt = 0
    errs = []
    f = 0
    trk = cp.Tracker() if track else None
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        gray = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, (W, H))
        if inv:
            gray = 255 - gray
        st, cands, dt = hw.run(gray)
        cands = [c for c in (cands or []) if c["area"] >= amin and c["peak"] >= pmin]
        if trk is not None:
            cands = cp.nms_tracks(trk.update(cands, 20.0), 0.3)
        gs = gt_by_f.get(f, [])
        used = set()
        for g in gs:
            n_gt += 1
            if not cands:
                continue
            tol = max(6.0, g["size"] * 1.2)
            c, d = match(cands, g, tol)
            if c is not None:
                n_tp += 1
                errs.append(d)
                used.add(id(c))
        n_cand += len(cands)
        n_fp += len([c for c in cands if id(c) not in used])
        f += 1
    cap.release()
    recall = 100.0 * n_tp / n_gt if n_gt else 0.0
    prec = 100.0 * n_tp / n_cand if n_cand else 0.0
    f1 = 2 * recall * prec / (recall + prec) if (recall + prec) else 0.0
    return dict(frames=f, n_gt=n_gt, n_cand=n_cand, tp=n_tp, fp=n_fp,
                recall=recall, prec=prec, f1=f1,
                err=float(np.mean(errs)) if errs else -1.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="/root/testset")
    ap.add_argument("--inv", default="auto")
    ap.add_argument("--track", type=int, default=0)
    ap.add_argument("--pmin", type=int, default=0, help="峰值门槛，低于它的候选直接丢")
    ap.add_argument("--out", default="/root/testset_result.csv")
    a = ap.parse_args()

    hw = HW3D()
    print("device ok, VERSION = 0x%08x" % (hw.version() if hasattr(hw, "version") else 0))

    modes = [0, 1] if a.inv == "auto" else [int(a.inv)]
    rows = []
    for jf in sorted(glob.glob(os.path.join(a.dir, "scene_*.json"))):
        meta = json.load(open(jf, encoding="utf-8"))
        mp4 = jf.replace(".json", ".mp4")
        if not os.path.exists(mp4):
            continue
        for inv in modes:
            t0 = time.time()
            r = run_scene(hw, mp4, meta, inv, a.track, pmin=a.pmin)
            r.update(name=meta["name"], bg=meta["bg"], dark=int(meta["dark"]),
                     size=int(meta["size"]), contrast=int(meta["contrast"]), inv=inv)
            rows.append(r)
            print("%-20s bg=%-6s %s %2dpx c=%3d inv=%d | 召回 %5.1f%%  精确 %5.1f%%  F1 %5.1f  误差 %.1fpx  候选/帧 %.1f  (%.0fs)"
                  % (r["name"], r["bg"], "暗" if meta["dark"] else "亮", meta["size"],
                     meta["contrast"], inv, r["recall"], r["prec"], r["f1"], r["err"],
                     r["n_cand"] / max(1, r["frames"]), time.time() - t0))

    # 汇总：按模式与尺寸
    print("\n=== 汇总 ===")
    for inv in modes:
        sub = [r for r in rows if r["inv"] == inv]
        if not sub:
            continue
        rec = np.mean([r["recall"] for r in sub])
        pre = np.mean([r["prec"] for r in sub])
        f1 = np.mean([r["f1"] for r in sub])
        print("inv=%d : 平均召回 %.1f%%  平均精确 %.1f%%  平均F1 %.1f  (%d 段)" %
              (inv, rec, pre, f1, len(sub)))

    with open(a.out, "w", encoding="utf-8") as fh:
        keys = ["name", "bg", "dark", "size", "contrast", "inv", "frames", "n_gt",
                "n_cand", "tp", "fp", "recall", "prec", "f1", "err"]
        fh.write(",".join(keys) + "\n")
        for r in rows:
            fh.write(",".join(str(r.get(k, "")) for k in keys) + "\n")
    print("结果写入 %s" % a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
