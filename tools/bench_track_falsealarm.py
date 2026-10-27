# -*- coding: utf-8 -*-
"""跟踪压虚警实验（PC 端，不需要板子）

问题：CFAR 每帧给出几十~上百个候选，其中真目标约 1 个。
      PS 侧卡尔曼 + N 帧航迹确认，能把虚警压到多少？

方法：真实 1080P 图当背景（有云/地物 → 自然纹理），
      合成一个 5px 亮点按 0.8 px/帧缓慢移动，跑 300 帧。

实测结论（2026-10-27）：
  confirm=1（逐帧）  : 原始候选 64.0 → 确认航迹 64.01，虚警 63.01
  confirm=3（三帧确认）: 原始候选 64.0 → 确认航迹 63.58，虚警 62.59
  confirm=5          : 原始候选 64.0 → 确认航迹 63.15，虚警 62.16

  ⇒ 三帧确认只把虚警从 63.01 压到 62.59（降 0.7%），几乎无效。

根因：背景是静止的，CFAR 虚警每帧出现在同一位置（云边缘、建筑纹理），
      卡尔曼能完美预测 → 完美匹配 → 连续命中 → 被确认为真目标。
      跟踪只能压掉"跳动的虚警"，压不掉"静止的纹理虚警"。

⇒ 架构含义：静止纹理虚警必须由 NPU 判别环节处理（CNN 能学形状/纹理），
            跟踪只是关联航迹，不是去虚警的主力。

注意：本实验背景完全静止，是极端情况。真实摄像头有抖动，虚警不会那么"完美静止"，
      所以真实场景下跟踪能压掉一部分。但静止的那部分依然压不掉。

用法：
  python tools/bench_track_falsealarm.py
  python tools/bench_track_falsealarm.py --frames 500 --step 1.2 --confirm 3
"""
import os, sys, csv, argparse, numpy as np, cv2

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(REPO, "deploy", "eval_roi_448")
sys.path.insert(0, os.path.join(REPO, "baseline"))

from detect_v1 import adaptive_threshold, extract_candidates
from track_v2 import Track, greedy_match


def imread_cn(path):
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


def build_sequence(n_frame, step_px, radius, tier="15-35px"):
    """取一张真实图当背景，合成一个缓慢移动的亮点"""
    with open(os.path.join(BASE, "manifest.csv"), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    bg = None
    for r in rows:
        if r["尺寸档"] == tier:
            img = imread_cn(os.path.join(BASE, "images", r["文件"]))
            if img is not None:
                bg, name = img, r["文件"]
                break
    if bg is None:
        raise RuntimeError("找不到可用背景图")
    H, W = bg.shape[:2]
    x0, y0 = W * 0.25, H * 0.65
    vx, vy = step_px * 0.8, -step_px * 0.6

    def render(t):
        fr = bg.copy()
        cx, cy = int(x0 + vx * t), int(y0 + vy * t)
        if 0 <= cx < W and 0 <= cy < H:
            cv2.circle(fr, (cx, cy), int(radius), (230, 230, 230), -1)
            cv2.circle(fr, (cx, cy), 1, (255, 255, 255), -1)
            return fr, (cx, cy)
        return fr, None

    return render, name, (W, H)


def make_detect(down=2, win=31, k=4.0, floor=3.0, se=5, topk=64,
                mode="top", merge_r=8):
    """返回一个 detect(frame) -> [(x, y, area)]，坐标已回到原图尺度"""
    k5 = cv2.getStructuringElement(cv2.MORPH_RECT, (se, se))

    def detect(frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        g = gray[::down, ::down] if down > 1 else gray
        top = cv2.morphologyEx(g, cv2.MORPH_TOPHAT, k5)
        cs = []
        enh_list = []
        if mode in ("top", "dual"):
            enh_list.append(top)
        if mode in ("black", "dual"):
            enh_list.append(cv2.morphologyEx(g, cv2.MORPH_BLACKHAT, k5))
        for enh in enh_list:
            binary, _ = adaptive_threshold(enh, win, k, floor)
            cs += extract_candidates(binary, enh, 2, 200, topk)
        if mode == "dual":
            cs.sort(key=lambda c: -c["peak"])
            kept = []
            for c in cs:
                if all((c["x"]-o["x"])**2 + (c["y"]-o["y"])**2 > merge_r**2 for o in kept):
                    kept.append(c)
            cs = kept
        return [(c["x"] * down, c["y"] * down, c["area"]) for c in cs]

    return detect


def run(render, n_frame, detect, confirm_hits, gate=12.0, max_miss=15, tol=16):
    tracks = []
    raw = conf_sum = true_hit = false_conf = 0
    for t in range(n_frame):
        fr, gt = render(t)
        dets = detect(fr)
        raw += len(dets)

        preds = [tk.predict() for tk in tracks]
        pairs = greedy_match(preds, dets, gate)
        used = set()
        for ti, di in pairs:
            tracks[ti].update(dets[di][0], dets[di][1], confirm_hits)
            used.add(di)
        for j in range(len(dets)):
            if j not in used:
                tracks.append(Track(dets[j][0], dets[j][1], confirm_hits))
        for tk in tracks:
            tk.miss += 1
        tracks = [tk for tk in tracks if tk.miss <= max_miss]

        conf = [tk for tk in tracks if tk.confirmed]
        conf_sum += len(conf)
        if gt is not None:
            # Track 没有 .x 属性，最新位置在 trail[-1]
            near = [tk for tk in conf
                    if abs(tk.trail[-1][0] - gt[0]) <= tol and abs(tk.trail[-1][1] - gt[1]) <= tol]
            if near:
                true_hit += 1
            false_conf += len(conf) - len(near)

    m = float(n_frame)
    return dict(raw=raw/m, conf=conf_sum/m, pd=true_hit/m*100, fa=false_conf/m)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=300)
    ap.add_argument("--step", type=float, default=0.8, help="目标每帧移动像素")
    ap.add_argument("--radius", type=float, default=2.5, help="目标半径（直径≈5px）")
    ap.add_argument("--topk", type=int, default=64)
    ap.add_argument("--mode", default="top", choices=["top", "black", "dual"])
    a = ap.parse_args()

    render, name, (W, H) = build_sequence(a.frames, a.step, a.radius)
    print("  背景 %s  %dx%d   %d 帧  目标 %.1f px/帧" % (name, W, H, a.frames, a.step))

    detect = make_detect(topk=a.topk, mode=a.mode)
    print("  检测模式 %s，topk=%d" % (a.mode, a.topk))
    print()
    print("  %-9s %12s %12s %12s %12s"
          % ("confirm", "原始候选/帧", "确认航迹/帧", "真目标命中%", "虚警航迹/帧"))
    for c in (1, 3, 5):
        r = run(render, a.frames, detect, c)
        print("  %-9d %12.1f %12.2f %12.1f %12.2f"
              % (c, r["raw"], r["conf"], r["pd"], r["fa"]))

    print()
    print("  结论：三帧确认对【静止纹理虚警】基本无效（背景不变 → 虚警位置不变 →")
    print("        卡尔曼完美匹配 → 连续命中 → 被确认）。")
    print("        静止虚警需由 NPU 判别环节处理，跟踪只负责航迹关联。")


if __name__ == "__main__":
    main()