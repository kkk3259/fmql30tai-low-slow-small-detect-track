# -*- coding: utf-8 -*-
"""
低小慢目标检测 —— 软件基线 v0（纯 CPU / OpenCV）
处理链：读帧 -> 灰度化 -> 2x降采样 -> 3x3高斯 -> Top-Hat 形态学增强 -> 三画面对比输出 MP4

用法：
  python run.py --src synth
  python run.py --src D:\\lowslow\\data\\seqA.mp4 --out D:\\lowslow\\results\\baseline_seqA.mp4
"""
import argparse
import csv
import os
import time

import cv2
import numpy as np


# ---------------------------------------------------------------- 合成序列
def make_synthetic(path, w=1280, h=720, fps=30, n_frames=150, clouds=14,
                   target_radius=1.5, target_amp=15.0):
    """合成序列（贴近真实低空背景）：
      背景 = 基础天空 + 若干低频云团（幅度可达 ±40 灰阶，制造局部杂波）+ 传感器噪声
      目标 = 半径约 1.5px、对比度约 15 灰阶、约 1.2px/帧 缓慢移动的小亮点
    价值：真值精确、参数可控；云团的存在让 Top-Hat 的作用能被量化出来。"""
    h_out = h - (h % 2)
    w_out = w - (w % 2)
    vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w_out, h_out))
    if not vw.isOpened():
        raise SystemExit("合成视频写入器打不开：" + path)
    rng = np.random.default_rng(0)
    yy_g, xx_g = np.mgrid[0:h_out, 0:w_out].astype(np.float32)
    base = np.full((h_out, w_out), 120.0, np.float32)
    for _ in range(clouds):                                  # 低频云团 -> 局部杂波
        cx, cy = rng.integers(0, w_out), rng.integers(0, h_out)
        sx, sy = rng.integers(60, 180), rng.integers(40, 120)
        amp = rng.uniform(-35, 45)
        base += amp * np.exp(-(((xx_g - cx) ** 2 / (2.0 * sx ** 2)) + ((yy_g - cy) ** 2 / (2.0 * sy ** 2))))
    base = np.clip(base, 30, 240)
    half = max(3, int(np.ceil(float(target_radius) * 3)))       # 目标窗口半宽（取 3 倍半径）
    yy, xx = np.mgrid[-half:half + 1, -half:half + 1]
    spot = float(target_amp) * np.exp(-(yy ** 2 + xx ** 2) / (2 * float(target_radius) ** 2))
    x0, y0, vx, vy = w_out // 4, h_out // 2, 1.2, 0.35
    gt = []
    for i in range(n_frames):
        img = base + rng.normal(0, 2.0, (h_out, w_out)).astype(np.float32)
        cx, cy = int(x0 + vx * i), int(y0 + vy * i)
        img[cy - half:cy + half + 1, cx - half:cx + half + 1] += spot
        vw.write(cv2.cvtColor(np.clip(img, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR))
        gt.append((i, cx, cy))
    vw.release()
    with open(os.path.splitext(path)[0] + "_gt.csv", "w", newline="") as f:
        r = csv.writer(f)
        r.writerow(["frame", "x", "y"])
        r.writerows(gt)
    print("[合成] {} 已生成（{} 帧，真值见同名 _gt.csv）".format(path, n_frames))


# ---------------------------------------------------------------- 处理链各级
def to_gray_down(frame_bgr, down):
    """灰度化 + 降采样（对应 PL 的 IP1 第一级）"""
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    if down > 1:
        gray = gray[::down, ::down]
    return np.ascontiguousarray(gray)


def gauss(gray, k):
    """高斯去噪（对应 PL 的 IP1 第二级）"""
    return gray if k < 3 else cv2.GaussianBlur(gray, (k, k), 0)


def tophat(gray, se):
    """Top-Hat 形态学增强（对应 PL 的 IP2 空域部分）：矩形结构元 -> 硬件只需 min/max 比较器"""
    if se < 3:
        return gray
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (se, se))
    return cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, kernel)


# ---------------------------------------------------------------- 指标
def metrics(img, x, y, r_win=32, r_guard=6):
    """在一个大窗口内统计：目标峰高、背景中位数、背景起伏标准差 σ。
    故意排除目标周围 guard 区，避免目标自身污染背景统计。"""
    h, w = img.shape[:2]
    r_win = min(r_win, (min(h, w) - 1) // 2)
    x0 = min(max(int(x) - r_win, 0), w - (2 * r_win + 1))
    y0 = min(max(int(y) - r_win, 0), h - (2 * r_win + 1))
    big = img[y0:y0 + 2 * r_win + 1, x0:x0 + 2 * r_win + 1].astype(np.float32)
    gx, gy = int(x) - x0, int(y) - y0
    gx = min(max(gx, 0), big.shape[1] - 1)
    gy = min(max(gy, 0), big.shape[0] - 1)
    mask = np.ones(big.shape, bool)
    mask[max(0, gy - r_guard):gy + r_guard + 1, max(0, gx - r_guard):gx + r_guard + 1] = False
    bg = big[mask]
    peak = float(big[max(0, gy - r_guard):gy + r_guard + 1,
                     max(0, gx - r_guard):gx + r_guard + 1].max())
    return peak, float(np.median(bg)), float(bg.std())


def snr_db(peak, bg_med, bg_std, floor=0.5):
    """峰高/背景起伏，用 dB 表示。σ 取不到（被完全压平）时用下限 floor 兜底，避免除零虚高。"""
    ratio = (peak - bg_med) / max(bg_std, floor)
    return ratio, 20.0 * np.log10(max(ratio, 1e-6))


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="synth", help="输入视频路径；写 synth 先生成合成序列")
    ap.add_argument("--out", default="baseline_out.mp4")
    ap.add_argument("--csv", default="baseline_timing.csv")
    ap.add_argument("--down", type=int, default=2, help="降采样倍率，1=不降")
    ap.add_argument("--gauss", type=int, default=3, help="高斯核（奇数），<3 关闭")
    ap.add_argument("--tophat", type=int, default=5, help="Top-Hat 结构元大小，<3 关闭")
    ap.add_argument("--max-frames", type=int, default=0, help="0=全部")
    ap.add_argument("--threads", type=int, default=1, help="OpenCV 线程数；1=单核")
    ap.add_argument("--codec", default="mp4v", help="fourcc，如 mp4v / MJPG / XVID")
    a = ap.parse_args()

    cv2.setNumThreads(max(1, a.threads))

    gt = {}
    if a.src == "synth":
        a.src = "synth_sky.mp4"
        if not os.path.exists(a.src):
            make_synthetic(a.src)
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
    n_in = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print("[输入] {}  {}x{}  {:.1f}fps  共 {} 帧".format(a.src, w_in, h_in, fps_in, n_in))

    # 输出画布：三画面并排，每格 (w_in/2, h_in/2)
    hw, hh = w_in // 2, h_in // 2
    W_OUT, H_OUT = hw * 3, hh
    vw = cv2.VideoWriter(a.out, cv2.VideoWriter_fourcc(*a.codec), fps_in, (W_OUT, H_OUT))
    if not vw.isOpened():
        alt = os.path.splitext(a.out)[0] + ".avi"
        print("[提示] {} 打不开，改用 MJPG/avi：{}".format(a.codec, alt))
        a.out = alt
        vw = cv2.VideoWriter(a.out, cv2.VideoWriter_fourcc(*"MJPG"), fps_in, (W_OUT, H_OUT))
        if not vw.isOpened():
            raise SystemExit("输出视频写入器创建失败：" + a.out)
    print("[输出] {}  {}x{}".format(a.out, W_OUT, H_OUT))

    rows, m_before, m_after = [], [], []
    idx, t_begin = 0, time.perf_counter()
    while True:
        ok, frame = cap.read()
        if not ok or (a.max_frames and idx >= a.max_frames):
            break
        t0 = time.perf_counter()
        gray = to_gray_down(frame, a.down)
        t1 = time.perf_counter()
        g = gauss(gray, a.gauss)
        t2 = time.perf_counter()
        th = tophat(g, a.tophat)
        t3 = time.perf_counter()

        if idx in gt:
            gx, gy = gt[idx][0] / a.down, gt[idx][1] / a.down
            m_before.append(metrics(g, gx, gy))
            m_after.append(metrics(th, gx, gy))

        v1 = cv2.resize(frame, (hw, hh))
        v2 = cv2.cvtColor(cv2.resize(g, (hw, hh), interpolation=cv2.INTER_NEAREST), cv2.COLOR_GRAY2BGR)
        v3 = cv2.cvtColor(cv2.resize(cv2.normalize(th, None, 0, 255, cv2.NORM_MINMAX),
                                     (hw, hh), interpolation=cv2.INTER_NEAREST), cv2.COLOR_GRAY2BGR)
        panel = np.hstack([v1, v2, v3])
        assert panel.shape[0] == H_OUT and panel.shape[1] == W_OUT, "面板尺寸与写入器不一致！"
        for i, tag in enumerate(["1 Original", "2 Gray+Down", "3 TopHat"]):
            cv2.putText(panel, tag, (10 + i * hw, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        cv2.putText(panel, "frame {}".format(idx), (10, hh - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        vw.write(panel)

        rows.append([idx, (t1 - t0) * 1e3, (t2 - t1) * 1e3, (t3 - t2) * 1e3, (t3 - t0) * 1e3])
        idx += 1

    t_total = time.perf_counter() - t_begin
    cap.release()
    vw.release()

    with open(a.csv, "w", newline="") as f:
        r = csv.writer(f)
        r.writerow(["frame", "gray_down_ms", "gauss_ms", "tophat_ms", "frame_total_ms"])
        r.writerows(rows)

    if not rows:
        raise SystemExit("没有读到任何帧")
    arr = np.array([r[1:] for r in rows], dtype=float)
    print("")
    print("===== 基线结果 =====")
    print("处理帧数        : {}".format(len(rows)))
    print("平均处理帧率    : {:.2f} fps".format(len(rows) / t_total))
    print("单帧总耗时      : 均值 {:.2f} ms | 最大 {:.2f} ms | P95 {:.2f} ms".format(
        arr[:, 3].mean(), arr[:, 3].max(), np.percentile(arr[:, 3], 95)))
    print("分阶段均值      : 灰度+降采样 {:.2f} ms | 高斯 {:.2f} ms | TopHat {:.2f} ms".format(
        arr[:, 0].mean(), arr[:, 1].mean(), arr[:, 2].mean()))

    if m_before:
        pb = np.mean([m[0] for m in m_before]); mb_ = np.mean([m[1] for m in m_before]); sb = np.mean([m[2] for m in m_before])
        pa = np.mean([m[0] for m in m_after]); ma_ = np.mean([m[1] for m in m_after]); sa = np.mean([m[2] for m in m_after])
        rb, db_b = snr_db(pb, mb_, sb)
        ra, db_a = snr_db(pa, ma_, sa)
        print("")
        print("目标可检测性（真值处平均，窗口 65x65）")
        print("  增强前 : 峰高 {:5.2f} 灰阶 | 背景起伏σ {:5.2f} | 峰/σ {:7.2f} ({:5.2f} dB)".format(pb - mb_, sb, rb, db_b))
        print("  增强后 : 峰高 {:5.2f} 灰阶 | 背景起伏σ {:5.2f} | 峰/σ {:7.2f} ({:5.2f} dB)".format(pa - ma_, sa, ra, db_a))
        print("  提升   : {:5.2f} dB   （σ 到 0 表示背景被完全压平，已按下限 0.5 计）".format(db_a - db_b))
    print("")
    print("输出视频        : {}".format(os.path.abspath(a.out)))
    print("逐帧耗时        : {}".format(os.path.abspath(a.csv)))


if __name__ == "__main__":
    main()
