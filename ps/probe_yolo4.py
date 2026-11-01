#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_yolo4.py —— 在 forward 返回的 Tensor 上找形状接口。"""
import numpy as np
import cv2

from icraft.xir import Network
import icraft.xrt as xrt
from icraft.zg330backend import ZG330Backend
from icraft.host_backend import HostBackend

net = Network.CreateFromJsonFile("/root/npu/yolo11n_drone_trunc_ZG.json")
net.lazyLoadParamsFromFile("/root/npu/yolo11n_drone_trunc_ZG.raw")
dev = xrt.Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
sess = xrt.Session.Create([ZG330Backend, HostBackend], net.view(0),
                          [dev, xrt.HostDevice.Default()])
sess.apply()

img = cv2.imread("/root/ip2/t2_twodrones.png")
inp = cv2.cvtColor(cv2.resize(img, (640, 640)), cv2.COLOR_BGR2RGB).reshape(1, 640, 640, 3)
tt = net.ops[0].outputs[0].tensorType()
outs = sess.forward([xrt.Tensor(np.ascontiguousarray(inp), tt)])
print("N_OUT", len(outs), flush=True)
for i, o in enumerate(outs):
    print("--- out %d ---" % i, flush=True)
    for expr in ("o.dtype()", "o.offset()", "o.chunk()", "o.chunk().byteSize()",
                 "o.chunk().size()", "np.asarray(o).shape", "np.array(o).shape"):
        try:
            v = eval(expr)
            print("  %s -> %s" % (expr, v), flush=True)
        except Exception as ex:
            print("  %s !! %r" % (expr, ex), flush=True)
    try:
        a = np.asarray(o)
        print("  asarray ok shape=%s dtype=%s head=%s" % (a.shape, a.dtype, np.array2string(np.ravel(a)[:8], precision=4)), flush=True)
    except Exception as ex:
        print("  asarray fail", repr(ex), flush=True)
print("DONE", flush=True)
