# -*- coding: utf-8 -*-
"""probe_out3.py —— 用正确 API 判断输出能否局部读 + 布局 + 有效通道。"""
import json
import sys
import time
import traceback

import numpy as np

sys.path.insert(0, "/root/ip2")


def main():
    import cv2
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
    print("SESSION_OK", flush=True)

    img = cv2.resize(cv2.imread("/root/ip2/t4_fourdrones.png"), (640, 640))
    t = xrt.Tensor(np.ascontiguousarray(img.reshape(1, 640, 640, 3).astype(np.uint8)), tt)
    t0 = time.time()
    outs = sess.forward([t])
    print("FORWARD %.2f ms n_out=%d" % ((time.time() - t0) * 1000, len(outs)), flush=True)

    o0 = outs[0]
    shp = [int(x) for x in json.loads(str(o0.dtype()))["shape"]]
    n = int(np.prod(shp))
    print("out0 shape=%s float32 n=%d bytes=%d" % (shp, n, n * 4), flush=True)

    full = bytearray(n * 4)
    t0 = time.time()
    o0.read(full, 0, n * 4)
    print("FULL read %.2f ms" % ((time.time() - t0) * 1000), flush=True)

    # 局部读：前 5 个通道
    try:
        np5 = 5 * 8400 * 4
        part = bytearray(np5)
        t0 = time.time()
        o0.read(part, 0, np5)
        dt = (time.time() - t0) * 1000
        p = np.frombuffer(bytes(part), dtype=np.float32)
        f = np.frombuffer(bytes(full), dtype=np.float32)
        same = np.allclose(p[:100], f[:100])
        print("PART read %.2f ms  prefix_match=%s" % (dt, same), flush=True)
    except Exception as e:
        print("PART FAIL:", str(e)[:120], flush=True)

    # 逐通道统计
    a = np.frombuffer(bytes(full), dtype=np.float32).reshape(shp[1], shp[2])
    print("=== 按 [64][8400] 解释 ===", flush=True)
    for c in (0, 1, 2, 3, 4, 5, 10, 63):
        r = a[c]
        print("  ch%-2d min=%7.2f max=%7.2f nonzero=%d"
              % (c, r.min(), r.max(), int(np.count_nonzero(r))), flush=True)


try:
    main()
except Exception:
    print("EXCEPTION:", flush=True)
    traceback.print_exc()
