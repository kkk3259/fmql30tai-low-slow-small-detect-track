# -*- coding: utf-8 -*-
"""
合成序列参数扫描：量化"检出率 Pd 随 目标尺寸 / 对比度 的变化"

这是给算法做"体检"——就像通信里测 BER-SNR 曲线，我们测 Pd ~ 目标尺寸/对比度。

原理：合成序列的目标是我们自己画上去的，所以尺寸、对比度、背景杂波都能精确设定，
      真值天然准确（不用人工标注）→ 可以系统地扫参数，得到算法的能力边界。

用法：
  python tools\\sweep_synth.py                          # 默认 3x3 = 9 组
  python tools\\sweep_synth.py --radii 0.8,1.2,2.0,4.0 --amps 3,8,20,50
  python tools\\sweep_synth.py --frames 200 --k 3.5     # 换检测参数再扫一遍

输出：results\\sweep_synth.csv（每行一组：半径/对比度/Pd/虚警/候选数）
"""
import argparse
import csv
import os
import shutil
import sys
import tempfile
import time

import numpy as np
import cv2

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJ = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_PROJ, "baseline"))

from run import make_synthetic, to_gray_down, gauss, tophat          # noqa: E402
from detect_v1 import adaptive_threshold, extract_candidates          # noqa: E402


def evaluate(video, gt_file, cfg, gate):
    """对一段合成序列跑完整检测链，返回 (Pd%, 虚警数, 平均候选数, 帧数)"""
    gt = {}
    with open(gt_file) as f:
        for r in csv.DictReader(f):
            gt[int(r["frame"])] = (float(r["x"]), float(r["y"]))  # 兼容带小数的真值（mark_gt.py 输出）

    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        raise SystemExit("打不开生成视频：" + video)

    hits = miss = fp = n_gt = cand_sum = 0
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        gray = to_gray_down(frame, cfg["down"])
        g = gauss(gray, cfg["gauss"])
        th = tophat(g, cfg["tophat"])
        binary, _ = adaptive_threshold(th, cfg["win"], cfg["k"], cfg["floor"])
        cands = extract_candidates(binary, th, cfg["min_area"], cfg["max_area"], cfg["topk"])
        cand_sum += len(cands)

        if idx in gt:
            n_gt += 1
            gx, gy = gt[idx][0] / cfg["down"], gt[idx][1] / cfg["down"]
            hit = any((c["x"] - gx) ** 2 + (c["y"] - gy) ** 2 <= gate * gate for c in cands)
            if hit:
                hits += 1
            else:
                miss += 1
            fp += max(0, len(cands) - (1 if hit else 0))
        idx += 1
    cap.release()

    pd = 100.0 * hits / n_gt if n_gt else 0.0
    return pd, fp, (cand_sum / idx if idx else 0.0), idx


def main():
    ap = argparse.ArgumentParser(description="合成序列参数扫描（Pd vs 目标尺寸/对比度）")
    ap.add_argument("--frames", type=int, default=120, help="每段序列帧数")
    ap.add_argument("--radii", default="1.0,1.5,3.0", help="目标半径（像素），逗号分隔")
    ap.add_argument("--amps", default="5,15,30", help="目标对比度（灰阶），逗号分隔")
    ap.add_argument("--clouds", type=int, default=14, help="背景云团数量（杂波强度）")
    # 检测参数（默认沿用 v1 的调优值，保证与既有结果可比）
    ap.add_argument("--k", type=float, default=4.0)
    ap.add_argument("--floor", type=float, default=3.0)
    ap.add_argument("--min-area", type=int, default=2)
    ap.add_argument("--tophat", type=int, default=5)
    ap.add_argument("--down", type=int, default=2)
    ap.add_argument("--gate", type=float, default=3.0, help="命中判定半径（降采样图像素）")
    ap.add_argument("--out", default="results\\sweep_synth.csv")
    a = ap.parse_args()

    cfg = dict(down=a.down, gauss=0, tophat=a.tophat, win=31,
               k=a.k, floor=a.floor, min_area=a.min_area, max_area=200, topk=8)
    radii = [float(x) for x in a.radii.split(",")]
    amps = [float(x) for x in a.amps.split(",")]

    tmp = tempfile.mkdtemp(prefix="sweep_")
    rows = []
    print("")
    print("=== 合成序列参数扫描 ===")
    print("组数        : {}  (半径 {} × 对比度 {})".format(len(radii) * len(amps), a.radii, a.amps))
    print("每段帧数    : {}".format(a.frames))
    print("检测参数    : k={} floor={} min_area={} tophat={} down={}".format(
        a.k, a.floor, a.min_area, a.tophat, a.down))
    print("背景杂波    : {} 个云团".format(a.clouds))
    print("")
    print("  {:>8} {:>8} | {:>8} {:>10} {:>12}".format("半径px", "对比度", "Pd(%)", "虚警数", "候选/帧"))
    print("  " + "-" * 54)

    for r in radii:
        for amp in amps:
            v = os.path.join(tmp, "s_r{}_a{}.mp4".format(r, amp))
            t0 = time.time()
            make_synthetic(v, n_frames=a.frames, clouds=a.clouds,
                           target_radius=r, target_amp=amp)
            pd, fp, cavg, n = evaluate(v, os.path.splitext(v)[0] + "_gt.csv", cfg, a.gate)
            rows.append([r, amp, round(pd, 1), fp, round(cavg, 2), n, round(time.time() - t0, 1)])
            print("  {:>8.1f} {:>8.0f} | {:>8.1f} {:>10d} {:>12.2f}".format(r, amp, pd, fp, cavg))

    shutil.rmtree(tmp, ignore_errors=True)

    out = os.path.join(_PROJ, a.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["target_radius_px", "target_amp_gray", "Pd_percent", "false_alarms",
                    "avg_cand_per_frame", "frames", "seconds"])
        w.writerows(rows)
    print("")
    print("结果已写入  : {}".format(out))
    print("下一步画图  : python tools\\plot_sweep.py")


if __name__ == "__main__":
    main()
