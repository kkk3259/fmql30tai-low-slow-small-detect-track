#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_yolo5.py —— 摸清 yolo11n 输出的编码规则。

不猜解码公式，先把 tensor 排布真相打出来：
  - 8400 个 anchor，每个 64 通道：前 4 个是不是 box？剩下 60 个是不是类别？
  - 分数用 sigmoid(通道值) 后 TOP-10 的表现
  - 同时打印第二个输出（[1,1,8400]）的 TOP-10
"""
import json
import os

import cv2
import numpy as np

NPU_DIR = "/root/npu"
J = os.path.join(NPU_DIR, "yolo11n_drone_trunc_ZG.json")
R = os.path.join(NPU_DIR, "yolo11n_drone_trunc_ZG.raw")
IMG = "/root/ip2/t4_fourdrones.png"


def read_tensor(o):
    d = json.loads(str(o.dtype()))
    shape = [int(x) for x in d["shape"]]
    n = 1
    for s in shape:
        n *= s
    buf = bytearray(n * 4)
    o.read(buf, 0, n * 4)
    arr = np.frombuffer(bytes(buf), dtype=np.float32).reshape(shape)
    return arr


def main():
    import icraft.xrt as xrt
    from icraft.xir import Network
    from icraft.zg330backend import ZG330Backend
    from icraft.host_backend import HostBackend

    net = Network.CreateFromJsonFile(J)
    net.lazyLoadParamsFromFile(R)
    dev = xrt.Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
    sess = xrt.Session.Create([ZG330Backend, HostBackend], net.view(0),
                              [dev, xrt.HostDevice.Default()])
    sess.apply()

    img = cv2.imread(IMG)
    img = cv2.resize(img, (640, 640))
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)[None, ...]

    tt = net.ops[0].outputs[0].tensorType()
    try:
        tt.setShape([1, 640, 640, 3])
    except Exception:
        pass
    tin = xrt.Tensor(np.ascontiguousarray(rgb.astype(np.uint8)), tt)
    outs = sess.forward([tin])
    print("N_OUT =", len(outs))
    a = read_tensor(outs[0])
    print("OUT0 shape", a.shape, "min %.2f max %.2f" % (a.min(), a.max()))
    if len(outs) > 1:
        b = read_tensor(outs[1])
        print("OUT1 shape", b.shape, "min %.2f max %.2f" % (b.min(), b.max()))
    else:
        b = None

    p = a[0]                      # [64, 8400]
    boxes = p[:4]                 # [4, 8400]
    cls = p[4:]                   # [60, 8400]
    print("boxes[0..4] (ch0) =", p[0, :5])
    print("ch4 (obj?)        =", p[4, :5])
    print("ch5 (cls0?)       =", p[5, :5])

    sc = 1.0 / (1.0 + np.exp(-cls))
    best = sc.max(axis=0)         # 每个 anchor 的最高类概率
    idx = np.argsort(-best)[:10]
    print("=== TOP10 by sigmoid(max_class) ===")
    for i in idx:
        gx = gy = lv = -1
        if i < 6400:
            lv, gx, gy, st = 0, i % 80, i // 80, 8
        elif i < 8000:
            j = i - 6400
            lv, gx, gy, st = 1, j % 40, j // 40, 16
        else:
            j = i - 8000
            lv, gx, gy, st = 2, j % 20, j // 20, 32
        s = float(best[i])
        obj = ""
        if b is not None:
            obj = " out1=%.3f" % float(1.0 / (1.0 + np.exp(-b[0, 0, i])))
        print("  #%5d L%d gx=%2d gy=%2d  p=%.4f  raw4=%s%s"
              % (i, lv, gx, gy, s,
                 np.array2string(boxes[:, i], precision=2, separator=","), obj))


if __name__ == "__main__":
    main()
