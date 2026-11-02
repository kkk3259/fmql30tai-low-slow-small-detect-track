# -*- coding: utf-8 -*-
"""probe_out2.py —— 判断 NPU 输出能否局部读 + 布局 + 有效通道。"""
import sys
import time
import traceback

import numpy as np

sys.path.insert(0, "/root/ip2")

def main():
    from icraft.xir import Network
    import icraft.xrt as xrt
    from icraft.zg330backend import ZG330Backend
    from icraft.host_backend import HostBackend

    M = "/root/npu/yolo11n_drone_trunc_ZG"
    net = Network.CreateFromJsonFile(M + ".json")
    net.lazyLoadParamsFromFile(M + ".raw", 0)
    dev = xrt.Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
    sess = xrt.Session.Create([ZG330Backend, HostBackend], net.view(0),
                              [dev, xrt.HostDevice.Default()])
    sess.apply()
    print("SESSION_OK", flush=True)

    # 用一张有无人机的图喂进去
    import cv2
    img = cv2.imread("/root/ip2/t4_fourdrones.png")
    img = cv2.resize(img, (640, 640))
    inp = img.reshape(1, 640, 640, 3).astype(np.uint8)

    t = sess.getInputTensor(0)
    t.write(inp.tobytes(), 0, inp.size)
    t0 = time.time()
    outs = sess.forward([t])
    print("FORWARD %.2f ms  n_out=%d" % ((time.time() - t0) * 1000, len(outs)), flush=True)

    o0 = outs[0]
    print("out0 dtype:", str(o0.dtype())[:150], flush=True)

    # 1) 全量读
    full = bytearray(64 * 8400)
    t0 = time.time()
    o0.read(full, 0, len(full))
    print("FULL read %.2f ms" % ((time.time() - t0) * 1000), flush=True)

    # 2) 局部读（长度 = 5 通道）
    try:
        part = bytearray(5 * 8400)
        t0 = time.time()
        o0.read(part, 0, len(part))
        print("PART read(42000) %.2f ms  OK" % ((time.time() - t0) * 1000), flush=True)
        print("PART head:", list(part[:8]), flush=True)
    except Exception as e:
        print("PART read FAIL:", str(e)[:120], flush=True)

    # 3) 偏移读
    try:
        off = bytearray(8400)
        t0 = time.time()
        o0.read(off, 8400, 8400)
        print("OFFSET read OK %.2f ms head=%s" % ((time.time() - t0) * 1000, list(off[:6])), flush=True)
    except Exception as e:
        print("OFFSET read FAIL:", str(e)[:120], flush=True)

    # 4) 逐通道统计（判断布局 + 有效通道）
    a = np.frombuffer(bytes(full), dtype=np.int8).astype(np.int16)
    print("=== 按 C-major 解释: [64][8400] ===", flush=True)
    m = a.reshape(64, 8400)
    for c in list(range(0, 6)) + [60, 61, 62, 63]:
        print("  ch%-2d  min=%-4d max=%-4d mean=%.1f nonzero=%d"
              % (c, m[c].min(), m[c].max(), m[c].mean(), int(np.count_nonzero(m[c]))), flush=True)
    print("=== 按 A-major 解释: [8400][64] ===", flush=True)
    m2 = a.reshape(8400, 64)
    print("  col0 max=%d  col4 max=%d  col63 max=%d"
          % (m2[:, 0].max(), m2[:, 4].max(), m2[:, 63].max()), flush=True)


try:
    main()
except Exception:
    print("EXCEPTION:", flush=True)
    traceback.print_exc()
