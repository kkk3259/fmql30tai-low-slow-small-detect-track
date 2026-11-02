#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""offline_roi_vid.py —— 视频走「PL 粗筛 + NPU ROI 精判」离线出结果。

与 cam3d_pipe --mode roi 完全同一条链路：
  帧→640×360 灰度 → PL3D.run() 出候选 → 每候选裁 96×96 → 4×4 拼 640×640
  → yolo11n 一次 forward → 每 slot 取最高分映射回整帧 → 过滤 ROI_CONF → 画框

用法：offline_roi_vid.py <in.mp4> <out.mp4> [max_frames]
"""
import subprocess
import sys

import cv2
import numpy as np
sys.path.insert(0, "/root/ip2")
from cam3d_test import PL3D  # noqa: E402
from yolo_det import Yolo   # noqa: E402

W, H = 640, 360
# ROI 边长可调：目标只有 10 px 时，96 的裁剪放大 1.67× 仍不够，改 32 得到 5×
ROI_SIDE = int(__import__("os").environ.get("ROI_SIDE", "96"))
ROI_CELL, ROI_CONF = 4, 0.45
RECHECK_CONF = 0.20      # 保护区重检的放宽阈值
RECHECK_HITS = 6         # 连续命中这么多帧后，丢失时触发重检
INVERT = int(__import__("os").environ.get("INVERT", "1"))   # 默认取反：亮天空里的暗鸟
# PL 的列坐标有固定相位偏移（实测 x_true = x_det + 62），不补正 ROI 会裁到目标旁边
X_SHIFT = int(__import__("os").environ.get("X_SHIFT", "62"))
DUAL = int(__import__("os").environ.get("DUAL", "1"))



class _Trk(object):
    """极简航迹：距离关联 + EMA 平滑 + 短暂保持。"""

    R = 46.0        # 关联半径
    A = 0.35        # EMA 系数（新值权重）
    MISS = 4        # 允许丢帧数

    def __init__(self):
        self.t = []

    def update(self, dets):
        for d in dets:
            best, bd = None, 1e9
            for k in self.t:
                dd = ((d["x"] - k["x"]) ** 2 + (d["y"] - k["y"]) ** 2) ** 0.5
                if dd < bd:
                    best, bd = k, dd
            if best is not None and bd <= self.R:
                best["x"] = (1 - self.A) * best["x"] + self.A * d["x"]
                best["y"] = (1 - self.A) * best["y"] + self.A * d["y"]
                best["w"] = (1 - self.A) * best["w"] + self.A * d["w"]
                best["h"] = (1 - self.A) * best["h"] + self.A * d["h"]
                best["p"] = max(best["p"], d["p"])
                best["miss"] = 0
                best["live"] = 1
                best["hits"] = best.get("hits", 0) + 1
            else:
                self.t.append({"x": d["x"], "y": d["y"], "w": d["w"], "h": d["h"],
                                "p": d["p"], "miss": 0, "live": 1, "hits": 1})
        for k in self.t:
            if not k.get("live"):
                k["miss"] += 1
            k["live"] = 0
        self.t = [k for k in self.t if k["miss"] <= self.MISS]
        return [{"x": k["x"], "y": k["y"], "w": k["w"], "h": k["h"],
                 "p": k["p"], "roi": 1} for k in self.t if k["miss"] <= self.MISS]


def aa_rect(img, x1, y1, x2, y2, col, th=3):
    """抗锯齿矩形：cv2.rectangle 不支持 LINE_AA，用 4 条线拼。"""
    cv2.line(img, (x1, y1), (x2, y1), col, th, cv2.LINE_AA)
    cv2.line(img, (x2, y1), (x2, y2), col, th, cv2.LINE_AA)
    cv2.line(img, (x2, y2), (x1, y2), col, th, cv2.LINE_AA)
    cv2.line(img, (x1, y2), (x1, y1), col, th, cv2.LINE_AA)

def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "/root/bird.mp4"
    dst = sys.argv[2] if len(sys.argv) > 2 else "/root/roi_bird.mp4"
    maxn = int(sys.argv[3]) if len(sys.argv) > 3 else 300

    pl = PL3D()
    y = Yolo(dev=pl.dev)
    print("PL3D + Yolo ready (shared dev)", flush=True)

    cap = cv2.VideoCapture(src)
    ow = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    oh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    ff = ("ffmpeg -y -f rawvideo -pix_fmt bgr24 -s %dx%d -r 15 -i - "
          "-c:v libx264 -crf 18 -pix_fmt yuv420p %s" % (ow, oh, dst))
    proc = subprocess.Popen(ff.split(), stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    _TRK = _Trk()
    n = tot_pl = tot_hit = 0
    while n < maxn:
        ok, frame = cap.read()
        if not ok:
            break
        vis = frame.copy()
        gray = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (W, H),
                          interpolation=cv2.INTER_AREA)
        # PL 只认亮目标：暗目标（亮天空里的鸟）必须先取反
        if INVERT:
            gray = 255 - gray
        cands, st, dt = pl.run(gray)
        # 双极性：每 2 帧跑一次取反，合并候选（间距>12px 才加入）
        if DUAL and (n % 2 == 0):
            c2, _s2, dt2 = pl.run(255 - gray)
            dt += dt2
            for c in c2:
                if all(abs(c["x"] - k["x"]) + abs(c["y"] - k["y"]) > 12 for k in cands):
                    cands.append(c)
        keep = [c for c in cands if c["area"] >= 4 and c["peak"] >= 8
                and 8 <= c["y"] < H - 8 and 8 <= c["x"] < W - 8]
        for c in keep:
            c["x"] = (c["x"] + X_SHIFT) % W        # 补列相位偏移
        # 【2026-11-02】按中心距聚类：距离过近的 PL 候选直接合成一个（不看到重叠率）
        def _cluster(cs):
            groups = []
            for c in sorted(cs, key=lambda z: -z["peak"]):
                r = min(40.0, max(14.0, 2.5 * (c["area"] ** 0.5)))
                hit = None
                for g in groups:
                    if ((c["x"] - g["x"]) ** 2 + (c["y"] - g["y"]) ** 2) ** 0.5 <= r:
                        hit = g
                        break
                if hit is None:
                    groups.append({"x": float(c["x"]), "y": float(c["y"]),
                                   "area": c["area"], "peak": c["peak"], "_n": 1})
                else:
                    n = hit["_n"]
                    hit["x"] = (hit["x"] * n + c["x"]) / (n + 1)
                    hit["y"] = (hit["y"] * n + c["y"]) / (n + 1)
                    hit["area"] = max(hit["area"], c["area"])
                    hit["peak"] = max(hit["peak"], c["peak"])
                    hit["_n"] = n + 1
            return groups

        clusters = _cluster(keep)
        clusters.sort(key=lambda g: -g["peak"])
        cin = clusters[:ROI_CELL * ROI_CELL]
        fused = []
        if cin:
            crops, meta = [], []
            for c in cin:
                # 【2026-11-02】按目标面积放大裁剪窗，让 NPU 在更大的上下文里找目标并给出自己的框
                _side = int(min(max(ROI_SIDE, 3.0 * (c["area"] ** 0.5)), 128))
                hx = _side // 2
                x0 = int(min(max(c["x"] - hx, 0), max(0, W - _side)))
                y0 = int(min(max(c["y"] - hx, 0), max(0, H - _side)))
                crops.append(gray[y0:y0 + _side, x0:x0 + _side].copy())
                meta.append((x0, y0, _side))
            res = y.detect_mosaic(crops, grid=ROI_CELL)
            best = {}
            for slot, x1, y1, x2, y2, sc in res:
                if slot >= len(meta):
                    continue
                if slot not in best or sc > best[slot][4]:
                    best[slot] = (x1, y1, x2, y2, sc)
            for i, c in enumerate(cin):
                if i in best:
                    x1, y1, x2, y2, sc = best[i]
                    x0, y0, sd = meta[i]
                    fused.append({"x": x0 + (x1 + x2) / 2, "y": y0 + (y1 + y2) / 2,
                                  "w": x2 - x1, "h": y2 - y1, "p": float(sc), "roi": 1})
                else:
                    fused.append({"x": c["x"], "y": c["y"], "w": 14, "h": 14,
                                  "p": 0.0, "roi": 0})
        # 【2026-11-02】命中框合并：两框交集 >= 较小框面积的 80% 就合成一个（取并集）
        raw_hit = [c for c in fused if c["roi"] and c["p"] >= ROI_CONF]
        raw_hit.sort(key=lambda z: -z["p"])
        hit = []
        for c in raw_hit:
            ax1, ay1 = c["x"] - c["w"] / 2, c["y"] - c["h"] / 2
            ax2, ay2 = c["x"] + c["w"] / 2, c["y"] + c["h"] / 2
            merged = False
            for m in hit:
                bx1, by1 = m["x"] - m["w"] / 2, m["y"] - m["h"] / 2
                bx2, by2 = m["x"] + m["w"] / 2, m["y"] + m["h"] / 2
                iw = min(ax2, bx2) - max(ax1, bx1)
                ih = min(ay2, by2) - max(ay1, by1)
                if iw <= 0 or ih <= 0:
                    continue
                inter = iw * ih
                smaller = min(c["w"] * c["h"], m["w"] * m["h"])
                if smaller > 0 and inter / smaller >= 0.50:
                    ux1, uy1 = min(ax1, bx1), min(ay1, by1)
                    ux2, uy2 = max(ax2, bx2), max(ay2, by2)
                    m["x"], m["y"] = (ux1 + ux2) / 2, (uy1 + uy2) / 2
                    m["w"], m["h"] = ux2 - ux1, uy2 - uy1
                    m["p"] = max(m["p"], c["p"])
                    merged = True
                    break
            if not merged:
                hit.append(dict(c))
        # 被命中框覆盖的 PL-only 小框不再重复画
        def _inside(o, m):
            return (abs(o["x"] - m["x"]) < m["w"] / 2 and abs(o["y"] - m["y"]) < m["h"] / 2)
        # 【2026-11-02】保护区重检：已确认过、本帧突然丢失的航迹，
        # 用低阈值在预测位置再判一次，避免"识别到一半突然没了"
        lost = [k for k in _TRK.t
                if k.get("miss", 0) >= 1 and k.get("hits", 0) >= RECHECK_HITS]
        if lost:
            rc, rm = [], []
            for k in lost[:ROI_CELL * ROI_CELL]:
                _sd = 128
                hx = _sd // 2
                x0 = int(min(max(k["x"] - hx, 0), max(0, W - _sd)))
                y0 = int(min(max(k["y"] - hx, 0), max(0, H - _sd)))
                rc.append(gray[y0:y0 + _sd, x0:x0 + _sd].copy())
                rm.append((x0, y0, k))
            if rc:
                rres = y.detect_mosaic(rc, grid=ROI_CELL, conf=RECHECK_CONF)
                for slot, x1, y1, x2, y2, sc in rres:
                    if slot >= len(rm):
                        continue
                    x0, y0, k = rm[slot]
                    hit.append({"x": x0 + (x1 + x2) / 2, "y": y0 + (y1 + y2) / 2,
                                "w": x2 - x1, "h": y2 - y1,
                                "p": float(sc), "roi": 1, "recheck": 1})
        fused = _TRK.update(hit) if hit else _TRK.update([])
        # PL-only 候选画淡框（不再隐藏，让 PL 的工作可见）
        fused = fused + [c for c in (locals().get("fused") or []) if False]
        if cin:
            for c in cin:
                if not any(_inside(c, m) for m in fused):
                    fused.append({"x": c["x"], "y": c["y"], "w": 14, "h": 14,
                                  "p": 0.0, "roi": 0})
        # 保护区重检救回来的帧，在 HUD 上体现
        n_re = sum(1 for c in hit if c.get("recheck"))
        tot_pl += len(cands)
        tot_hit += len(hit)
        sx, sy = ow / float(W), oh / float(H)
        for c in fused:
            cx, cy = c["x"] * sx, c["y"] * sy
            hw, hh = max(8.0, c["w"] * sx / 2), max(8.0, c["h"] * sy / 2)
            if c["roi"] and c["p"] >= ROI_CONF:
                col, lab = (80, 230, 60), "%.0f%%" % (c["p"] * 100)
            elif c["roi"]:
                col, lab = (40, 150, 240), "%.0f%%" % (c["p"] * 100)
            else:
                col, lab = (168, 168, 168), ""
            _th = 1 if (not c["roi"]) else 2
            aa_rect(vis, int(cx - hw), int(cy - hh), int(cx + hw), int(cy + hh), col, 3 if c["roi"] else 1)
            if c["roi"]:
                cv2.putText(vis, lab, (int(cx - hw), max(14, int(cy - hh) - 5)), 0, 0.75, col, 2, cv2.LINE_AA)
        cv2.putText(vis, "roi f%d  PL=%d  hit=%d  re=%d" % (n, len(cands), len(hit), n_re),
                    (10, 32), 0, 0.9, (0, 235, 255), 2)
        proc.stdin.write(vis.tobytes())
        n += 1
        if n % 30 == 0:
            print("  %d frames  PL/f=%.1f hit/f=%.2f" % (n, tot_pl / n, tot_hit / n), flush=True)
    proc.stdin.close()
    proc.wait()
    print("ROIVID done %d frames PL/f=%.1f hit/f=%.2f -> %s"
          % (n, tot_pl / max(1, n), tot_hit / max(1, n), dst))


if __name__ == "__main__":
    main()
