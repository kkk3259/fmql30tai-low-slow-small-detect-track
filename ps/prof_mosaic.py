# -*- coding: utf-8 -*-
"""prof_mosaic.py —— 把 mosaic 的耗时逐段拆开。"""
import json
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, "/root/ip2")


def main():
    import icraft.xrt as xrt
    from icraft.xir import Network
    from icraft.zg330backend import ZG330Backend
    from icraft.host_backend import HostBackend

    M = "/root/npu/yolo11n_drone_trunc_ZG"
    net = Network.CreateFromJsonFile(M + ".json")
    net.lazyLoadParamsFromFile(M + ".raw", 0)
    dev = xrt.Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
    sess = xrt.Session.Create([ZG330Backend, HostBackend], net.view(0),
                              [dev, xrt.HostDevice.Default()])
    sess.apply()
    tt = net.ops[0].outputs[0].tensorType()

    # 5 块 128x128 裁片（模拟 ROI）
    g = cv2.cvtColor(cv2.resize(cv2.imread("/root/ip2/t4_fourdrones.png"), (640, 360)),
                     cv2.COLOR_BGR2GRAY)
    crops = [g[100 + i * 20:228 + i * 20, 100:228] for i in range(5)]

    def once():
        t = {}
        t0 = time.time()
        canvas = np.full((640, 640, 3), 114, np.uint8)
        cell = 640 // 4
        for i, c in enumerate(crops):
            r = i // 4
            q = i % 4
            p = cv2.cvtColor(cv2.resize(c, (cell, cell)), cv2.COLOR_GRAY2BGR)
            canvas[r * cell:(r + 1) * cell, q * cell:(q + 1) * cell] = p
        t["resize+pack"] = (time.time() - t0) * 1000

        t0 = time.time()
        tin = xrt.Tensor(np.ascontiguousarray(canvas.reshape(1, 640, 640, 3)), tt)
        t["tensor"] = (time.time() - t0) * 1000

        t0 = time.time()
        outs = sess.forward([tin])
        t["forward"] = (time.time() - t0) * 1000

        t0 = time.time()
        o0 = outs[0]
        shp = [int(x) for x in json.loads(str(o0.dtype()))["shape"]]
        n0 = int(np.prod(shp))
        b0 = bytearray(n0 * 4)
        o0.read(b0, 0, n0 * 4)
        a0 = np.frombuffer(bytes(b0), dtype=np.float32).reshape(shp)
        t["read OUT0"] = (time.time() - t0) * 1000

        t0 = time.time()
        o1 = outs[1]
        s1 = [int(x) for x in json.loads(str(o1.dtype()))["shape"]]
        n1 = int(np.prod(s1))
        b1 = bytearray(n1 * 4)
        o1.read(b1, 0, n1 * 4)
        a1 = np.frombuffer(bytes(b1), dtype=np.float32).reshape(s1)
        t["read OUT1"] = (time.time() - t0) * 1000

        t0 = time.time()
        ml = a0[0, 4:, :].max(axis=0)
        sc = (1.0 / (1.0 + np.exp(-a1[0, 0])) * (1.0 / (1.0 + np.exp(-ml))))
        idx = np.where(sc > 0.45)[0]
        t["decode"] = (time.time() - t0) * 1000
        t["n_box"] = len(idx)
        return t, sc.max()

    once()
    acc = {}
    for _ in range(6):
        t, mx = once()
        for k, v in t.items():
            acc[k] = acc.get(k, 0.0) + v
    print("max score = %.3f" % mx, flush=True)
    tot = 0.0
    for k, v in acc.items():
        if k == "n_box":
            print("%-12s %d" % (k, v / 6), flush=True)
            continue
        print("%-12s %.2f ms" % (k, v / 6), flush=True)
        tot += v / 6
    print("%-12s %.2f ms" % ("TOTAL", tot), flush=True)


main()
