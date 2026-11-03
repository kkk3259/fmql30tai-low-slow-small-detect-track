#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全流程：视频/摄像头 → PL 找目标 → NPU 判「是不是无人机」→ 画框输出

三种用法
--------
  # 1) 离线视频，出 mp4（推荐先验这个）
  python3 full_pipeline.py --video /root/bird.mp4 --out /root/full.mp4

  # 2) 实时摄像头 + 网页
  python3 full_pipeline.py --cam 0 --web 8080

  # 3) 只跑 PL（不接 NPU），用来对比
  python3 full_pipeline.py --video x.mp4 --out y.mp4 --npu 0

后端
----
  --backend pl   三域位流（PL DDR + 平台寄存器 0x400C0000 + AI_Mate 在）
  --backend ps   独立检测器位流（PS DDR udmabuf + 寄存器 0x43C00000，NPU 不可用）
  --backend auto 先试 pl，失败退回 ps

判真阈值
--------
  --thr 0.5     NPU 正类概率 ≥ 阈值才算「无人机」
  --only-drone  只画判定为无人机的框（默认两者都画，只是标签不同）
"""
import argparse
import json
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

W, H = 640, 360


# ---------------------------------------------------------------- PL 后端
class BackendPL(object):
    """三域位流：帧放 PL DDR，寄存器走平台窗口。"""

    name = "pl"

    def __init__(self):
        import detect3d
        self.det = detect3d.Det3D(w=W, h=H)

    def run(self, gray):
        st, cands, dt = self.det.detect(gray)
        return st, cands, dt

    def close(self):
        pass


class BackendPS(object):
    """独立检测器位流：帧放 PS DDR(udmabuf)，寄存器 0x43C00000。"""

    name = "ps"

    def __init__(self):
        import cam_pipe as cp
        self.cp = cp
        self.hw = cp.HW()

    def run(self, gray):
        return self.hw.run(gray)

    def close(self):
        pass


def make_backend(which):
    if which == "pl":
        return BackendPL()
    if which == "ps":
        return BackendPS()
    try:
        b = BackendPL()
        print("[backend] 用三域位流")
        return b
    except Exception as e:
        print("[backend] 三域不可用（%s），退回独立位流" % e)
        return BackendPS()


# ---------------------------------------------------------------- NPU
def make_classifier():
    import cascade
    clf = cascade.Classifier()
    print("[npu] 模型已加载:", os.path.basename(cascade.RAW))
    return clf


def classify(clf, gray, cands, side=128, zoom=1.4):
    """给每个候选裁一块送 NPU，返回 [{x,y,area,peak,p}]"""
    import cascade
    out = []
    for c in cands:
        x, y = int(c["x"]), int(c["y"])
        s = max(8, int(round(np.sqrt(max(1, c["area"])))))
        patch = cascade.crop_box(gray, x, y, side=int(s * zoom), out=side)
        try:
            p = clf.predict(patch)
            prob = float(p[0])
        except Exception as e:
            prob = -1.0
            if len(out) == 0:
                print("[npu] 推理失败:", e)
        d = dict(c)
        d["p"] = prob
        out.append(d)
    return out


# ---------------------------------------------------------------- 画框
def draw(img, cands, thr, only_drone=False):
    n_pos = 0
    for c in cands:
        x, y = int(c["x"]), int(c["y"])
        s = max(8, int(round(np.sqrt(max(1, c["area"])))))
        prob = c.get("p", -1.0)
        if prob < 0:
            col, lab = (128, 128, 128), "?"
        elif prob >= thr:
            col, lab = (0, 255, 0), "DRONE %.2f" % prob
            n_pos += 1
        else:
            col = (0, 0, 255)
            lab = "no %.2f" % prob
            if only_drone:
                continue
        cv2.rectangle(img, (x - s, y - s), (x + s, y + s), col, 2)
        cv2.putText(img, lab, (x + s + 3, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, 1, cv2.LINE_AA)
    return n_pos


def hud(img, txt):
    cv2.putText(img, txt, (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)


# ---------------------------------------------------------------- 主流程
def run_video(args):
    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        print("打不开视频", args.video)
        return 1
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    fps_in = cap.get(cv2.CAP_PROP_FPS) or 30.0

    be = make_backend(args.backend)
    clf = make_classifier() if args.npu else None

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    vw = None
    i = 0
    t0 = time.time()
    t_pl = t_npu = 0.0
    tot_pos = 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        i += 1
        big = fr.copy()                                   # 原分辨率用来画框
        gray = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
        if gray.shape[:2] != (H, W):
            gray = cv2.resize(gray, (W, H), interpolation=cv2.INTER_AREA)

        t = time.time()
        st, cands, dt = be.run(gray)
        t_pl += time.time() - t

        if clf is not None and cands:
            t = time.time()
            cands = classify(clf, gray, cands)
            t_npu += time.time() - t
            n_pos = draw(big, cands, args.thr, args.only_drone)
            tot_pos += n_pos
            tag = "frame %d/%d  PL %.1fms  NPU %d  pos %d" % (
                i, n, dt, len(cands), n_pos)
        else:
            draw(big, cands, 1.0, False)
            tag = "frame %d/%d  PL %.1fms  cand %d" % (i, n, dt, len(cands))
        hud(big, tag)

        if vw is None:
            h2, w2 = big.shape[:2]
            OW = args.outw or w2
            OH = int(round(h2 * OW / float(w2)))
            vw = cv2.VideoWriter(args.out, fourcc, fps_in, (OW, OH))
            print("输出 %s  %dx%d" % (args.out, OW, OH))
        vw.write(big if big.shape[1] == OW else cv2.resize(big, (OW, OH)))

        if i % 30 == 0:
            print("  %d/%d  PL均 %.1fms  NPU均 %.1fms" % (i, n, 1000 * t_pl / i, 1000 * t_npu / max(1, i)))
    cap.release()
    if vw:
        vw.release()
    be.close()
    print("完成：%d 帧，总耗时 %.1fs，平均 PL %.1fms，平均 NPU %.1fms/帧，判正共 %d 个" % (
        i, time.time() - t0, 1000 * t_pl / max(1, i), 1000 * t_npu / max(1, i), tot_pos))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", default="")
    ap.add_argument("--cam", type=int, default=-1)
    ap.add_argument("--out", default="/root/full.mp4")
    ap.add_argument("--web", type=int, default=0, help=">0 时开网页端口（实时模式）")
    ap.add_argument("--backend", default="auto", choices=["auto", "pl", "ps"])
    ap.add_argument("--npu", type=int, default=1)
    ap.add_argument("--thr", type=float, default=0.5)
    ap.add_argument("--only-drone", action="store_true")
    ap.add_argument("--outw", type=int, default=0, help="输出宽度，0=原宽")
    args = ap.parse_args()

    if args.video:
        return run_video(args)
    print("实时模式暂未实装（先用 --video 跑离线）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
