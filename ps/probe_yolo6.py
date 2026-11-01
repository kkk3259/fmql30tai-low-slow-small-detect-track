#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_yolo6.py —— 用两种解码假设渲染 t4，一眼定死框编码。

假设 A（YOLOv5 风格）：cx=(2*sig(x)+gx-0.5)*st, w=4*sig(w)^2*anc
假设 B（YOLOv8/v11 ltrb）：x1=(gx+0.5-l)*st, x2=(gx+0.5+r)*st
分数 = sigmoid(out1) * sigmoid(max cls)
"""
import json
import os

import cv2
import numpy as np

NPU = "/root/npu/yolo11n_drone_trunc_ZG"
IMG = "/root/ip2/t4_fourdrones.png"
ANCH = {0: [(10, 13), (16, 30), (33, 23)], 1: [(30, 61), (62, 45), (59, 119)], 2: [(116, 90), (156, 198), (373, 326)]}


def read_tensor(o):
    d = json.loads(str(o.dtype()))
    shp = [int(x) for x in d["shape"]]
    n = int(np.prod(shp))
    buf = bytearray(n * 4)
    o.read(buf, 0, n * 4)
    return np.frombuffer(bytes(buf), dtype=np.float32).reshape(shp)


def sig(x):
    return 1.0 / (1.0 + np.exp(-x))


def level_of(i):
    if i < 6400:
        return 0, i % 80, i // 80, 8
    if i < 8000:
        j = i - 6400
        return 1, j % 40, j // 40, 16
    j = i - 8000
    return 2, j % 20, j // 20, 32


def main():
    import icraft.xrt as xrt
    from icraft.xir import Network
    from icraft.zg330backend import ZG330Backend
    from icraft.host_backend import HostBackend

    net = Network.CreateFromJsonFile(NPU + ".json")
    net.lazyLoadParamsFromFile(NPU + ".raw")
    dev = xrt.Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
    sess = xrt.Session.Create([ZG330Backend, HostBackend], net.view(0),
                              [dev, xrt.HostDevice.Default()])
    sess.apply()
    img = cv2.imread(IMG)
    h0, w0 = img.shape[:2]
    rgb = cv2.cvtColor(cv2.resize(img, (640, 640)), cv2.COLOR_BGR2RGB)[None]
    tt = net.ops[0].outputs[0].tensorType()
    try:
        tt.setShape([1, 640, 640, 3])
    except Exception:
        pass
    outs = sess.forward([xrt.Tensor(np.ascontiguousarray(rgb.astype(np.uint8)), tt)])
    o0 = read_tensor(outs[0])[0]          # [64,8400]
    o1 = read_tensor(outs[1])[0, 0]       # [8400]

    obj = sig(o1)
    cls = sig(o0[4:])
    sc = obj * cls.max(axis=0)
    print("score max %.4f  mean %.6f  >0.3: %d" % (sc.max(), sc.mean(), int((sc > 0.3).sum())))
    top = np.argsort(-sc)[:12]

    A = cv2.resize(img, (640, 640)).copy()
    B = A.copy()
    for i in top:
        lv, gx, gy, st = level_of(int(i))
        s = float(sc[i])
        if s < 0.15:
            continue
        b = o0[:4, i]
        # A: v5
        a = sig(b)
        ax, ay = (2 * a[0] + gx - 0.5) * st, (2 * a[1] + gy - 0.5) * st
        anc = ANCH[int(gx + gy) % 3] if False else ANCH[lv][0]
        aw, ah = 4 * a[2] * a[2] * st, 4 * a[3] * a[3] * st
        cv2.rectangle(A, (int(ax - aw / 2), int(ay - ah / 2)), (int(ax + aw / 2), int(ay + ah / 2)), (0, 255, 0), 2)
        cv2.putText(A, "%.2f" % s, (int(ax), int(ay - 6)), 0, 0.5, (0, 255, 0), 1)
        # B: ltrb
        x1 = (gx + 0.5 - b[0]) * st
        y1 = (gy + 0.5 - b[1]) * st
        x2 = (gx + 0.5 + b[2]) * st
        y2 = (gy + 0.5 + b[3]) * st
        cv2.rectangle(B, (int(x1), int(y1)), (int(x2), int(y2)), (0, 200, 255), 2)
        cv2.putText(B, "%.2f" % s, (int(x1), int(y1) - 6), 0, 0.5, (0, 200, 255), 1)
        print("  #%d L%d gx=%d gy=%d s=%.3f raw=%s" % (i, lv, gx, gy, s, np.round(b, 1)))

    cv2.putText(A, "A2: w=4*sig^2*stride", (8, 26), 0, 0.9, (0, 255, 0), 2)
    cv2.putText(B, "B: ltrb dist2bbox", (8, 26), 0, 0.9, (0, 200, 255), 2)
    out = np.vstack([A, B])
    cv2.imwrite("/root/ip2/yolo_a2.png", out)
    print("OUT /root/ip2/yolo_a2.png")


if __name__ == "__main__":
    main()
