# -*- coding: utf-8 -*-
"""推流与检测解耦：画面线程跑满帧率，检测线程自己定速，框由后处理叠加。

用法：offline_split.py <in.mp4> <out.mp4> [maxn]
"""
import subprocess
import sys
import threading
import time

import cv2

sys.path.insert(0, "/root/ip2")
from cam3d_test import PL3D          # noqa: E402
from yolo_det import Yolo            # noqa: E402

W, H = 640, 360
ROI_SIDE, ROI_CELL, ROI_CONF = 96, 4, 0.45
ROI_N = ROI_CELL * ROI_CELL
X_SHIFT = 64
OUT_W, OUT_H = 640, 360

FRAME = [None]        # 最新原始帧（彩色）
BOXES = [[]]          # 最新检测框（含 vx/vy 速度）
DET_FRAME = [0]       # 最近一次检测时的画面帧号
PREV = [{}]           # 上一轮检测的中心点，用来算速度
DET_CNT = [0]         # 检测次数
DET_T = [0.0]         # 检测总耗时
RUN = [True]
FRAME_N = [0]         # 当前已处理的画面帧号



def aa_rect(img, x1, y1, x2, y2, col, th=3):
    """抗锯齿矩形：cv2.rectangle 不支持 LINE_AA，用 4 条线拼。"""
    cv2.line(img, (x1, y1), (x2, y1), col, th, cv2.LINE_AA)
    cv2.line(img, (x2, y1), (x2, y2), col, th, cv2.LINE_AA)
    cv2.line(img, (x2, y2), (x1, y2), col, th, cv2.LINE_AA)
    cv2.line(img, (x1, y2), (x1, y1), col, th, cv2.LINE_AA)

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


def detect_loop(pl, y):
    while RUN[0]:
        f = FRAME[0]
        if f is None:
            time.sleep(0.005)
            continue
        t0 = time.time()
        gray = cv2.resize(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (W, H))
        cands, _st, _dt = pl.run(gray)
        keep = [c for c in cands if c["area"] >= 4 and c["peak"] >= 8
                and 8 <= c["y"] < H - 8 and 8 <= c["x"] < W - 8]
        for c in keep:
            c["x"] = (c["x"] + X_SHIFT) % W
        cl = sorted(cluster(keep), key=lambda z: -z["peak"])[:ROI_N]
        crops, meta = [], []
        for c in cl:
            sd = int(min(max(ROI_SIDE, 3.0 * (c["area"] ** 0.5)), 128))
            hx = sd // 2
            x0 = int(min(max(c["x"] - hx, 0), max(0, W - sd)))
            y0 = int(min(max(c["y"] - hx, 0), max(0, H - sd)))
            crops.append(gray[y0:y0 + sd, x0:x0 + sd].copy())
            meta.append((x0, y0, sd))
        out = []
        if crops:
            res = y.detect_mosaic(crops, grid=ROI_CELL)
            best = {}
            for slot, x1, y1, x2, y2, sc in res:
                if slot >= len(meta):
                    continue
                if slot not in best or sc > best[slot][4]:
                    best[slot] = (x1, y1, x2, y2, sc)
            for i, (x0, y0, sd) in enumerate(meta):
                if i in best:
                    x1, y1, x2, y2, sc = best[i]
                    if sc >= ROI_CONF:
                        out.append((int(x0 + x1), int(y0 + y1),
                                    int(x0 + x2), int(y0 + y2), float(sc)))
        # 速度估计：与上一轮同位置框比较，dt 用"检测轮次"折算成画面帧
        prev = PREV[0]
        outv = []
        for (x1, y1, x2, y2, sc) in out:
            cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
            vx = vy = 0.0
            bd, bk = 1e9, None
            for k, pv in prev.items():
                d = ((cx - pv[0]) ** 2 + (cy - pv[1]) ** 2) ** 0.5
                if d < bd:
                    bd, bk = d, k
            if bk is not None and bd < 90:
                pv = prev[bk]
                vx, vy = pv[2], pv[3]
                if pv[4] > 0:
                    nvx = (cx - pv[0]) / float(pv[4])
                    nvy = (cy - pv[1]) / float(pv[4])
                    vx = 0.6 * vx + 0.4 * nvx
                    vy = 0.6 * vy + 0.4 * nvy
            outv.append((x1, y1, x2, y2, sc, cx, cy, vx, vy))

        newprev = {}
        for i, b in enumerate(outv):
            newprev[i] = (b[5], b[6], b[7], b[8],
                          max(1, FRAME_N[0] - DET_FRAME[0]))
        PREV[0] = newprev
        BOXES[0] = outv
        DET_FRAME[0] = FRAME_N[0]      # 记下这次检测用的是第几帧
        DET_CNT[0] += 1
        DET_T[0] += time.time() - t0


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "/root/photos.mp4"
    dst = sys.argv[2] if len(sys.argv) > 2 else "/root/split_out.mp4"
    maxn = int(sys.argv[3]) if len(sys.argv) > 3 else 240

    pl = PL3D()
    y = Yolo(dev=pl.dev)
    th = threading.Thread(target=detect_loop, args=(pl, y), daemon=True)
    th.start()

    cap = cv2.VideoCapture(src)
    fps_src = cap.get(cv2.CAP_PROP_FPS) or 25.0
    ff = ("ffmpeg -y -f rawvideo -pix_fmt bgr24 -s %dx%d -r %d -i - "
          "-c:v libx264 -crf 20 -pix_fmt yuv420p %s" % (OUT_W, OUT_H, int(fps_src), dst))
    proc = subprocess.Popen(ff.split(), stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    n = 0
    t_start = time.time()
    while n < maxn:
        ok, f = cap.read()
        if not ok:
            break
        FRAME[0] = f                                   # 只丢最新帧，检测自己来取
        vis = cv2.resize(f, (OUT_W, OUT_H))            # 画面路径：不烧框，直接送编码
        FRAME_N[0] = n
        dtn = n - DET_FRAME[0]                          # 距上次检测过了几帧
        for b in BOXES[0]:
            x1, y1, x2, y2, sc = b[0], b[1], b[2], b[3], b[4]
            if len(b) > 8:                              # 速度外推
                dx = b[7] * dtn
                dy = b[8] * dtn
                x1, x2, y1, y2 = x1 + dx, x2 + dx, y1 + dy, y2 + dy
            aa_rect(vis, int(x1), int(y1), int(x2), int(y2), (80, 230, 60), 3)
            cv2.putText(vis, "%.0f%%" % (sc * 100), (int(x1), max(12, int(y1) - 5)),
                        0, 0.65, (80, 230, 60), 2, cv2.LINE_AA)
        cv2.putText(vis, "frame %d  det %d" % (n, DET_CNT[0]), (8, 24), 0, 0.7,
                    (0, 235, 255), 2)
        proc.stdin.write(vis.tobytes())
        n += 1
    RUN[0] = False
    proc.stdin.close()
    proc.wait()
    wall = time.time() - t_start
    print("VIDEO  %d frames in %.1f s -> %.1f fps（画面线程）" % (n, wall, n / wall))
    print("DETECT %d 次，平均 %.1f ms/次 -> %.1f Hz"
          % (DET_CNT[0], DET_T[0] / max(1, DET_CNT[0]) * 1000,
             DET_CNT[0] / max(0.001, wall)))
    print("SPLIT done -> %s" % dst)


if __name__ == "__main__":
    main()
