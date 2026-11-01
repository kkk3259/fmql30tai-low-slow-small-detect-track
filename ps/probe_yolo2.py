#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_yolo2.py —— 穷举各种方式取 yolo11n 输出张量的形状/大小。"""
import numpy as np
import cv2

from icraft.xir import Network
import icraft.xrt as xrt
from icraft.zg330backend import ZG330Backend
from icraft.host_backend import HostBackend

J = "/root/npu/yolo11n_drone_trunc_ZG.json"
R = "/root/npu/yolo11n_drone_trunc_ZG.raw"
IMG = "/root/ip2/t2_twodrones.png"


def dump(obj, tag, depth=0):
    """把对象上所有可调用的无参属性和普通属性都试一遍。"""
    names = [n for n in dir(obj) if not n.startswith("_")]
    out = []
    for n in names:
        try:
            v = getattr(obj, n)
        except Exception:
            continue
        if callable(v):
            try:
                r = v()
                if isinstance(r, (int, float, str, list, tuple)) or r is None:
                    out.append("%s()=%s" % (n, r))
            except Exception:
                pass
        else:
            if isinstance(v, (int, float, str, list, tuple)) or v is None:
                out.append("%s=%s" % (n, v))
    print("  [%s] %s" % (tag, " | ".join(out[:30])), flush=True)


net = Network.CreateFromJsonFile(J)
net.lazyLoadParamsFromFile(R)
dev = xrt.Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
sess = xrt.Session.Create([ZG330Backend, HostBackend], net.view(0),
                          [dev, xrt.HostDevice.Default()])
sess.apply()

print("=== 网络输出节点的 tensorType ===", flush=True)
for i, op in enumerate(net.ops[-4:]):
    print("  op[%d] typeKey=%s" % (len(net.ops) - 4 + i, getattr(op, "typeKey", "?")), flush=True)
    dump(op, "op")
    try:
        for j, o in enumerate(op.outputs):
            dump(o, "out%d" % j)
            tt = o.tensorType() if hasattr(o, "tensorType") else None
            if tt is not None:
                dump(tt, "tt%d" % j)
    except Exception as ex:
        print("   outputs fail:", repr(ex), flush=True)

# 只打最后两个 op 的输出形状
print("=== 最后一层输出 ===", flush=True)
last = net.ops[-1]
tt0 = last.outputs[0].tensorType()
print("  tt:", tt0, flush=True)
for a in dir(tt0):
    if a.startswith("_"):
        continue
    try:
        v = getattr(tt0, a)
        print("   tt.%s = %s%s" % (a, v, (" -> " + str(v())) if callable(v) else ""), flush=True)
        break
    except Exception:
        pass

# 跑一次前向，看输出张量本身
img = cv2.imread(IMG)
inp = cv2.cvtColor(cv2.resize(img, (640, 640)), cv2.COLOR_BGR2RGB).reshape(1, 640, 640, 3)
tin = xrt.Tensor(np.ascontiguousarray(inp), net.ops[0].outputs[0].tensorType())
outs = sess.forward([tin])
print("=== 输出张量 ===", flush=True)
for i, o in enumerate(outs):
    dump(o, "outs%d" % i)
print("DONE", flush=True)
