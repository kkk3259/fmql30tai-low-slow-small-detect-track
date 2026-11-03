# -*- coding: utf-8 -*-
"""
ROI 数据集制作工具（A 的工作第一步）

作用：把「视频 + 真值 CSV」变成 NPU 训练用的 ROI 样本集
      正样本 = 目标位置裁的 128x128 灰度图块
      负样本 = ① 背景随机位置  ② 检测器虚警位置（难负样本，最有价值）

 关键：裁剪用的是 ps_app.py 里的 crop_roi()，保证【训练与推理预处理完全一致】。

用法：
  # 用合成序列（最快上手，真值精确）
  python train/make_roi_dataset.py --src results/synth_r1.5_a15.mp4 --out D:\\lowslow\\data\\roi

  # 用公开数据集转出来的序列（先按 03 节的方法转成 mp4 + gt.csv）
  python train/make_roi_dataset.py --src D:\\lowslow\\data\\seqA.mp4 --out D:\\lowslow\\data\\roi

输出结构：
  <out>/pos/*.png        正样本（目标）
  <out>/neg_bg/*.png     负样本（背景）
  <out>/neg_fa/*.png     负样本（检测器虚警，难负样本）
  <out>/labels.csv       一张表：文件名,标签,来源,帧号,x,y
  <out>/stats.txt        统计信息
"""
import argparse
import csv
import os
import random
import sys
from collections import Counter

import cv2
import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJ = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_PROJ, "baseline"))
sys.path.insert(0, os.path.join(_PROJ, "ps"))

from run import to_gray_down, gauss, tophat                 # noqa: E402
from detect_v1 import adaptive_threshold, extract_candidates  # noqa: E402
from ps_app import crop_roi, ROI_SIZE                         # noqa: E402   复用同一裁剪函数


def ensure_dirs(out):
    for d in ("pos", "neg_bg", "neg_fa"):
        os.makedirs(os.path.join(out, d), exist_ok=True)


def main():
    ap = argparse.ArgumentParser(description="ROI 数据集制作（对接 I3/I4 接口）")
    ap.add_argument("--src", required=True, help="视频路径（mp4/avi）")
    ap.add_argument("--gt", default="", help="真值 CSV（frame,x,y[,...]）；默认取同名 _gt.csv")
    ap.add_argument("--out", required=True, help="输出目录（建议放仓库外，如 D:\\lowslow\\data\\roi）")
    ap.add_argument("--down", type=int, default=2, help="降采样倍率（与 ps_app 一致=2）")
    ap.add_argument("--max-frames", type=int, default=0, help="最多处理多少帧（0=全部）")

    # 采样控制
    ap.add_argument("--pos-per-frame", type=int, default=1, help="每帧取几个正样本")
    ap.add_argument("--jitter", type=int, default=3, help="正样本位置抖动范围（像素，做数据增强）")
    ap.add_argument("--neg-bg-per-frame", type=int, default=2, help="每帧取几个背景负样本")
    ap.add_argument("--neg-fa-per-frame", type=int, default=2, help="每帧从虚警里取几个负样本")

    # 检测器参数（用于产生虚警）
    ap.add_argument("--k", type=float, default=4.0)
    ap.add_argument("--floor", type=float, default=3.0)
    ap.add_argument("--tophat", type=int, default=5)
    ap.add_argument("--gate", type=float, default=3.0, help="判定'命中真值'的半径")
    args = ap.parse_args()

    gt_file = args.gt or (os.path.splitext(args.src)[0] + "_gt.csv")
    if not os.path.exists(args.src):
        raise SystemExit("找不到视频：" + args.src)
    if not os.path.exists(gt_file):
        raise SystemExit("找不到真值：" + gt_file + "\n（可先用 tools/mark_gt.py 标注生成）")

    gt = {}
    with open(gt_file, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            k = [x for x in r.keys()]
            fr = int(r.get("frame", r.get(k[0])))
            gt[fr] = (float(r.get("x", 0)), float(r.get("y", 0)))

    ensure_dirs(args.out)
    rng = random.Random(0)

    cap = cv2.VideoCapture(args.src)
    if not cap.isOpened():
        raise SystemExit("打不开视频：" + args.src)
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) // args.down
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) // args.down

    rows = []
    stat = Counter()
    frame_idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if args.max_frames and frame_idx >= args.max_frames:
            break

        gray = to_gray_down(frame, args.down)          # 与推理链一致

        # ---------- ① 正样本：真值位置（带抖动增强）----------
        if frame_idx in gt:
            gx, gy = gt[frame_idx][0] / args.down, gt[frame_idx][1] / args.down
            for i in range(args.pos_per_frame):
                jx = gx + (rng.randint(-args.jitter, args.jitter) if i else 0)
                jy = gy + (rng.randint(-args.jitter, args.jitter) if i else 0)
                roi, _ = crop_roi(gray, jx, jy, ROI_SIZE)
                name = "pos/f{:05d}_{}.png".format(frame_idx, i)
                cv2.imwrite(os.path.join(args.out, name), roi)
                rows.append([name, 1, "pos", frame_idx, round(jx, 2), round(jy, 2)])
                stat["pos"] += 1

        # ---------- ② 负样本 A：背景随机位置 ----------
        for i in range(args.neg_bg_per_frame):
            # 随机位置要离真值足够远，避免误裁到目标
            for _ in range(20):
                rx = rng.uniform(ROI_SIZE / 2, W - ROI_SIZE / 2)
                ry = rng.uniform(ROI_SIZE / 2, H - ROI_SIZE / 2)
                if frame_idx not in gt:
                    break
                tx, ty = gt[frame_idx][0] / args.down, gt[frame_idx][1] / args.down
                if (rx - tx) ** 2 + (ry - ty) ** 2 > (60 ** 2):
                    break
            roi, _ = crop_roi(gray, rx, ry, ROI_SIZE)
            name = "neg_bg/f{:05d}_{}.png".format(frame_idx, i)
            cv2.imwrite(os.path.join(args.out, name), roi)
            rows.append([name, 0, "neg_bg", frame_idx, round(rx, 2), round(ry, 2)])
            stat["neg_bg"] += 1

        # ---------- ③ 负样本 B：检测器虚警位置（ 难负样本，最有价值）----------
        if args.neg_fa_per_frame > 0:
            th = tophat(gauss(gray, 0), args.tophat)
            binary, _ = adaptive_threshold(th, 31, args.k, args.floor)
            cands = extract_candidates(binary, th, 2, 200, 16)
            # 找出"没命中真值"的候选 = 虚警
            fa = []
            for c in cands:
                hit = False
                if frame_idx in gt:
                    tx, ty = gt[frame_idx][0] / args.down, gt[frame_idx][1] / args.down
                    hit = (c["x"] - tx) ** 2 + (c["y"] - ty) ** 2 <= args.gate ** 2
                if not hit:
                    fa.append(c)
            for c in fa[:args.neg_fa_per_frame]:
                roi, _ = crop_roi(gray, c["x"], c["y"], ROI_SIZE)
                name = "neg_fa/f{:05d}_{}.png".format(frame_idx, len(rows))
                cv2.imwrite(os.path.join(args.out, name), roi)
                rows.append([name, 0, "neg_fa", frame_idx, round(c["x"], 2), round(c["y"], 2)])
                stat["neg_fa"] += 1

        frame_idx += 1
    cap.release()

    # ---------- 写标签表与统计 ----------
    with open(os.path.join(args.out, "labels.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["file", "label", "source", "frame", "x", "y"])
        w.writerows(rows)

    npos = stat["pos"]
    nneg = stat["neg_bg"] + stat["neg_fa"]
    lines = [
        "处理帧数      : {}".format(frame_idx),
        "ROI 尺寸      : {}x{}（灰度）".format(ROI_SIZE, ROI_SIZE),
        "正样本 (pos)  : {}".format(npos),
        "负样本 背景   : {}".format(stat["neg_bg"]),
        "负样本 虚警   : {}".format(stat["neg_fa"]),
        "负样本 合计   : {}".format(nneg),
        "正负比        : 1 : {:.2f}".format(nneg / max(npos, 1)),
        "输出目录      : {}".format(args.out),
    ]
    with open(os.path.join(args.out, "stats.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("")
    print("=== ROI 数据集制作完成 ===")
    for l in lines:
        print("  " + l)
    print("")
    print("  建议：正负比控制在 1:2 ~ 1:5；样本总数建议 ≥5000（每类 ≥1000）")


if __name__ == "__main__":
    main()
