# -*- coding: utf-8 -*-
"""
低小慢目标检测 —— 软件基线 v1：自动检测（在 v0 增强链后面接"自适应阈值 + 连通域"）

链路（每一级都对应将来 PL / NPU 里的一块）：
  读帧 -> 灰度+降采样 -> 高斯 -> Top-Hat 增强 -> CFAR 自适应阈值 -> 连通域 -> 面积筛选 -> 画框
                                        (对应 IP1)      (对应 IP2 阈值级)  (对应 IP2 候选提取)

评估：合成序列带真值，统计 检出率 Pd 与 虚警数（这是报告里最硬的指标）

用法：
  python detect_v1.py --src synth
  python detect_v1.py --src synth --k 3.0                 # 阈值更松 -> 检出↑ 虚警↑
  python detect_v1.py --src synth --k 5.0                 # 阈值更严 -> 检出↓ 虚警↓
"""
import argparse
import csv
import os
import time

import cv2
import numpy as np

# 复用 v0 里已验证的处理函数（同目录）
from run import make_synthetic, to_gray_down, gauss, tophat


# ---------------------------------------------------------------- 自适应阈值（CFAR 式）
def adaptive_threshold(img, win=31, k=4.0, floor=1.0):
    """局部均值 + k×局部标准差 作为门限 —— 就是通信里的恒虚警检测思路。
    boxFilter 做滑动窗口统计，整幅图只需 O(1)/像素，硬件里同样是滑动累加实现。"""
    f = img.astype(np.float32)
    mu = cv2.boxFilter(f, -1, (win, win), normalize=True, borderType=cv2.BORDER_REFLECT)
    mu2 = cv2.boxFilter(f * f, -1, (win, win), normalize=True, borderType=cv2.BORDER_REFLECT)
    var = np.maximum(mu2 - mu * mu, 0.0)
    sd = np.sqrt(var)
    thr = mu + k * sd + floor
    return (f > thr).astype(np.uint8) * 255, thr


# ---------------------------------------------------------------- 连通域 -> 候选
def extract_candidates(binary, enh, min_area, max_area, topk):
    """把二值图里"连成一片的亮点"逐个找出来，按峰值强度排序取前 topk 个"""
    n, lab, stats, cents = cv2.connectedComponentsWithStats(binary, connectivity=8)
    out = []
    for i in range(1, n):                       # 0 号是背景
        x, y, w, h, area = stats[i]
        if area < min_area or area > max_area:
            continue
        m = (lab == i)
        peak = float(enh[m].max()) if m.any() else 0.0
        out.append({"x": float(cents[i][0]), "y": float(cents[i][1]),
                    "w": int(w), "h": int(h), "area": int(area), "peak": peak})
    out.sort(key=lambda c: -c["peak"])
    return out[:topk]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="synth")
    ap.add_argument("--out", default="results\\detect_v1.mp4")
    ap.add_argument("--csv", default="results\\detect_v1.csv")
    ap.add_argument("--down", type=int, default=2)
    ap.add_argument("--gauss", type=int, default=0, help="高斯核，<3 表示关闭（实测：3x3 高斯会把小目标削掉，Pd 从 95%% 掉到 81%%）")
    ap.add_argument("--tophat", type=int, default=5)
    ap.add_argument("--win", type=int, default=31, help="CFAR 局部窗口大小")
    ap.add_argument("--k", type=float, default=4.0, help="阈值 = 均值 + k*标准差")
    ap.add_argument("--floor", type=float, default=3.0, help="阈值最低下限（灰阶）")
    ap.add_argument("--min-area", type=int, default=2, help="候选最小面积（像素）")
    ap.add_argument("--max-area", type=int, default=200, help="候选最大面积（像素）")
    ap.add_argument("--topk", type=int, default=8, help="每帧最多输出候选数")
    ap.add_argument("--gate", type=float, default=3.0, help="命中判定半径（降采样图上的像素）")
    ap.add_argument("--max-frames", type=int, default=0)
    a = ap.parse_args()

    cv2.setNumThreads(1)

    gt = {}
    if a.src == "synth":
        a.src = "synth_sky.mp4"
        if not os.path.exists(a.src):
            make_synthetic(a.src)
    # 修正：任何视频源（包括真实视频）都尝试加载同名的 _gt.csv
    # 原实现只在 src=="synth" 时加载，导致真实视频统计不出 Pd / 虚警。
    gtf = os.path.splitext(a.src)[0] + "_gt.csv"
    if os.path.exists(gtf):
        with open(gtf) as f:
            for row in csv.DictReader(f):
                gt[int(row["frame"])] = (float(row["x"]), float(row["y"]))  # 兼容带小数的真值（mark_gt.py 输出 541.0 形式）

    cap = cv2.VideoCapture(a.src)
    if not cap.isOpened():
        raise SystemExit("打不开视频：" + str(a.src))
    fps_in = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w_in = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h_in = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print("[输入] {}  {}x{}  {:.1f}fps".format(a.src, w_in, h_in, fps_in))

    hw, hh = w_in // 2, h_in // 2
    W_OUT, H_OUT = hw * 3, hh
    vw = cv2.VideoWriter(a.out, cv2.VideoWriter_fourcc(*"mp4v"), fps_in, (W_OUT, H_OUT))
    if not vw.isOpened():
        raise SystemExit("输出视频写入器创建失败：" + a.out)
    print("[输出] {}  {}x{}".format(a.out, W_OUT, H_OUT))

    rows = []
    hits = miss = fp_total = frames_with_gt = 0
    cand_sum = 0
    idx, t_begin = 0, time.perf_counter()
    while True:
        ok, frame = cap.read()
        if not ok or (a.max_frames and idx >= a.max_frames):
            break
        t0 = time.perf_counter()
        gray = to_gray_down(frame, a.down)
        g = gauss(gray, a.gauss)
        th = tophat(g, a.tophat)
        t1 = time.perf_counter()
        binary, _ = adaptive_threshold(th, a.win, a.k, a.floor)
        cands = extract_candidates(binary, th, a.min_area, a.max_area, a.topk)
        t2 = time.perf_counter()

        # ---- 用真值算检出 / 虚警 ----
        hit_this = False
        if idx in gt:
            frames_with_gt += 1
            gx, gy = gt[idx][0] / a.down, gt[idx][1] / a.down
            for c in cands:
                if (c["x"] - gx) ** 2 + (c["y"] - gy) ** 2 <= a.gate ** 2:
                    hit_this = True
                    break
            if hit_this:
                hits += 1
            else:
                miss += 1
            fp_total += max(0, len(cands) - (1 if hit_this else 0))   # 除命中外的候选都算误报
            cand_sum += len(cands)

        # ---- 画面对比：原图 | 增强图+检测结果 | 二值图 ----
        v1 = cv2.resize(frame, (hw, hh))
        canv = cv2.cvtColor(cv2.normalize(th, None, 0, 255, cv2.NORM_MINMAX), cv2.COLOR_GRAY2BGR)
        canv = cv2.resize(canv, (hw, hh), interpolation=cv2.INTER_NEAREST)
        for c in cands:                                  # 绿色 = 检测到的候选（放大 2 倍画回原尺度）
            cx, cy = int(c["x"] * a.down), int(c["y"] * a.down)
            cv2.circle(canv, (cx, cy), 12, (0, 255, 0), 2)
        if idx in gt:                                    # 黄色 = 真值
            cv2.circle(canv, (gt[idx][0], gt[idx][1]), 4, (0, 255, 255), 2)
        v3 = cv2.cvtColor(cv2.resize(binary, (hw, hh), interpolation=cv2.INTER_NEAREST), cv2.COLOR_GRAY2BGR)
        panel = np.hstack([v1, canv, v3])
        assert panel.shape[0] == H_OUT and panel.shape[1] == W_OUT, "面板尺寸与写入器不一致！"
        for i, tag in enumerate(["1 Original", "2 Detect(green)/GT(yellow)", "3 Binary"]):
            cv2.putText(panel, tag, (10 + i * hw, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        cv2.putText(panel, "f{} cands={}".format(idx, len(cands)), (10, hh - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        vw.write(panel)

        rows.append([idx, (t1 - t0) * 1e3, (t2 - t1) * 1e3, (t2 - t0) * 1e3,
                     len(cands), 1 if hit_this else 0])
        idx += 1

    t_total = time.perf_counter() - t_begin
    cap.release()
    vw.release()

    with open(a.csv, "w", newline="") as f:
        r = csv.writer(f)
        r.writerow(["frame", "preproc_ms", "detect_ms", "frame_total_ms", "n_cand", "hit"])
        r.writerows(rows)
    if not rows:
        raise SystemExit("没有读到任何帧")

    arr = np.array([r[1:4] for r in rows], dtype=float)
    print("")
    print("===== v1 检测结果 =====")
    print("处理帧数        : {}".format(len(rows)))
    print("平均处理帧率    : {:.2f} fps".format(len(rows) / t_total))
    print("单帧总耗时      : 均值 {:.2f} ms | P95 {:.2f} ms".format(
        arr[:, 2].mean(), np.percentile(arr[:, 2], 95)))
    print("分阶段均值      : 预处理(灰度/降采样/高斯/TopHat) {:.2f} ms | 检测(阈值+连通域) {:.2f} ms".format(
        arr[:, 0].mean(), arr[:, 1].mean()))
    if frames_with_gt:
        pd_ = 100.0 * hits / frames_with_gt
        avg_cand = cand_sum / frames_with_gt
        minutes = frames_with_gt / fps_in / 60.0
        fa_rate = fp_total / minutes if minutes > 0 else 0
        print("")
        print("---- 检测指标（对 {} 帧有真值的画面）----".format(frames_with_gt))
        print("检出率 Pd       : {:.1f} %   (命中 {} / 漏检 {})".format(pd_, hits, miss))
        print("平均候选数/帧   : {:.2f}".format(avg_cand))
        print("误报候选总数    : {}".format(fp_total))
        print("虚警率 Fa       : {:.1f} 次/分钟".format(fa_rate))
        print("")
        print("参数说明: 阈值 = 局部均值 + {} x 局部标准差 + {}   (窗口 {}x{})".format(a.k, a.floor, a.win, a.win))
        print("         调大 --k 可降低虚警、调小可提高检出（这就是 Pd-Fa 曲线的扫描变量）")
    print("")
    print("输出视频        : {}".format(os.path.abspath(a.out)))
    print("逐帧数据        : {}".format(os.path.abspath(a.csv)))


if __name__ == "__main__":
    main()
