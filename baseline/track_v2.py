# -*- coding: utf-8 -*-
"""
低小慢目标检测 —— 软件基线 v2：多目标跟踪
在 v1（CFAR 阈值 + 连通域检测）后面加跟踪链：

  每帧检测候选 -> 卡尔曼预测 -> 贪心匹配(距离门限) -> 命中/丢失计数
                                                    -> 连续 N 帧命中才"确认"（抑制虚警）
                                                    -> 连续 M 帧丢失则删除
  输出：带编号(ID)的航迹 + 轨迹线；统计虚警率、跟踪成功率、ID 切换次数

用法：
  python track_v2.py --src synth
  python track_v2.py --src synth --confirm 3 --gate 12      # 调门限
  python track_v2.py --src synth --confirm 1                # 关掉确认(退化成逐帧检测)
"""
import argparse
import csv
import math
import os
import time

import cv2
import numpy as np

from run import make_synthetic, to_gray_down, gauss, tophat
from detect_v1 import adaptive_threshold, extract_candidates


# ---------------------------------------------------------------- 卡尔曼（匀速模型 x,y,vx,vy）
def new_kalman(x, y):
    kf = cv2.KalmanFilter(4, 2)
    kf.transitionMatrix = np.array([[1, 0, 1, 0],
                                    [0, 1, 0, 1],
                                    [0, 0, 1, 0],
                                    [0, 0, 0, 1]], np.float32)
    kf.measurementMatrix = np.array([[1, 0, 0, 0],
                                     [0, 1, 0, 0]], np.float32)
    kf.processNoiseCov = np.eye(4, dtype=np.float32) * 1e-2      # q：过程噪声
    kf.measurementNoiseCov = np.eye(2, dtype=np.float32) * 1e-1  # r：观测噪声
    kf.errorCovPost = np.eye(4, dtype=np.float32)
    kf.statePost = np.array([[x], [y], [0], [0]], np.float32)
    return kf


class Track(object):
    _next_id = 1

    def __init__(self, x, y, confirm_hits):
        self.id = Track._next_id
        Track._next_id += 1
        self.kf = new_kalman(x, y)
        self.hits = 1          # 累计命中次数
        self.miss = 0          # 连续丢失次数
        self.confirmed = (self.hits >= confirm_hits)
        self.trail = [(x, y)]  # 轨迹点（用于画线）

    def predict(self):
        p = self.kf.predict()
        return float(p[0, 0]), float(p[1, 0])

    def update(self, x, y, confirm_hits):
        self.kf.correct(np.array([[np.float32(x)], [np.float32(y)]]))
        self.hits += 1
        self.miss = 0
        self.trail.append((x, y))
        if len(self.trail) > 60:
            self.trail.pop(0)
        if self.hits >= confirm_hits:
            self.confirmed = True


def greedy_match(preds, dets, gate):
    """贪心匹配：把"预测位置"和"检测位置"按距离从近到远配对，超过门限的不配。"""
    pairs = []
    if not preds or not dets:
        return pairs
    cand = []
    for i, p in enumerate(preds):
        for j, d in enumerate(dets):
            dist = math.hypot(p[0] - d[0], p[1] - d[1])
            if dist <= gate:
                cand.append((dist, i, j))
    cand.sort()
    used_i, used_j = set(), set()
    for dist, i, j in cand:
        if i in used_i or j in used_j:
            continue
        pairs.append((i, j))
        used_i.add(i)
        used_j.add(j)
    return pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="synth")
    ap.add_argument("--out", default="results\\track_v2.mp4")
    ap.add_argument("--csv", default="results\\track_v2.csv")
    # 检测参数（沿用 v1 调优值）
    ap.add_argument("--down", type=int, default=2)
    ap.add_argument("--gauss", type=int, default=0)
    ap.add_argument("--tophat", type=int, default=5)
    ap.add_argument("--win", type=int, default=31)
    ap.add_argument("--k", type=float, default=4.0)
    ap.add_argument("--floor", type=float, default=3.0)
    ap.add_argument("--min-area", type=int, default=2)
    ap.add_argument("--max-area", type=int, default=200)
    ap.add_argument("--topk", type=int, default=8)
    # 跟踪参数
    ap.add_argument("--gate", type=float, default=12.0, help="匹配距离门限（降采样图上的像素）")
    ap.add_argument("--confirm", type=int, default=3, help="连续命中多少帧才确认航迹（抑制虚警的关键）")
    ap.add_argument("--max-miss", type=int, default=15, help="连续丢失多少帧后删除航迹")
    ap.add_argument("--max-frames", type=int, default=0)
    a = ap.parse_args()

    cv2.setNumThreads(1)

    gt = {}
    if a.src == "synth":
        a.src = "synth_sky.mp4"
        if not os.path.exists(a.src):
            make_synthetic(a.src)
        gtf = os.path.splitext(a.src)[0] + "_gt.csv"
        if os.path.exists(gtf):
            with open(gtf) as f:
                for row in csv.DictReader(f):
                    gt[int(row["frame"])] = (int(row["x"]), int(row["y"]))

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

    tracks = []
    rows = []
    raw_cand_total = 0        # v1 的原始候选总数（未确认）
    confirmed_frames = 0
    track_hit_frames = 0      # 真值被已确认航迹覆盖的帧数
    frames_with_gt = 0
    false_confirm = 0         # 已确认航迹中"不对应真值"的次数（虚警）
    id_switches = 0
    last_gt_id = None

    idx, t_begin = 0, time.perf_counter()
    while True:
        ok, frame = cap.read()
        if not ok or (a.max_frames and idx >= a.max_frames):
            break
        t0 = time.perf_counter()
        gray = to_gray_down(frame, a.down)
        g = gauss(gray, a.gauss)
        th = tophat(g, a.tophat)
        binary, _ = adaptive_threshold(th, a.win, a.k, a.floor)
        cands = extract_candidates(binary, th, a.min_area, a.max_area, a.topk)
        t1 = time.perf_counter()

        # ---- 跟踪 ----
        preds = [t.predict() for t in tracks]
        dets = [(c["x"], c["y"]) for c in cands]
        pairs = greedy_match(preds, dets, a.gate)
        used_t, used_d = set(), set()
        for ti, di in pairs:
            tracks[ti].update(dets[di][0], dets[di][1], a.confirm)
            used_t.add(ti)
            used_d.add(di)
        for i, t in enumerate(tracks):
            if i not in used_t:
                t.miss += 1
        for j in range(len(cands)):
            if j not in used_d:
                tracks.append(Track(dets[j][0], dets[j][1], a.confirm))
        tracks = [t for t in tracks if t.miss <= a.max_miss]
        confirmed = [t for t in tracks if t.confirmed]
        t2 = time.perf_counter()

        # ---- 统计（用真值判定） ----
        raw_cand_total += len(cands)
        if confirmed:
            confirmed_frames += 1
        if idx in gt:
            frames_with_gt += 1
            gx, gy = gt[idx][0] / a.down, gt[idx][1] / a.down
            hit_id = None
            for t in confirmed:
                px, py = t.kf.statePost[0, 0], t.kf.statePost[1, 0]
                if math.hypot(px - gx, py - gy) <= a.gate:
                    hit_id = t.id
                    break
            if hit_id is not None:
                track_hit_frames += 1
                if last_gt_id is not None and hit_id != last_gt_id:
                    id_switches += 1
                last_gt_id = hit_id
            # 已确认但不能对应真值的航迹 -> 虚警
            for t in confirmed:
                px, py = t.kf.statePost[0, 0], t.kf.statePost[1, 0]
                if math.hypot(px - gx, py - gy) > a.gate:
                    false_confirm += 1

        # ---- 画三格：原始 | 检测+航迹 | 二值 ----
        v1img = cv2.resize(frame, (hw, hh))
        canv = cv2.cvtColor(cv2.normalize(th, None, 0, 255, cv2.NORM_MINMAX), cv2.COLOR_GRAY2BGR)
        canv = cv2.resize(canv, (hw, hh), interpolation=cv2.INTER_NEAREST)
        for c in cands:                                   # 灰色小圈 = v1 的原始检测候选
            cv2.circle(canv, (int(c["x"] * a.down), int(c["y"] * a.down)), 6, (140, 140, 140), 1)
        for t in tracks:                                  # 绿色 = 已确认航迹（带 ID 和轨迹线）
            if not t.confirmed:
                continue
            pts = [(int(x * a.down), int(y * a.down)) for (x, y) in t.trail]
            for k in range(1, len(pts)):
                cv2.line(canv, pts[k - 1], pts[k], (0, 255, 0), 1)
            px = int(t.kf.statePost[0, 0] * a.down)
            py = int(t.kf.statePost[1, 0] * a.down)
            cv2.rectangle(canv, (px - 14, py - 14), (px + 14, py + 14), (0, 255, 0), 2)
            cv2.putText(canv, "ID" + str(t.id), (px + 16, py - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        if idx in gt:                                     # 黄色 = 真值
            cv2.circle(canv, (gt[idx][0], gt[idx][1]), 4, (0, 255, 255), 2)
        v3 = cv2.cvtColor(cv2.resize(binary, (hw, hh), interpolation=cv2.INTER_NEAREST), cv2.COLOR_GRAY2BGR)
        panel = np.hstack([v1img, canv, v3])
        assert panel.shape[0] == H_OUT and panel.shape[1] == W_OUT, "面板尺寸与写入器不一致！"
        for i, tag in enumerate(["1 Original", "2 Tracks(green)/Det(gray)/GT(yellow)", "3 Binary"]):
            cv2.putText(panel, tag, (10 + i * hw, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
        cv2.putText(panel, "f{} cands={} tracks={}".format(idx, len(cands), len(confirmed)),
                    (10, hh - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        vw.write(panel)

        rows.append([idx, (t1 - t0) * 1e3, (t2 - t1) * 1e3, (t2 - t0) * 1e3,
                     len(cands), len(confirmed), 1 if (idx in gt and any(
                         math.hypot(t.kf.statePost[0, 0] - gt[idx][0] / a.down,
                                    t.kf.statePost[1, 0] - gt[idx][1] / a.down) <= a.gate
                         for t in confirmed)) else 0])
        idx += 1

    t_total = time.perf_counter() - t_begin
    cap.release()
    vw.release()

    with open(a.csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["frame", "detect_ms", "track_ms", "frame_total_ms", "n_cand", "n_track", "gt_hit"])
        w.writerows(rows)
    if not rows:
        raise SystemExit("没有读到任何帧")

    arr = np.array([r[1:4] for r in rows], dtype=float)
    minutes = max(len(rows) / fps_in / 60.0, 1e-6)
    print("")
    print("===== v2 跟踪结果 =====")
    print("处理帧数        : {}".format(len(rows)))
    print("平均处理帧率    : {:.2f} fps".format(len(rows) / t_total))
    print("单帧总耗时      : 均值 {:.2f} ms | P95 {:.2f} ms".format(
        arr[:, 2].mean(), np.percentile(arr[:, 2], 95)))
    print("分阶段均值      : 检测(阈值+连通域) {:.2f} ms | 跟踪(预测+匹配+管理) {:.2f} ms".format(
        arr[:, 0].mean(), arr[:, 1].mean()))
    print("")
    print("---- 虚警抑制对比（关键）----")
    print("v1 原始候选     : 平均 {:.2f} 个/帧（总计 {} 个）".format(
        raw_cand_total / len(rows), raw_cand_total))
    print("v2 确认航迹     : 平均 {:.2f} 条/帧".format(confirmed_frames / len(rows)))
    print("v2 虚警次数     : {} 次 / {:.1f} 分钟  →  {:.1f} 次/分钟".format(
        false_confirm, minutes, false_confirm / minutes))
    if frames_with_gt:
        print("")
        print("---- 跟踪指标（对 {} 帧有真值的画面）----".format(frames_with_gt))
        print("跟踪成功率      : {:.1f} %  ({}/{})".format(
            100.0 * track_hit_frames / frames_with_gt, track_hit_frames, frames_with_gt))
        print("ID 切换次数     : {}".format(id_switches))
    print("")
    print("参数: 确认门限 {} 帧 | 匹配门限 {} px | 删除门限 {} 帧".format(a.confirm, a.gate, a.max_miss))
    print("输出视频        : {}".format(os.path.abspath(a.out)))
    print("逐帧数据        : {}".format(os.path.abspath(a.csv)))


if __name__ == "__main__":
    main()
