#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_yolo.py —— 探 yolo11n_drone 的输入输出格式（逐步打印，不吞异常）"""
import sys
import numpy as np
import cv2

from icraft.xir import Network
import icraft.xrt as xrt
from icraft.zg330backend import ZG330Backend
from icraft.host_backend import HostBackend

J = "/root/npu/yolo11n_drone_trunc_ZG.json"
R = "/root/npu/yolo11n_drone_trunc_ZG.raw"
IMG = sys.argv[1] if len(sys.argv) > 1 else "/root/ip2/t2_twodrones.png"

print("1) load network", flush=True)
net = Network.CreateFromJsonFile(J)
net.lazyLoadParamsFromFile(R)
print("   ops =", len(net.ops), flush=True)

print("2) open device", flush=True)
dev = xrt.Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
print("   dev ok", flush=True)

print("3) session", flush=True)
sess = xrt.Session.Create([ZG330Backend, HostBackend], net.view(0),
                          [dev, xrt.HostDevice.Default()])
print("   session ok, apply...", flush=True)
sess.apply()
print("   applied", flush=True)

# 输入张量类型
op0 = net.ops[0]
tt = op0.outputs[0].tensorType()
for attr in ("getShape", "shape", "dims", "getDims"):
    if hasattr(tt, attr):
        try:
            print("   input shape via %s = %s" % (attr, getattr(tt, attr)()), flush=True)
            break
        except Exception:
            try:
                print("   input shape via %s = %s" % (attr, getattr(tt, attr)), flush=True)
                break
            except Exception:
                pass

img = cv2.imread(IMG)
if img is None:
    print("   read img fail", flush=True); sys.exit(1)
inp = cv2.resize(img, (640, 640))
inp = cv2.cvtColor(inp, cv2.COLOR_BGR2RGB)
arr = inp.reshape(1, 640, 640, 3).astype(np.uint8)

print("4) forward", flush=True)
tin = xrt.Tensor(arr, tt)
outs = sess.forward([tin])
print("   n_out =", len(outs), flush=True)
for i, o in enumerate(outs):
    try:
        shp = None
        for a in ("getShape", "shape", "dims"):
            if hasattr(o, a):
                v = getattr(o, a)
                shp = v() if callable(v) else v
                break
        print("   out[%d] shape=%s" % (i, shp), flush=True)
        buf = bytearray(64)
        o.read(buf, 0, 64)
        vals = np.frombuffer(bytes(buf), dtype=np.float32)[:8]
        print("        head floats = %s" % np.array2string(vals, precision=4), flush=True)
    except Exception as ex:
        print("   out[%d] read fail: %r" % (i, ex), flush=True)

print("DONE", flush=True)
