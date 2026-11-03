# -*- coding: utf-8 -*-
"""最终版离线检测管线（所有已验证的改动整合，去掉失败的取舍）。

包含：
  ① 空间分散选候选（间距 ≥40px）
  ② 中心距聚类（r = clamp(2.5√area, 14, 40)）
  ③ 放大裁剪窗（clamp(3√area, 96, 128)）
  ④ mosaic 一次判 16 个
  ⑤ IoU>0.25 合并（取代包含度判据）
  ⑥ EMA 平滑（A=0.35）+ 丢帧保持（MISS=4）
  ⑦ 保护区重检（CONF 0.45→0.20，仅丢失帧触发）
  ⑧ 抗锯齿画框（3px，PL-only 灰框 1px）
  ⑨ 解耦：画面线程 / 检测线程独立

不包含（已否决）：
   速度外推（检测间隔不稳，速度噪声大，框会飞出去）
   NEAREST 缩放（漏小目标）
   按包含度合并（对部分重叠无效）

用法：offline_final.py <in.mp4> <out.mp4> [maxn]
"""
import subprocess
import sys
import threading
import time

import cv2
import numpy as np

sys.path.insert(0, "/root/ip2")
from cam3d_test import PL3D          # noqa: E402
from yolo_det import Yolo            # noqa: E402

W, H = 640, 360
OUT_W, OUT_H = 640, 360
ROI_SIDE, ROI_CELL, ROI_CONF = 96, 4, 0.45
ROI_N = ROI_CELL * ROI_CELL
X_SHIFT = 64
RECHECK_CONF, RECHECK_HITS = 0.20, 6
MIND_PX = 40.0
EMA_A, TRK_R, MISS_MAX = 0.35, 46.0, 4

FRAME = [None]
BOXES = [[]]
DET_CNT = [0]
DET_T = [0.0]
RUN = [True]


def aa_rect(img, x1, y1, x2, y2, col, th=3):
    for (a, b) in (((x1, y1), (x2, y1)), ((x2, y1), (x2, y2)),
                   ((x2, y2), (x1, y2)), ((x1, y2), (x1, y1))):
        cv2.line(img, a, b, col, th, cv2.LINE_AA)


def pick_spread(cs, k, mind=MIND_PX):
    """按 peak 降序贪心，彼此中心距 ≥ mind。"""
    out = []
    for c in sorted(cs, key=lambda z: -z["peak"]):
        if all(((c["x"] - o["x"]) ** 2 + (c["y"] - o["y"]) ** 2) ** 0.5 >= mind
               for o in out):
            out.append(c)
        if len(out) >= k:
            break
    return out


def cluster(cs):
    g = []
    for c in sorted(cs, key=lambda z: -z["peak"]):
        r = min(40.0, max(14.0, 2.5 * (c["area"] ** 0.5)))
        got = None
        for x in g:
            if ((c["x"] - x["x"]) ** 2 + (c["y"] - x["y"]) ** 2) ** 0.5 <= r:
                got = x
                break
        if got is None:
            g.append({"x": float(c["x"]), "y": float(c["y"]),
                      "area": c["area"], "peak": c["peak"], "_n": 1})
        else:
            k = got["_n"]
            got["x"] = (got["x"] * k + c["x"]) / (k + 1)
            got["y"] = (got["y"] * k + c["y"]) / (k + 1)
            got["area"] = max(got["area"], c["area"])
            got["peak"] = max(got["peak"], c["peak"])
            got["_n"] = k + 1
    return g


def iou_merge(boxes):
    boxes = sorted(boxes, key=lambda z: -z[4])
    mg = []
    for (x1, y1, x2, y2, sc) in boxes:
        hit_any = False
        for m in mg:
            iw = min(x2, m[2]) - max(x1, m[0])
            ih = min(y2, m[3]) - max(y1, m[1])
            if iw <= 0 or ih <= 0:
                continue
            inter = float(iw * ih)
            ua = (x2 - x1) * (y2 - y1) + (m[2] - m[0]) * (m[3] - m[1]) - inter
            if ua > 0 and inter / ua > 0.25:
                m[0], m[1] = min(m[0], x1), min(m[1], y1)
                m[2], m[3] = max(m[2], x2), max(m[3], y2)
                m[4] = max(m[4], sc)
                hit_any = True
                break
        if not hit_any:
            mg.append([x1, y1, x2, y2, sc])
    return mg


class Trk(object):
    def __init__(self):
        self.t = []

    def update(self, dets):
        for d in dets:
            best, bd = None, 1e9
            for k in self.t:
                dd = ((d[0] - k["x"]) ** 2 + (d[1] - k["y"]) ** 2) ** 0.5
                if dd < bd:
                    best, bd = k, dd
            if best is not None and bd <= TRK_R:
                best["x"] = (1 - EMA_A) * best["x"] + EMA_A * d[0]
                best["y"] = (1 - EMA_A) * best["y"] + EMA_A * d[1]
                best["w"] = (1 - EMA_A) * best["w"] + EMA_A * d[2]
                best["h"] = (1 - EMA_A) * best["h"] + EMA_A * d[3]
                best["p"] = max(best["p"], d[4])
                best["miss"] = 0
                best["live"] = 1
                best["hits"] = best.get("hits", 0) + 1
            else:
                self.t.append({"x": d[0], "y": d[1], "w": d[2], "h": d[3],
                               "p": d[4], "miss": 0, "live": 1, "hits": 1})
        for k in self.t:
            if not k.get("live"):
                k["miss"] += 1
            k["live"] = 0
        self.t = [k for k in self.t if k["miss"] <= MISS_MAX]
        return self.t


TRK = Trk()


def detect_loop(pl, y):
    while RUN[0]:
        f = FRAME[0]
        if f is None:
            time.sleep(0.005)
            continue
        t0 = time.time()
        gray = cv2.resize(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (W, H),
                          interpolation=cv2.INTER_LINEAR)
        cands, _st, _dt = pl.run(gray)
        keep = [c for c in cands if c["area"] >= 4 and c["peak"] >= 8
                and 8 <= c["y"] < H - 8 and 8 <= c["x"] < W - 8]
        for c in keep:
            c["x"] = (c["x"] + X_SHIFT) % W
        cl = sorted(cluster(keep), key=lambda z: -z["peak"])
        cin = pick_spread(cl, ROI_N)

        crops, meta = [], []
        for c in cin:
            sd = int(min(max(ROI_SIDE, 3.0 * (c["area"] ** 0.5)), 128))
            hx = sd // 2
            x0 = int(min(max(c["x"] - hx, 0), max(0, W - sd)))
            y0 = int(min(max(c["y"] - hx, 0), max(0, H - sd)))
            crops.append(gray[y0:y0 + sd, x0:x0 + sd].copy())
            meta.append((x0, y0, sd))

        raw = []
        if crops:
            best = {}
            for slot, x1, y1, x2, y2, sc in y.detect_mosaic(crops, grid=ROI_CELL):
                if slot >= len(meta):
                    continue
                if slot not in best or sc > best[slot][4]:
                    best[slot] = (x1, y1, x2, y2, sc)
            for i, (x0, y0, sd) in enumerate(meta):
                if i in best:
                    x1, y1, x2, y2, sc = best[i]
                    if sc >= ROI_CONF:
                        raw.append((x0 + x1, y0 + y1, x0 + x2, y0 + y2, float(sc)))

        # ⑦ 保护区重检
        lost = [k for k in TRK.t if k.get("miss", 0) >= 1 and k.get("hits", 0) >= RECHECK_HITS]
        if lost:
            rc, rm = [], []
            for k in lost[:ROI_N]:
                sd = 128
                hx = sd // 2
                x0 = int(min(max(k["x"] - hx, 0), max(0, W - sd)))
                y0 = int(min(max(k["y"] - hx, 0), max(0, H - sd)))
                rc.append(gray[y0:y0 + sd, x0:x0 + sd].copy())
                rm.append((x0, y0))
            if rc:
                for slot, x1, y1, x2, y2, sc in y.detect_mosaic(rc, grid=ROI_CELL,
                                                               conf=RECHECK_CONF):
                    if slot >= len(rm):
                        continue
                    x0, y0 = rm[slot]
                    raw.append((x0 + x1, y0 + y1, x0 + x2, y0 + y2, float(sc)))

        mg = iou_merge(raw) if raw else []
        dets = [(float((b[0] + b[2]) / 2), float((b[1] + b[3]) / 2),
                 float(b[2] - b[0]), float(b[3] - b[1]), b[4]) for b in mg]
        BOXES[0] = TRK.update(dets)
        DET_CNT[0] += 1
        DET_T[0] += time.time() - t0


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "/root/scan.mp4"
    dst = sys.argv[2] if len(sys.argv) > 2 else "/root/final_out.mp4"
    maxn = int(sys.argv[3]) if len(sys.argv) > 3 else 240

    pl = PL3D()
    y = Yolo(dev=pl.dev)
    threading.Thread(target=detect_loop, args=(pl, y), daemon=True).start()

    cap = cv2.VideoCapture(src)
    fps_src = cap.get(cv2.CAP_PROP_FPS) or 25.0
    ff = ("ffmpeg -y -f rawvideo -pix_fmt bgr24 -s %dx%d -r %d -i - "
          "-c:v libx264 -crf 20 -pix_fmt yuv420p %s" % (OUT_W, OUT_H, int(fps_src), dst))
    proc = subprocess.Popen(ff.split(), stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    n = 0
    t0 = time.time()
    while n < maxn:
        ok, f = cap.read()
        if not ok:
            break
        FRAME[0] = f
        vis = cv2.resize(f, (OUT_W, OUT_H))
        for k in BOXES[0]:
            x1 = int(k["x"] - k["w"] / 2)
            y1 = int(k["y"] - k["h"] / 2)
            x2 = int(k["x"] + k["w"] / 2)
            y2 = int(k["y"] + k["h"] / 2)
            col = (80, 230, 60) if k["p"] >= ROI_CONF else (40, 150, 240)
            aa_rect(vis, x1, y1, x2, y2, col, 3)
            cv2.putText(vis, "%.0f%%" % (min(1.0, k["p"]) * 100), (x1, max(12, y1 - 5)),
                        0, 0.7, col, 2, cv2.LINE_AA)
        cv2.putText(vis, "f%d  det %d  box %d" % (n, DET_CNT[0], len(BOXES[0])),
                    (8, 26), 0, 0.75, (0, 235, 255), 2, cv2.LINE_AA)
        proc.stdin.write(vis.tobytes())
        n += 1

    RUN[0] = False
    proc.stdin.close()
    proc.wait()
    wall = time.time() - t0
    print("VIDEO  %d frames / %.1f s -> %.1f fps（画面线程）" % (n, wall, n / wall))
    print("DETECT %d 次, %.1f ms/次 -> %.1f Hz"
          % (DET_CNT[0], DET_T[0] / max(1, DET_CNT[0]) * 1000,
             DET_CNT[0] / max(0.001, wall)))
    print("FINAL done -> %s" % dst)


if __name__ == "__main__":
    main()
