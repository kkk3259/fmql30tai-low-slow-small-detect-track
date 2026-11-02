# -*- coding: utf-8 -*-
"""
检测链路信号诊断：在【真目标位置】逐环测量信号值，定位瓶颈到底在哪一环

为什么需要：之前凭推测（候选截断/结构元不匹配）下了两次结论都错了。
本工具改为【直接测量】—— 在真值坐标处测出各环节的实际数值，
从而判定：是灰度太弱？Top-Hat 没增强？还是 CFAR 门限太高？

用法：
  python tools\\diag_signal.py --src D:\\lowslow\\data\\real\\bird.mp4
  python tools\\diag_signal.py --src ... --k 3 --floor 2      # 换参数再看
"""
import argparse
import csv
import os
import sys

import cv2
import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJ = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_PROJ, "baseline"))

from run import to_gray_down, gauss, tophat                    # noqa: E402
from detect_v1 import adaptive_threshold                       # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="检测链路信号诊断（真目标位置逐环测量）")
    ap.add_argument("--src", required=True)
    ap.add_argument("--down", type=int, default=2)
    ap.add_argument("--gauss", type=int, default=0)
    ap.add_argument("--tophat", type=int, default=5)
    ap.add_argument("--win", type=int, default=31)
    ap.add_argument("--k", type=float, default=4.0)
    ap.add_argument("--floor", type=float, default=3.0)
    ap.add_argument("--max-frames", type=int, default=0)
    a = ap.parse_args()

    gtf = os.path.splitext(a.src)[0] + "_gt.csv"
    if not os.path.exists(gtf):
        raise SystemExit("找不到真值：" + gtf)
    gt = {}
    with open(gtf, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            gt[int(r["frame"])] = (float(r["x"]), float(r["y"]))

    cap = cv2.VideoCapture(a.src)
    if not cap.isOpened():
        raise SystemExit("打不开视频：" + a.src)

    # 统计量
    gray_vals, th_vals, thr_vals, bg_vals = [], [], [], []
    pass_cnt = 0
    idx = 0
    # 同时统计"全图"的背景分布作为对照
    frame_sigma = []

    while True:
        ok, fr = cap.read()
        if not ok or (a.max_frames and idx >= a.max_frames):
            break
        gray = to_gray_down(fr, a.down)
        g = gauss(gray, a.gauss)
        th = tophat(g, a.tophat)
        binary, thr = adaptive_threshold(th, a.win, a.k, a.floor)

        if idx in gt:
            gx, gy = int(round(gt[idx][0] / a.down)), int(round(gt[idx][1] / a.down))
            H, W = gray.shape[:2]
            if 2 <= gy < H - 2 and 2 <= gx < W - 2:
                # 目标位置：取 3x3 邻域最大值（避免标注略偏）
                patch = th[gy - 2:gy + 3, gx - 2:gx + 3]
                pk = float(patch.max())
                th_vals.append(pk)
                gray_vals.append(float(gray[gy - 2:gy + 3, gx - 2:gx + 3].max()))
                thr_vals.append(float(thr[gy, gx]))
                # 局部背景（同帧全图中位数作为参考）
                bg_vals.append(float(np.median(th)))
                if binary[gy - 2:gy + 3, gx - 2:gx + 3].max() > 0:
                    pass_cnt += 1
        frame_sigma.append(float(np.std(gray)))
        idx += 1
    cap.release()

    n = len(th_vals)
    if n == 0:
        raise SystemExit("没有可用的真值帧")

    th_arr = np.array(th_vals)
    thr_arr = np.array(thr_vals)
    gr_arr = np.array(gray_vals)
    bg_arr = np.array(bg_vals)

    print("")
    print("=== 检测链路信号诊断（在真目标位置测量）===")
    print("  视频      : {}".format(os.path.basename(a.src)))
    print("  参数      : tophat={} win={} k={} floor={}".format(a.tophat, a.win, a.k, a.floor))
    print("  有效真值帧: {}".format(n))
    print("")
    print("  环节                    |      均值 |   中位数 |     最大 |    最小")
    print("  ------------------------|-----------|----------|----------|---------")
    print("  ① 灰度值(目标处)         | {:>9.1f} | {:>8.1f} | {:>8.1f} | {:>7.1f}".format(
        gr_arr.mean(), np.median(gr_arr), gr_arr.max(), gr_arr.min()))
    print("  ② Top-Hat 增强值(目标处) | {:>9.2f} | {:>8.2f} | {:>8.2f} | {:>7.2f}".format(
        th_arr.mean(), np.median(th_arr), th_arr.max(), th_arr.min()))
    print("  ③ CFAR 门限(目标处)      | {:>9.2f} | {:>8.2f} | {:>8.2f} | {:>7.2f}".format(
        thr_arr.mean(), np.median(thr_arr), thr_arr.max(), thr_arr.min()))
    print("  ④ 全图增强图背景中位数    | {:>9.2f} | {:>8.2f} | {:>8.2f} | {:>7.2f}".format(
        bg_arr.mean(), np.median(bg_arr), bg_arr.max(), bg_arr.min()))
    print("")
    print("  目标处增强值 / 门限  = {:.2f}   （>1 才能过门限）".format(th_arr.mean() / max(thr_arr.mean(), 1e-6)))
    print("  目标处过门限比例     = {:.1f}%  ({} / {})".format(100.0 * pass_cnt / n, pass_cnt, n))
    print("  全图灰度 σ（杂波强度）| 均值 {:.1f}".format(np.mean(frame_sigma)))
    print("")
    print("  ── 判读 ──")
    ratio = th_arr.mean() / max(thr_arr.mean(), 1e-6)
    if ratio < 1.0:
        print("   目标增强值【低于门限】→ 瓶颈在【CFAR 门限偏高】或【Top-Hat 增强不足】")
        print("     下一步：试 --k 3 --floor 2（降门限），看比值是否 >1")
    else:
        print("   目标增强值已过门限，但检出率仍低 → 瓶颈可能在【候选筛选/排序】环节")


if __name__ == "__main__":
    main()
