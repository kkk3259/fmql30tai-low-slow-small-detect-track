# -*- coding: utf-8 -*-
"""无摄像头帧率基准：用视频文件当输入，逐段计时，算出理论帧率。

跑：python3 bench_nocam.py /root/photos.mp4 60
"""
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, "/root/ip2")
from cam3d_test import PL3D          # noqa: E402
from yolo_det import Yolo            # noqa: E402

W, H = 640, 360
ROI_SIDE, ROI_CELL, ROI_CONF = 96, 4, 0.45
ROI_N = ROI_CELL * ROI_CELL
X_SHIFT = 64


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


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "/root/photos.mp4"
    maxn = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    pl = PL3D()
    y = Yolo(dev=pl.dev)

    cap = cv2.VideoCapture(src)
    acc = {"cap": 0.0, "gray": 0.0, "pl": 0.0, "crop": 0.0, "npu": 0.0}
    n = 0
    while n < maxn:
        t0 = time.time()
        ok, f = cap.read()
        if not ok:
            break
        t1 = time.time()
        gray = cv2.resize(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (W, H),
                          interpolation=cv2.INTER_AREA)
        t2 = time.time()
        cands, _st, _dt = pl.run(gray)
        t3 = time.time()
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
        t4 = time.time()
        if crops:
            y.detect_mosaic(crops, grid=ROI_CELL)
        t5 = time.time()

        acc["cap"] += t1 - t0
        acc["gray"] += t2 - t1
        acc["pl"] += t3 - t2
        acc["crop"] += t4 - t3
        acc["npu"] += t5 - t4
        n += 1

    print("frames =", n)
    tot = 0.0
    for k in ("cap", "gray", "pl", "crop", "npu"):
        ms = acc[k] / max(1, n) * 1000.0
        tot += ms
        print("  %-5s %7.2f ms" % (k, ms))
    print("  TOTAL %7.2f ms  -> %.1f fps" % (tot, 1000.0 / tot))
    print("  去掉读帧(cap)后: %.2f ms -> %.1f fps"
          % (tot - acc["cap"] / max(1, n) * 1000.0,
             1000.0 / (tot - acc["cap"] / max(1, n) * 1000.0)))


if __name__ == "__main__":
    main()
