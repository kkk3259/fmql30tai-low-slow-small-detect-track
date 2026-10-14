# -*- coding: utf-8 -*-
"""
低小慢目标检测跟踪系统 —— 系统集成骨架（ps_app.py）

作用：把三个人的模块串成一条完整流水线。
      现在全部是 Python 实现（在 PC 上跑），板卡到货后按下面标了"★替换点"的地方
      逐段换成硬件模块，其它代码一行都不用改。

流水线（7 个处理环节，对应 5 个数据接口 I1~I5；其中 5 个环节可替换）：
  ① capture()   采集视频帧        -★- 将来: PS 的 V4L2(USB相机) / VPU(TF卡序列)
  ② detect()    检测(粗筛)        -★- 将来: PL 的 IP1+IP2  -> 输出候选列表 I2
  ③ crop_roi()  裁 128x128 图块   -★- 将来: PL 的 IP4      -> 输出 ROI 张量 I3
  ④ RoIJudge()  判别(精判)        -★- 将来: NPU 推理        -> 输出置信度 I4
  ⑤ Tracker()   跟踪与航迹管理     --  一直放 CPU（本文件，不替换）
  ⑥ render()    显示叠加          -★- 将来: HDMI 输出 / PL 的 OSD
  ⑦ report()    告警上报          --  串口 / UDP（JSON，本文件）

用法：
  python ps\\ps_app.py --src synth
  python ps\\ps_app.py --src D:\\lowslow\\data\\seq01.mp4 --out results\\app_demo.mp4
  python ps\\ps_app.py --src synth --no-classify        # 关掉判别（全部通过）
  python ps\\ps_app.py --src synth --model D:\\lowslow\\models\\roi_cnn.onnx   # 接 A 的模型
"""
import argparse
import csv
import json
import math
import os
import sys
import time

import cv2
import numpy as np

# ---- 让本文件能直接引用 baseline/ 下的算法实现（集成层的复用，不重复造轮子）----
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJ = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_PROJ, "baseline"))

from run import make_synthetic, to_gray_down, gauss, tophat          # noqa: E402
from detect_v1 import adaptive_threshold, extract_candidates          # noqa: E402
from track_v2 import Track, greedy_match                              # noqa: E402

ROI_SIZE = 128        # ROI 图块边长（I3 接口约定）
CONF_TH = 0.60        # 判别通过阈值（I4 接口约定）


# ================================================================ ① 采集
def capture_init(source):
    """★替换点1：板卡上换成 V4L2 取流（USB 相机）或 VPU 硬解（TF 卡序列）"""
    if source == "synth":
        source = os.path.join(_PROJ, "synth_sky.mp4")
        if not os.path.exists(source):
            make_synthetic(source)
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise SystemExit("打不开视频源：" + str(source))
    return cap, source


def capture_frame(cap):
    ok, frame = cap.read()
    return frame if ok else None


# ================================================================ ② 检测（粗筛）
class Detector(object):
    """★替换点2：板卡上换成"把帧通过 DMA 送给 PL，读回候选列表(I2)"

    现在：Python 版本（= 软件基线 v1 的检测链），输出格式与 I2 一致
    输出候选字段：x, y（降采样图坐标）, area, peak, conf
    """

    def __init__(self, down=2, gauss_k=0, tophat_se=5,
                 win=31, k=4.0, floor=3.0, min_area=2, max_area=200, topk=5,
                 temporal="none", n_acc=8, alpha=0.95, vel_x=0.0, vel_y=0.0):
        self.cfg = dict(down=down, gauss_k=gauss_k, tophat_se=tophat_se,
                        win=win, k=k, floor=floor,
                        min_area=min_area, max_area=max_area, topk=topk)
        # 时域增强（★将来对应 PL 的"帧缓存 + 时域累加"模块）
        self.enh = None
        if temporal != "none":
            from detect_v3 import TemporalEnhancer
            self.enh = TemporalEnhancer(mode=temporal, alpha=alpha, n_acc=n_acc,
                                        vel_x=vel_x, vel_y=vel_y)

    def __call__(self, frame):
        c = self.cfg
        gray = to_gray_down(frame, c["down"])
        if self.enh is not None:
            gray = self.enh(gray)                 # 时域增强（acc / mc / bg / tmax）
        g = gauss(gray, c["gauss_k"])
        th = tophat(g, c["tophat_se"])
        binary, _ = adaptive_threshold(th, c["win"], c["k"], c["floor"])
        cands = extract_candidates(binary, th, c["min_area"], c["max_area"], c["topk"])
        for cd in cands:
            cd["conf"] = 1.0          # 检测阶段先给 1.0，判别阶段会覆盖
        return cands, th, gray, binary


# ================================================================ ③ 裁 ROI
def crop_roi(gray, cx, cy, size=ROI_SIZE):
    """★替换点3：板卡上换成 PL 的 roi_pack(IP4)

    从降采样灰度图上裁 size×size 的图块（越界补 0），坐标是降采样图坐标。
    输出就对应接口 I3 的 roi_data（将来要改成 INT8 并加上量化参数）。
    """
    half = size // 2
    h, w = gray.shape[:2]
    x0, y0 = int(round(cx)) - half, int(round(cy)) - half
    x1, y1 = x0 + size, y0 + size
    pad_l, pad_t = max(0, -x0), max(0, -y0)
    pad_r, pad_b = max(0, x1 - w), max(0, y1 - h)
    x0c, y0c = max(0, x0), max(0, y0)
    x1c, y1c = min(w, x1), min(h, y1)
    roi = np.zeros((size, size), np.uint8)
    if x1c > x0c and y1c > y0c:
        roi[pad_t:pad_t + (y1c - y0c), pad_l:pad_l + (x1c - x0c)] = gray[y0c:y1c, x0c:x1c]
    return roi, (x0, y0)          # (offset_x, offset_y) 属于接口 I3


# ---------------------------------------------------------------- 判别后端（双平台）
# 2026-10-14：FMQL45T900（现在）无 NPU → 用 cpu/placeholder；FMQL30TAI（最终）→ 用 npu
# 用环境变量 ROIJUDGE_BACKEND 控制：auto / npu / cpu / placeholder
ROIJUDGE_BACKEND = os.environ.get("ROIJUDGE_BACKEND", "auto")


def detect_backend():
    """自动探测可用后端：优先 NPU，其次 CPU，最后占位"""
    if ROIJUDGE_BACKEND and ROIJUDGE_BACKEND.lower() != "auto":
        return ROIJUDGE_BACKEND.lower()
    # 自动：找 Icraft 运行时（仅 30TAI 有）
    try:
        import icraft  # noqa: F401
        return "npu"
    except Exception:
        pass
    # 其次：ONNX Runtime（45T900 上 CPU 推理用）
    try:
        import onnxruntime  # noqa: F401
        return "cpu"
    except Exception:
        return "placeholder"


# ================================================================ ④ 判别（精判）
class RoIJudge(object):
    """★替换点4：板卡上换成 NPU 推理（A 的 Icraft 模型）

    现在：
      - 没有模型时是"占位实现"，直接返回 1.0（等于全部通过，不丢检测结果）
      - 给了 ONNX 模型路径就用 onnxruntime 在 PC 上推理（先跑通链路）
    """

    def __init__(self, model_path=None, enabled=True):
        self.enabled = enabled
        self.sess = None
        self.input_name = None
        # ---- 双平台后端（初始化时探测一次，避免每帧 import 探测）----
        self.backend = detect_backend()
        if enabled and model_path and os.path.exists(model_path):
            try:
                import onnxruntime as ort
                self.sess = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
                self.input_name = self.sess.get_inputs()[0].name
                self.backend = "onnx"          # 有本地模型时优先用它
                print("[判别] 已加载模型: {}  (输入 {})".format(
                    os.path.basename(model_path), self.sess.get_inputs()[0].shape))
            except Exception as e:
                print("[判别] 模型加载失败，回退占位实现: {}".format(e))
                self.sess = None
        if self.sess is None:
            print("[判别] 后端 = {}（{}）".format(
                self.backend,
                {"npu": "30TAI / Icraft",
                 "cpu": "45T900 / ONNX Runtime（无模型时占位）",
                 "placeholder": "占位：全部通过"}.get(self.backend, self.backend)))

    def __call__(self, roi):
        """输入 ROI(灰度 uint8)，输出目标置信度 0~1（将来取自 I4）"""
        if not self.enabled:
            return 1.0                     # --no-classify：完全关掉判别（全部通过）
        if self.sess is None:
            # ---- 双平台后端分派（backend 在 __init__ 里探测并缓存，避免每帧 import）----
            backend = self.backend
            try:
                if backend == "npu":
                    # 30TAI：Icraft 推理（拿到板后替换此处）
                    return float(self._npu_infer(roi))            # ★替换点4 真实现
                elif backend in ("cpu", "onnx"):
                    # 45T900 / PC：CPU 推理（ONNX Runtime）
                    return float(self._cpu_infer(roi))
            except NotImplementedError as e:
                # 当前平台没有 NPU（如 FMQL45T900）→ 不崩，回退占位
                self.backend = "placeholder"
                print("[判别] 该平台无 NPU，回退占位：{}".format(e))
            except Exception as e:
                print("[判别] 后端 {} 推理失败，回退占位：{}".format(backend, e))
            return 1.0                                   # placeholder：全部通过

    def _npu_infer(self, roi):
        """30TAI：调用 Icraft 运行时（★ 拿到板后实现）"""
        raise NotImplementedError("30TAI 上接入 Icraft；当前平台无 NPU")

    def _cpu_infer(self, roi):
        """45T900 / PC：CPU 推理（ONNX Runtime）

        模型统一由 --model 参数传入（存于 self.sess）；
        没有模型时返回 1.0（占位），保证链路不中断。
        """
        if self.sess is None:
            return 1.0                     # 没模型 -> 占位（等价"全部通过"）
        try:
            import numpy as np
            x = roi.astype(np.float32) / 255.0
            if len(self.sess.get_inputs()[0].shape) == 4:
                x = x[None, None, :, :]    # NCHW 单通道
            logits = self.sess.run(None, {self.input_name: x})[0].ravel()
            if logits.size == 1:
                return float(1.0 / (1.0 + np.exp(-logits[0])))   # 单输出 -> sigmoid
            e = np.exp(logits - logits.max())
            return float((e / e.sum())[-1])                       # 多类 -> 最后一类
        except Exception as e:
            print("[判别] CPU 推理失败，回退占位: {}".format(e))
            return 1.0

        x = roi.astype(np.float32) / 255.0
        if len(self.sess.get_inputs()[0].shape) == 4:
            x = x[None, None, :, :]                      # NCHW, 单通道
        logits = self.sess.run(None, {self.input_name: x})[0].ravel()
        e = np.exp(logits - logits.max())
        return float((e / e.sum())[-1])                  # 最后一类 = 目标


# ================================================================ ⑤ 跟踪（一直放 CPU）
class Tracker(object):
    """就是 v2 的跟踪逻辑，封装成类，供主循环调用"""

    def __init__(self, gate=12.0, confirm=3, max_miss=15):
        self.gate = gate
        self.confirm = confirm
        self.max_miss = max_miss
        self.tracks = []

    def step(self, dets):
        preds = [t.predict() for t in self.tracks]
        pairs = greedy_match(preds, dets, self.gate)
        used_t, used_d = set(), set()
        for ti, di in pairs:
            self.tracks[ti].update(dets[di][0], dets[di][1], self.confirm)
            used_t.add(ti)
            used_d.add(di)
        for i, t in enumerate(self.tracks):
            if i not in used_t:
                t.miss += 1
        for j in range(len(dets)):
            if j not in used_d:
                self.tracks.append(Track(dets[j][0], dets[j][1], self.confirm))
        self.tracks = [t for t in self.tracks if t.miss <= self.max_miss]
        return [t for t in self.tracks if t.confirmed]


# ================================================================ ⑥ 显示
def render(frame, enhanced, cands, passed, tracks, gt, idx, down, stage_ms, mode):
    """★替换点5：板卡上换成 HDMI 输出（叠加可由 PL 的 OSD 完成）"""
    w_in = frame.shape[1]
    h_in = frame.shape[0]
    hw, hh = w_in // 2, h_in // 2

    left = cv2.resize(frame, (hw, hh))
    canv = cv2.cvtColor(cv2.normalize(enhanced, None, 0, 255, cv2.NORM_MINMAX), cv2.COLOR_GRAY2BGR)
    canv = cv2.resize(canv, (hw, hh), interpolation=cv2.INTER_NEAREST)

    for c in cands:                                        # 灰色 = 检测到但未通过判别
        if c.get("conf", 1.0) < CONF_TH:
            cv2.circle(canv, (int(c["x"] * down), int(c["y"] * down)), 6, (140, 140, 140), 1)
    for c in passed:                                       # 青色 = 通过判别的检测点
        cv2.circle(canv, (int(c["x"] * down), int(c["y"] * down)), 8, (255, 255, 0), 2)
    for t in tracks:                                       # 绿色 = 已确认航迹
        pts = [(int(x * down), int(y * down)) for (x, y) in t.trail]
        for k in range(1, len(pts)):
            cv2.line(canv, pts[k - 1], pts[k], (0, 255, 0), 1)
        px = int(t.kf.statePost[0, 0] * down)
        py = int(t.kf.statePost[1, 0] * down)
        cv2.rectangle(canv, (px - 14, py - 14), (px + 14, py + 14), (0, 255, 0), 2)
        cv2.putText(canv, "ID" + str(t.id), (px + 16, py - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    if gt is not None:
        cv2.circle(canv, (int(gt[0]), int(gt[1])), 4, (0, 255, 255), 2)  # 真值为 float，绘图需 int

    # 第三格：流水线状态面板（把每个环节的耗时摊出来，一眼看出瓶颈在哪）
    panel3 = np.zeros((hh, hw, 3), np.uint8)
    lines = [
        "pipeline status",
        "",
        "frame     : {}".format(idx),
        "mode      : {}".format(mode),
        "cands     : {}".format(len(cands)),
        "passed    : {}".format(len(passed)),
        "tracks    : {}".format(len(tracks)),
        "",
        "--- stage ms ---",
        "detect    : {:.2f}".format(stage_ms[0]),
        "roi+judge : {:.2f}".format(stage_ms[1]),
        "track     : {:.2f}".format(stage_ms[2]),
        "render    : {:.2f}".format(stage_ms[3]),
        "TOTAL     : {:.2f}".format(sum(stage_ms)),
    ]
    for i, s in enumerate(lines):
        cv2.putText(panel3, s, (14, 28 + i * 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (0, 255, 255) if s.startswith("---") or s.startswith("pipeline") else (200, 255, 200), 1)

    panel = np.hstack([left, canv, panel3])
    for i, tag in enumerate(["1 Original", "2 Detect(c gray)/RoI(c cyan)/Track(green)/GT(yellow)", "3 Pipeline"]):
        cv2.putText(panel, tag, (8 + i * hw, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)
    return panel


# ================================================================ ⑦ 上报
def report(frame_id, ts, tracks, fps=None, lat_ms=None, level_th=(0.6, 0.85)):
    """告警 JSON（每帧一行）。★将来走串口/USDUDP发给上位机"""
    if not tracks:
        return None
    t = tracks[0]
    px = float(t.kf.statePost[0, 0])
    py = float(t.kf.statePost[1, 0])
    vx = float(t.kf.statePost[2, 0])
    vy = float(t.kf.statePost[3, 0])
    conf = float(t.conf_last) if hasattr(t, "conf_last") else 1.0
    if conf >= level_th[1] and t.hits >= 10:
        lvl = "critical"
    elif conf >= level_th[0] and t.hits >= 3:
        lvl = "warn"
    else:
        lvl = "notice"
    rec = {"ts": round(ts, 3), "frame": frame_id, "fps": fps, "lat_ms": lat_ms,
           "alert": {"level": lvl, "track_id": t.id,
                     "bbox": [round(px - 14, 1), round(py - 14, 1), 28, 28],
                     "conf": round(conf, 2),
                     "speed_px_frame": round(math.hypot(vx, vy), 2),
                     "dir_deg": round(math.degrees(math.atan2(vy, vx)), 1),
                     "age_frames": t.hits}}
    return json.dumps(rec, ensure_ascii=False)


# ================================================================ 主循环
def main():
    ap = argparse.ArgumentParser(description="低小慢检测跟踪系统 · 集成骨架")
    ap.add_argument("--src", default="synth", help="视频源：synth 或视频文件路径")
    ap.add_argument("--out", default="results\\app_demo.mp4")
    ap.add_argument("--csv", default="results\\app_demo.csv")
    ap.add_argument("--json", default="results\\app_alerts.jsonl")
    ap.add_argument("--model", default="", help="ROI 判别模型 ONNX 路径（A 提供）")
    ap.add_argument("--no-classify", action="store_true", help="关掉判别环节（全部通过）")
    # ---- 时域增强（复用 detect_v3 的实现）----
    ap.add_argument("--temporal", default="none",
                    choices=["none", "acc", "mc", "bg", "tmax", "both"],
                    help="时域增强：none=关 / acc=多帧平均 / mc=运动补偿 / bg=背景差分 / tmax=时间TopHat")
    ap.add_argument("--n-acc", type=int, default=8, help="时域窗口帧数")
    ap.add_argument("--alpha", type=float, default=0.95, help="背景更新率（bg）")
    ap.add_argument("--vel-x", type=float, default=0.0, help="目标水平速度 px/帧（mc，降采样坐标）")
    ap.add_argument("--vel-y", type=float, default=0.0, help="目标垂直速度 px/帧（mc，降采样坐标）")
    ap.add_argument("--down", type=int, default=2)
    ap.add_argument("--k", type=float, default=4.0)
    ap.add_argument("--floor", type=float, default=3.0)
    ap.add_argument("--gate", type=float, default=12.0)
    ap.add_argument("--confirm", type=int, default=3)
    ap.add_argument("--max-frames", type=int, default=0)
    a = ap.parse_args()

    cv2.setNumThreads(1)

    # 真值（有则统计指标）
    gt = {}
    cap, src = capture_init(a.src)
    gtf = os.path.splitext(src)[0] + "_gt.csv"
    if os.path.exists(gtf):
        with open(gtf, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                gt[int(row["frame"])] = (float(row["x"]), float(row["y"]))  # 兼容带小数的真值
    print("[输入] {}  真值 {} 帧".format(src, len(gt)))

    fps_in = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w_in = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h_in = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    hw, hh = w_in // 2, h_in // 2
    W_OUT, H_OUT = hw * 3, hh
    vw = cv2.VideoWriter(a.out, cv2.VideoWriter_fourcc(*"mp4v"), fps_in, (W_OUT, H_OUT))
    if not vw.isOpened():
        raise SystemExit("输出视频写入器创建失败：" + a.out)

    detector = Detector(down=a.down, k=a.k, floor=a.floor,
                    temporal=a.temporal, n_acc=a.n_acc, alpha=a.alpha,
                    vel_x=a.vel_x, vel_y=a.vel_y)
    judge = RoIJudge(model_path=a.model, enabled=not a.no_classify)
    tracker = Tracker(gate=a.gate, confirm=a.confirm)
    mode = "python(占位判别)" if judge.sess is None else "python(ONNX判别)"

    rows, alert_lines = [], []
    stage_sum = np.zeros(4)
    idx, nb = 0, 0
    hit_frames = gt_frames = 0
    raw_cand_total = 0
    t_begin = time.perf_counter()

    while True:
        frame = capture_frame(cap)
        if frame is None or (a.max_frames and idx >= a.max_frames):
            break
        t0 = time.perf_counter()
        cands, enhanced, gray, binary = detector(frame)                 # ② 检测
        t1 = time.perf_counter()
        dets, passed = [], []
        for c in cands:                                                 # ③ 裁 ROI + ④ 判别
            roi, off = crop_roi(gray, c["x"], c["y"])
            c["conf"] = judge(roi)
            if c["conf"] >= CONF_TH:
                dets.append((c["x"], c["y"]))
                passed.append(c)
        t2 = time.perf_counter()
        tracks = tracker.step(dets)                                     # ⑤ 跟踪
        for t in tracks:
            t.conf_last = 1.0
        t3 = time.perf_counter()
        gt_now = gt.get(idx)
        panel = render(frame, enhanced, cands, passed, tracks, gt_now, idx,
                       a.down, (t1 - t0, t2 - t1, t3 - t2, 0.0), mode)   # ⑥ 显示
        vw.write(panel)
        t4 = time.perf_counter()

        raw_cand_total += len(cands)
        if gt_now is not None:
            gt_frames += 1
            gx, gy = gt_now[0] / a.down, gt_now[1] / a.down
            if any(math.hypot(t.kf.statePost[0, 0] - gx, t.kf.statePost[1, 0] - gy) <= a.gate
                   for t in tracks):
                hit_frames += 1

        js = report(idx, time.time(), tracks, fps=None, lat_ms=None)     # ⑦ 上报
        if js:
            alert_lines.append(js)
            nb += 1

        stage_sum += np.array([(t1 - t0) * 1e3, (t2 - t1) * 1e3, (t3 - t2) * 1e3, (t4 - t3) * 1e3])
        rows.append([idx, (t1 - t0) * 1e3, (t2 - t1) * 1e3, (t3 - t2) * 1e3, (t4 - t3) * 1e3,
                     (t4 - t0) * 1e3, len(cands), len(passed), len(tracks)])
        idx += 1

    t_total = time.perf_counter() - t_begin
    cap.release()
    vw.release()

    with open(a.csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["frame", "detect_ms", "roi_judge_ms", "track_ms", "render_ms",
                    "frame_total_ms", "n_cand", "n_passed", "n_track"])
        w.writerows(rows)
    with open(a.json, "w", encoding="utf-8") as f:
        f.write("\n".join(alert_lines))

    if not rows:
        raise SystemExit("没有读到任何帧")
    n = len(rows)
    print("")
    print("===== 集成骨架运行结果 =====")
    print("模式            : {}".format(mode))
    print("处理帧数        : {}".format(n))
    print("端到端帧率      : {:.2f} fps".format(n / t_total))
    print("单帧总耗时      : 均值 {:.2f} ms".format(sum(r[5] for r in rows) / n))
    print("")
    print("---- 各环节平均耗时（7 个处理环节）----")
    names = ["② 检测 detect", "③④ 裁ROI+判别", "⑤ 跟踪 track", "⑥ 显示 render"]
    for nm, v in zip(names, stage_sum / n):
        print("  {:<16s} {:.2f} ms".format(nm, v))
    print("")
    print("---- 链路统计 ----")
    print("  检测候选总数    : {}（平均 {:.2f}/帧）".format(raw_cand_total, raw_cand_total / n))
    print("  判别通过数      : 见 CSV 的 n_passed 列（占位判别时 = 候选数）")
    print("  告警条数        : {} 条（写入 {}）".format(nb, os.path.abspath(a.json)))
    if gt_frames:
        print("  跟踪成功率      : {:.1f} %  ({}/{})".format(100.0 * hit_frames / gt_frames, hit_frames, gt_frames))
    print("")
    print("输出视频        : {}".format(os.path.abspath(a.out)))
    print("逐帧数据        : {}".format(os.path.abspath(a.csv)))
    print("")
    print("提示：7 个环节中 ①采集/②检测/③裁ROI/④判别/⑥显示 可替换（=★替换点1~5，是 P 和 A 的接入位置）；⑤跟踪/⑦上报 固定放 CPU。")


if __name__ == "__main__":
    main()
