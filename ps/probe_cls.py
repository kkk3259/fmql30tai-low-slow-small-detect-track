# -*- coding: utf-8 -*-
"""probe_cls.py —— 比较 A=max(sig(out0[4:])) 与 B=sig(out0[4]) 是否等价。"""
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
    tt.setShape([1, 640, 640, 3])

    def sig(x):
        return 1.0 / (1.0 + np.exp(-x))

    for name in ("t4_fourdrones.png", "t2_twodrones.png", "t6_plane_bird.png"):
        img = cv2.imread("/root/ip2/" + name)
        if img is None:
            print(name, "IMG_FAIL", flush=True)
            continue
        im = cv2.resize(img, (640, 640))
        tin = xrt.Tensor(np.ascontiguousarray(im.reshape(1, 640, 640, 3)), tt)
        outs = sess.forward([tin])

        o0 = outs[0]
        shp = [int(x) for x in json.loads(str(o0.dtype()))["shape"]]
        n = int(np.prod(shp))
        b0 = bytearray(n * 4)
        o0.read(b0, 0, n * 4)
        a0 = np.frombuffer(bytes(b0), np.float32).reshape(shp)[0]

        o1 = outs[1]
        s1 = [int(x) for x in json.loads(str(o1.dtype()))["shape"]]
        n1 = int(np.prod(s1))
        b1 = bytearray(n1 * 4)
        o1.read(b1, 0, n1 * 4)
        a1 = np.frombuffer(bytes(b1), np.float32).reshape(s1)[0, 0]

        # A: 60 类最大值；B: 只用第 0 类（通道 4）
        scA = sig(a1) * sig(a0[4:].max(axis=0))
        scB = sig(a1) * sig(a0[4])
        iA = np.where(scA >= 0.45)[0]
        iB = np.where(scB >= 0.45)[0]
        print("%-22s A: n=%2d top=%.3f   B: n=%2d top=%.3f   相同锚点=%d/%d"
              % (name, len(iA), scA.max(), len(iB), scB.max(),
                 len(set(iA.tolist()) & set(iB.tolist())), len(iA)), flush=True)
        # 哪个类通道最常是最大值
        arg = a0[4:].argmax(axis=0)
        vals, cnt = np.unique(arg, return_counts=True)
        top = sorted(zip(cnt, vals), reverse=True)[:3]
        print("      最高类通道分布(前3): %s" % (top,), flush=True)


main()
