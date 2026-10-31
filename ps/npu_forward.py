# -*- coding: utf-8 -*-
"""NPU 前向：按官方 numpy2Tensor 写法构造输入并跑一次 forward。"""
import numpy as np
import icraft.xir as xir, icraft.xrt as xrt
import icraft.host_backend as hb
from icraft.zg330backend import ZG330Backend, OcmOpt

def p(*a): print(*a, flush=True)
JSON = "/root/npu/yolov5s_352x640_ZG.json"
RAW  = "/root/npu/yolov5s_352x640_ZG.raw"

net = xir.Network.CreateFromJsonFile(JSON)
net.lazyLoadParamsFromFile(RAW)
dev = xrt.Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
sess = xrt.Session.Create([ZG330Backend, hb.HostBackend], net.view(0),
                          [dev, xrt.HostDevice.Default()])
p("SESSION_OK forwards =", len(sess.getForwards()))

ops = net.ops
p("ops 数 =", len(ops), " ops[0].typeKey =", ops[0].typeKey())
if "InputNode" in ops[0].typeKey():
    iv = ops[0].outputs[0]
else:
    iv = ops[0].inputs[0]
tt = iv.tensorType()
p("输入 tensorType:", tt, " storage =", tt.getStorageType())
try:
    p("输入 shape:", [d for d in tt.shape()])
except Exception as e:
    p("shape 读不出:", repr(e)[:80])

shape = [1, 3, 352, 640]
arr = np.zeros(shape, dtype=np.uint8)
tt.setShape(shape)
arr = arr.astype(np.uint8)
tin = xrt.Tensor(arr, tt)
p("TENSOR_OK", arr.shape, arr.dtype)

import time
t0 = time.time()
outs = sess.forward([tin])
dt = (time.time() - t0) * 1000
p("FORWARD_OK 用时 %.1f ms, 输出 %d 个" % (dt, len(outs)))
for i, o in enumerate(outs[:4]):
    a = np.array(o, copy=False)
    p("   out[%d] shape=%s dtype=%s  max=%.3f mean=%.4f" % (i, a.shape, a.dtype, float(a.max()), float(a.mean())))
