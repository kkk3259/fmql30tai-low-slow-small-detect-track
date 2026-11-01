#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_yolo3.py —— 直接打印 dir()，找出取形状的正确接口。"""
import numpy as np
import cv2

from icraft.xir import Network
import icraft.xrt as xrt
from icraft.zg330backend import ZG330Backend
from icraft.host_backend import HostBackend

J = "/root/npu/yolo11n_drone_trunc_ZG.json"
R = "/root/npu/yolo11n_drone_trunc_ZG.raw"

net = Network.CreateFromJsonFile(J)
net.lazyLoadParamsFromFile(R)
print("OPS", len(net.ops), flush=True)
last = net.ops[-1]
print("LAST typeKey =", last.typeKey(), flush=True)
n_out = len(last.outputs)
print("LAST n_outputs =", n_out, flush=True)

for j in range(n_out):
    o = last.outputs[j]
    print("--- output %d ---" % j, flush=True)
    print("  dir(out) =", [a for a in dir(o) if not a.startswith("_")], flush=True)
    tt = o.tensorType()
    print("  tt =", tt, flush=True)
    print("  dir(tt) =", [a for a in dir(tt) if not a.startswith("_")], flush=True)

# 试几种常见取法
tt = last.outputs[0].tensorType()
for a in ("shape", "getShape", "dims", "getDims", "sizes"):
    if hasattr(tt, a):
        v = getattr(tt, a)
        try:
            print("  tt.%s -> %s" % (a, v() if callable(v) else v), flush=True)
        except Exception as ex:
            print("  tt.%s error %r" % (a, ex), flush=True)
print("DONE", flush=True)
