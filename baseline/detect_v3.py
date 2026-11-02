# -*- coding: utf-8 -*-
"""
低小慢目标检测 —— 软件基线 v3：时域增强（Temporal Enhancement）

为什么需要 v3？
    参数扫描实验（tools/sweep_synth.py）证明：目标对比度 ≤5 灰阶时，
    单帧检测的检出率 Pd ≈ 0% —— 空间域手段（Top-Hat + CFAR）已到极限。
    日志里 v1 的检测链是：
        灰度+降采样 → 高斯 → Top-Hat → CFAR → 候选
    全部是【空间域】操作，完全没有利用【时间维度】的信息。

时域增强的原理：
    噪声   在时间上【随机、不相关】→ n 帧平均后幅度降 √n
    目标   在时间上【持续、相关】  → n 帧平均后幅度基本不变
    ⇒ 信噪比提升 ≈ √n   （n=16 时约 +12 dB）

两种时域方案（可用 --mode 切换，便于对比）：
    ① bg  背景滑动平均 + 帧差
        bg[i] = α·bg[i-1] + (1-α)·frame[i]
        fg    = frame[i] - bg[i]
        静止背景（云团、地物）被"学"进 bg 并减掉，运动目标被保留。
        不要求目标静止；硬件只需 1 帧缓存 + 1 次乘加。

    ② acc 多帧滑动平均（时域积累）
        avg = mean(frame[i-N+1 .. i])
        对慢速目标（本课题正是"低·小·慢"）有效；目标移动过快时会糊。

    ③ both 先 bg 再 acc。`n    ④ tmax 时间域 Top-Hat：max_N − median_N（对运动目标也有效）。

用法：
    python detect_v3.py --src synth                          # 默认 bg 模式
    python detect_v3.py --src synth --mode acc --n-acc 16     # 时域积累 16 帧
    python detect_v3.py --src synth --mode none               # 关掉时域（等价 v1）
    python detect_v3.py --src synth --target-amp 5 --mode none  # 低对比度 + 无时域 → Pd 应≈0
    python detect_v3.py --src synth --target-amp 5 --mode acc --n-acc 16  # 低对比度 + 时域 → 看提升

================================================================================
【实验结论】（2026-10-04 实测，数据见 results/v3_temporal_sweep.csv）
================================================================================
在合成序列（半径 1.5px，噪声 σ≈2）上系统对比了 5 种方案，结果：

  对比度 |  none(基准) |  bg  | acc16 | tmax8 | mc16
  -------|-------------|------|-------|-------|------
     5   |     0.0%    | 0.0% |  0.0% |  0.0% |  0.0%
     7   |     0.0%    | 0.0% |  0.0% |  0.0% |  0.0%
     9   |    12.1%    |10.0% |  0.0% |  0.0% |  0.0%
    11   |    48.6%    |36.4% |  0.0% |  8.6% |  0.0%
    13   |    82.1%    |73.6% |  0.0% | 28.6% |  0.0%

结论（负面结果，同样有价值）：
  1. 单帧可检极限 ≈ 对比度 8~9 灰阶（低于此 Pd 恒为 0）。
  2. bg（背景滑动平均）能显著压虚警（26 → 0），但对 Pd 无提升 —— 它只减背景
     均值，不降噪声标准差。
  3. acc（多帧平均）、tmax（时间域 Top-Hat）、mc（运动补偿+平均）**均不如单帧**。
  4. 根本原因：目标尺度约 1.5px（亚像素级）、帧间移动约 0.6px（降采样后），
     帧间对齐的精度要求（<0.2px）超出图像离散化分辨能力 → 积累时目标互相抵消，
     且插值/对齐本身引入的损失远大于 √N 的积累收益。
     该结论在"降采样前（原图 1280×720）做时域"时同样成立。

因此本课题的有效时域手段不是"像素域时间积累"，而是
【航迹级时域确认】（Track-Before-Confirm）：
    单帧用较低门限检出 → 依靠"同一位置连续 N 帧出现"过滤随机虚警。
    这一机制已在 v2（track_v2.py）实现并实测：虚警 5412 次/分 → 0 次/分。
================================================================================"""
import argparse
import csv
import os
import sys
import time
from collections import deque

import cv2
import numpy as np

# 复用已验证的处理函数（同目录）
from run import make_synthetic, to_gray_down, gauss, tophat
from detect_v1 import adaptive_threshold, extract_candidates


# ================================================================ 时域增强器
class TemporalEnhancer:
    """时域增强：背景滑动平均 + 多帧滑动平均。

    设计要点：
      - 用 deque 做定长窗口，天然支持"滑动"（而不是从头累加）
      - 前 n_acc 帧处于"热身期"，输出可能与稳态不同（评估时可 --warmup 跳过）
      - 所有运算都是逐像素的乘加/平均 → 与 PL 的帧缓存流水线结构一一对应
    """

    def __init__(self, mode="bg", alpha=0.9, n_acc=8, vel_x=0.0, vel_y=0.0, no_interp=True):
        self.mode = mode
        self.alpha = float(alpha)
        self.n_acc = int(n_acc)
        self.bg = None                      # 背景估计（浮点）
        self.buf = deque(maxlen=self.n_acc)  # 多帧滑动窗口（acc 模式）
        self.buf2 = deque(maxlen=self.n_acc)  # both 模式专用窗口（避免与 acc 互相干扰）
        self.vel_x = float(vel_x)      # 目标速度（降采样后像素/帧），用于运动补偿
        self.vel_y = float(vel_y)
        self.no_interp = bool(no_interp)   # True=整数像素对齐（无插值损失）
        self.count = 0

    def __call__(self, gray):
        if self.mode == "none":
            return gray

        f = gray.astype(np.float32)
        self.count += 1

        out_bg = None
        out_acc = None

        # ---- ① 背景滑动平均 + 帧差 ----
        if self.mode in ("bg", "both"):
            if self.bg is None:
                self.bg = f.copy()                 # 第一帧当初始背景
                out_bg = np.zeros_like(f)          # 首帧没有前景
            else:
                self.bg = self.alpha * self.bg + (1.0 - self.alpha) * f
                fg = f - self.bg                   # 前景 = 当前帧 − 背景
                out_bg = np.clip(fg, 0, 255)       # 只保留"变亮"的部分（目标比背景亮）

        # ---- ② 多帧滑动平均（时域积累）----
        if self.mode in ("acc", "both"):
            self.buf.append(f)
            out_acc = np.mean(self.buf, axis=0)
            if len(self.buf) < 2:                  # 窗口未满时退化为原图
                out_acc = f

        # ---- ③ 时间域 Top-Hat：max_N − median_N ----
        # 目标（持续几帧的亮点）出现在 max 里、不在中值里 → 保留；
        # 随机噪声在两者中都存在 → 相减后抵消。且不要求目标静止。
        if self.mode == "tmax":
            self.buf.append(f)
            if len(self.buf) >= 3:
                arr = np.stack(self.buf, axis=0)
                mx = arr.max(axis=0)
                md = np.median(arr, axis=0)
                out = np.clip(mx - md, 0, 255)
            else:
                out = f

        # ---- ④ mc 运动补偿 + 时域平均 ----
        # 关键：先把窗口内各帧按目标速度反向平移"对齐"，再平均 —— 
        # 对齐后目标位置固定，平均只降噪声（√N），不再稀释目标。
        if self.mode == "mc":
            self.buf.append(f)
            n = len(self.buf)
            if n >= 3:
                acc = np.zeros_like(f)
                for k, fr in enumerate(self.buf):       # k=0 是最旧的一帧
                    dt = (n - 1 - k)                    # 该帧与"最新帧"的帧差
                    mx = -self.vel_x * dt               # 反向平移，对齐到最新帧
                    my = -self.vel_y * dt
                    M = np.float32([[1, 0, mx], [0, 1, my]])
                    # 关键：用 NEAREST（整数像素平移）避免双线性插值把点目标"抹平"
                    interp = cv2.INTER_NEAREST if self.no_interp else cv2.INTER_LINEAR
                    acc += cv2.warpAffine(fr, M, (f.shape[1], f.shape[0]),
                                          flags=interp, borderMode=cv2.BORDER_REPLICATE)
                out = acc / n
            else:
                out = f

        # ---- 合并 ----
        if self.mode == "mc":
            return np.clip(out, 0, 255).astype(np.uint8)
        if self.mode == "tmax":
            return np.clip(out, 0, 255).astype(np.uint8)
        if self.mode == "bg":
            out = out_bg
        elif self.mode == "acc":
            out = out_acc
        else:                                      # both：先背景抑制，再时域平均去噪
            if self.count <= 1:
                out = f
            else:
                self.buf.append(out_bg)
                out = np.mean(self.buf, axis=0)

        return np.clip(out, 0, 255).astype(np.uint8)


# ================================================================ 主流程
def run_sequence(src, enhancer, cfg, out_path=None, csv_path=None, max_frames=0):
    """跑一整段序列：读帧 → 预处理 → 时域增强 → 检测 → 统计，返回指标"""
    # 打开视频源（synth = 现场生成合成序列）
    if src == "synth":
        here = os.path.dirname(os.path.abspath(__file__))
        # 按"半径+对比度"命名，避免不同实验参数互相覆盖
        video = os.path.join(here, "..", "results",
                             "synth_r{}_a{}.mp4".format(cfg["target_radius"], int(cfg["target_amp"])))
        video = os.path.abspath(video)
        if not os.path.exists(video):
            os.makedirs(os.path.dirname(video), exist_ok=True)
            make_synthetic(video, n_frames=150, clouds=14,
                           target_radius=cfg["target_radius"], target_amp=cfg["target_amp"])
        gt_file = os.path.splitext(video)[0] + "_gt.csv"
    else:
        video = src
        gt_file = os.path.splitext(video)[0] + "_gt.csv"

    gt = {}
    if os.path.exists(gt_file):
        with open(gt_file, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                gt[int(r["frame"])] = (float(r["x"]), float(r["y"]))  # 兼容带小数的真值（mark_gt.py 输出）

    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        raise SystemExit("打不开视频：" + video)

    vw = None
    if out_path:
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        vw = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w * 3, h // 2))
        if not vw.isOpened():
            raise SystemExit("输出视频写入器打不开：" + out_path)

    rows = []
    hits = misses = fp = n_gt = 0
    cand_sum = 0
    frame_idx = 0
    t0 = time.time()

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if max_frames and frame_idx >= max_frames:
            break

        # ---- 标准预处理 ----
        gray = to_gray_down(frame, cfg["down"])

        # ----  v3 时域增强 ----
        enh = enhancer(gray)

        # ---- 后续与 v1 一致：高斯 → Top-Hat → CFAR → 候选 ----
        g = gauss(enh, cfg["gauss"])
        th = tophat(g, cfg["tophat"])
        binary, _ = adaptive_threshold(th, cfg["win"], cfg["k"], cfg["floor"])
        cands = extract_candidates(binary, th, cfg["min_area"], cfg["max_area"], cfg["topk"])
        cand_sum += len(cands)

        # ---- 统计（跳过热身期）----
        if frame_idx in gt and frame_idx >= cfg["warmup"]:
            n_gt += 1
            gx, gy = gt[frame_idx][0] / cfg["down"], gt[frame_idx][1] / cfg["down"]
            hit = any((c["x"] - gx) ** 2 + (c["y"] - gy) ** 2 <= cfg["gate"] ** 2 for c in cands)
            if hit:
                hits += 1
            else:
                misses += 1
            fp += max(0, len(cands) - (1 if hit else 0))
            best = None
            if cands:
                best = min(cands, key=lambda c: (c["x"] - gx) ** 2 + (c["y"] - gy) ** 2)
            rows.append([frame_idx, gx, gy,
                         round(best["x"], 2) if best else "",
                         round(best["y"], 2) if best else "",
                         1 if hit else 0])

        # ---- 可视化 ----
        if vw is not None:
            panels = []
            for img, label in ((gray, "1 Original"), (enh, "2 Temporal(enh)"), (binary, "3 Binary")):
                p = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR) if img.ndim == 2 else img.copy()
                for c in cands:
                    cv2.rectangle(p, (int(c["x"] - 8), int(c["y"] - 8)),
                                  (int(c["x"] + 8), int(c["y"] + 8)), (0, 255, 0), 1)
                cv2.putText(p, label, (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
                panels.append(p)
            panel = np.hstack(panels)
            vw.write(panel)

        frame_idx += 1

    cap.release()
    if vw is not None:
        vw.release()

    dt = time.time() - t0
    pd = 100.0 * hits / n_gt if n_gt else 0.0
    return dict(frames=frame_idx, n_gt=n_gt, hits=hits, misses=misses,
                pd=pd, fp=fp, cand_avg=cand_sum / max(frame_idx, 1),
                ms_per_frame=1000.0 * dt / max(frame_idx, 1))


def main():
    ap = argparse.ArgumentParser(description="低小慢检测 v3（时域增强）")
    ap.add_argument("--src", default="synth", help="视频路径，或 synth 生成合成序列")
    ap.add_argument("--out", default="")
    ap.add_argument("--csv", default="")
    ap.add_argument("--max-frames", type=int, default=0)

    # ---- 时域参数（v3 核心）----
    ap.add_argument("--mode", default="bg", choices=["none", "bg", "acc", "both", "tmax", "mc"],
                    help="时域增强模式：none=关闭(等价v1) / bg=背景滑动平均 / acc=多帧平均 / both")
    ap.add_argument("--alpha", type=float, default=0.9,
                    help="背景更新率（bg 模式）：越大背景越稳定，越小越快跟上背景变化")
    ap.add_argument("--n-acc", type=int, default=8, help="时域积累帧数（acc 模式）")
    ap.add_argument("--warmup", type=int, default=10, help="热身帧数（统计时跳过前 N 帧）")
    ap.add_argument("--vel-x", type=float, default=0.6,
                    help="目标水平速度（降采样后 px/帧），仅 mc 模式用；合成序列 vx=1.2/2=0.6")
    ap.add_argument("--no-interp", type=int, default=1, help="mc 模式：1=整数对齐(无插值) 0=亚像素线性插值")
    ap.add_argument("--vel-y", type=float, default=0.175,
                    help="目标垂直速度（降采样后 px/帧），仅 mc 模式用；合成序列 vy=0.35/2=0.175")

    # ---- 检测参数（与 v1 一致）----
    ap.add_argument("--down", type=int, default=2)
    ap.add_argument("--gauss", type=int, default=0)
    ap.add_argument("--tophat", type=int, default=5)
    ap.add_argument("--win", type=int, default=31)
    ap.add_argument("--k", type=float, default=4.0)
    ap.add_argument("--floor", type=float, default=3.0)
    ap.add_argument("--min-area", type=int, default=2)
    ap.add_argument("--max-area", type=int, default=200)
    ap.add_argument("--topk", type=int, default=5)
    ap.add_argument("--gate", type=float, default=3.0)

    # ---- 合成序列参数（便于做低对比度实验）----
    ap.add_argument("--target-radius", type=float, default=1.5)
    ap.add_argument("--target-amp", type=float, default=15.0)

    a = ap.parse_args()

    cfg = dict(down=a.down, gauss=a.gauss, tophat=a.tophat, win=a.win, k=a.k,
               floor=a.floor, min_area=a.min_area, max_area=a.max_area,
               topk=a.topk, gate=a.gate, warmup=a.warmup,
               target_radius=a.target_radius, target_amp=a.target_amp)

    enhancer = TemporalEnhancer(mode=a.mode, alpha=a.alpha, n_acc=a.n_acc,
                                vel_x=a.vel_x, vel_y=a.vel_y, no_interp=bool(a.no_interp))

    print("")
    print("=== v3 时域增强检测 ===")
    print("  视频源      : {}".format(a.src))
    print("  时域模式    : {}" .format(a.mode if a.mode != "none" else "none（等价 v1，单帧）"))
    if a.mode in ("bg", "both"):
        print("    alpha     : {}".format(a.alpha))
    if a.mode in ("acc", "both"):
        print("    n_acc     : {} 帧（理论 SNR 提升 √{} ≈ {:.1f} 倍 ≈ {:+.1f} dB）".format(
            a.n_acc, a.n_acc, a.n_acc ** 0.5, 10 * np.log10(a.n_acc) / 2))
    print("  检测参数    : k={} floor={} tophat={} win={}".format(a.k, a.floor, a.tophat, a.win))
    print("  合成目标    : 半径 {}px / 对比度 {} 灰阶".format(a.target_radius, a.target_amp))
    print("")

    r = run_sequence(a.src, enhancer, cfg, a.out or None, a.csv or None, a.max_frames)

    print("--- 结果 ---")
    print("  处理帧数    : {}".format(r["frames"]))
    print("  真值帧数    : {}".format(r["n_gt"]))
    print("  检出(命中)  : {}".format(r["hits"]))
    print("  漏检        : {}".format(r["misses"]))
    print("   检出率 Pd : {:.1f}%".format(r["pd"]))
    print("  虚警数      : {}".format(r["fp"]))
    print("  候选/帧     : {:.2f}".format(r["cand_avg"]))
    print("  单帧耗时    : {:.2f} ms".format(r["ms_per_frame"]))
    print("")


if __name__ == "__main__":
    main()
