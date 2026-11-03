#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bench cls128：单次前向耗时（任务2）

沿用 yolo_det.py 里已验证的 session 建法：
    from icraft.zg330backend import ZG330Backend
    from icraft.host_backend import HostBackend
    xrt.Session.Create([ZG330Backend, HostBackend], net.view(0), [dev, xrt.HostDevice.Default()])

用法：python3 bench_cls128.py [N]     N 默认 200
"""
import json
import sys
import time

import numpy as np

import icraft.xrt as xrt
from icraft.xir import Network
from icraft.zg330backend import ZG330Backend
from icraft.host_backend import HostBackend

MODEL = "/root/npu/cls128_drone_ZG"
URL = "axi://zg330aiu?npu=0x40000000&dma=0x80000000"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 200
SIDE = 128


def main():
    net = Network.CreateFromJsonFile(MODEL + ".json")
    net.lazyLoadParamsFromFile(MODEL + ".raw", 0)
    dev = xrt.Device.Open(URL)

    sess = xrt.Session.Create([ZG330Backend, HostBackend], net.view(0),
                              [dev, xrt.HostDevice.Default()])
    sess.apply()

    # 从网络里找一个输出张量类型（用作输入 tensorType）
    tt = None
    for op in net.view(0).ops:
        if len(op.outputs) > 0:
            tt = op.outputs[0].tensorType()
            break
    print("tensorType:", tt)

    rng = np.random.default_rng(0)
    img = rng.integers(0, 255, (1, SIDE, SIDE, 3), dtype=np.uint8)
    rgb = np.ascontiguousarray(img.astype(np.uint8))

    buf = np.zeros(2, np.float32)
    fwd, tot = [], []
    for i in range(N):
        t0 = time.perf_counter()
        tin = xrt.Tensor(rgb, tt)
        t1 = time.perf_counter()
        outs = sess.forward([tin])
        t2 = time.perf_counter()
        outs[0].read(buf, 0, 2)
        t3 = time.perf_counter()
        fwd.append((t2 - t1) * 1e3)
        tot.append((t3 - t0) * 1e3)
        if i == 0:
            print("首次: tensor %.2f / forward %.2f / read %.2f ms" %
                  ((t1 - t0) * 1e3, (t2 - t1) * 1e3, (t3 - t2) * 1e3))
            print("输出:", buf)

    fwd = np.array(fwd[10:])
    tot = np.array(tot[10:])
    print("N=%d  前向: 均 %.3f / 中位 %.3f / 最小 %.3f / 最大 %.3f ms" %
          (len(fwd), fwd.mean(), np.median(fwd), fwd.min(), fwd.max()))
    print("N=%d  全程: 均 %.3f ms（含 Tensor 构造 + read）" % (len(tot), tot.mean()))
    print("T2_DONE")


if __name__ == "__main__":
    main()
