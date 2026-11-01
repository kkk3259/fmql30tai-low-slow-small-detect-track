#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""calib.py —— 受控标定：把 t4 里一架无人机裁出来粘到 640 图正中，看它命中哪个锚点。

这样能把三个未知数一次定死：
  1) 8400 个锚点的分块顺序（哪个区间对应 80x80 / 40x40 / 20x20）
  2) 网格内 (gx,gy) 与图像 (x,y) 的对应关系
  3) w/h 的 stride 系数
"""
import json

import cv2
import numpy as np

NPU = "/root/npu/yolo11n_drone_trunc_ZG"


def sig(x):
    return 1.0 / (1.0 + np.exp(-x))


def read_tensor(o):
    d = json.loads(str(o.dtype()))
    shp = [int(x) for x in d["shape"]]
    n = int(np.prod(shp))
    buf = bytearray(n * 4)
    o.read(buf, 0, n * 4)
    return np.frombuffer(bytes(buf), dtype=np.float32).reshape(shp)


def levels(i):
    """三种可能的分块方案，全部返回。"""
    out = {}
    if i < 6400:
        j = i
        out["A_80first"] = (j % 80, j // 80, 8)
    elif i < 8000:
        j = i - 6400
        out["A_80first"] = (j % 40, j // 40, 16)
    else:
        j = i - 8000
        out["A_80first"] = (j % 20, j // 20, 32)
    # B: 20x20 在最前
    if i < 400:
        out["B_20first"] = (i % 20, i // 20, 32)
    elif i < 2000:
        j = i - 400
        out["B_20first"] = (j % 40, j // 40, 16)
    else:
        j = i - 2000
        out["B_20first"] = (j % 80, j // 80, 8)
    return out


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
    tt = net.ops[0].outputs[0].tensorType()
    try:
        tt.setShape([1, 640, 640, 3])
    except Exception:
        pass

    src = cv2.imread("/root/ip2/t4_fourdrones.png")
    big = cv2.resize(src, (640, 640))
    # 裁一架（右上那架，目测在 640 空间的 (430,230) 附近）
    patch = big[195:265, 395:465]
    canvas = np.zeros((640, 640, 3), np.uint8)
    canvas[:] = (140, 120, 90)          # 灰蓝天，避免纯黑太失真
    canvas[288:358, 288:358] = patch    # 中心 (320,323)

    rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)[None]
    t = xrt.Tensor(np.ascontiguousarray(rgb.astype(np.uint8)), tt)
    outs = sess.forward([t])
    o0 = read_tensor(outs[0])[0]
    o1 = read_tensor(outs[1])[0, 0]
    sc = sig(o1) * sig(o0[4:]).max(axis=0)
    print("真值：目标在 (320,323)，尺寸 70x70")
    top = np.argsort(-sc)[:6]
    for i in top:
        i = int(i)
        a = sig(o0[:4, i])
        print("  #%-5d score=%.3f raw=[%.1f,%.1f,%.1f,%.1f]" % (i, sc[i], *o0[:4, i]))
        for name, (gx, gy, st) in levels(i).items():
            cx = (2 * a[0] + gx - 0.5) * st
            cy = (2 * a[1] + gy - 0.5) * st
            w = 4 * a[2] * a[2] * st
            h = 4 * a[3] * a[3] * st
            print("      %-10s gx=%2d gy=%2d st=%2d -> cx=%5.1f cy=%5.1f w=%5.1f h=%5.1f"
                  % (name, gx, gy, st, cx, cy, w, h))


if __name__ == "__main__":
    main()
