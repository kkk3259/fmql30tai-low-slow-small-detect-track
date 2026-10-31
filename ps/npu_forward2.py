# -*- coding: utf-8 -*-
"""NPU 前向 v2：apply() + NHWC [1,352,640,3]。"""
import numpy as np, time
import icraft.xir as xir, icraft.xrt as xrt
import icraft.host_backend as hb
from icraft.zg330backend import ZG330Backend

def p(*a): print(*a, flush=True)
JSON = "/root/npu/yolov5s_352x640_ZG.json"
RAW  = "/root/npu/yolov5s_352x640_ZG.raw"

net = xir.Network.CreateFromJsonFile(JSON)
net.lazyLoadParamsFromFile(RAW)
dev = xrt.Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
sess = xrt.Session.Create([ZG330Backend, hb.HostBackend], net.view(0),
                          [dev, xrt.HostDevice.Default()])
p("SESSION_OK forwards =", len(sess.getForwards()))
t0 = time.time()
sess.apply()
p("APPLY_OK %.1f ms" % ((time.time()-t0)*1000))

iv = net.ops[0].outputs[0]
tt = iv.tensorType()
shape = [1, 352, 640, 3]
arr = np.zeros(shape, dtype=np.uint8)
arr[..., 0] = 128; arr[..., 1] = 128; arr[..., 2] = 128
tt.setShape(shape)
tin = xrt.Tensor(arr, tt)
t0 = time.time()
outs = sess.forward([tin])
p("FORWARD_OK %.1f ms, 输出 %d 个" % ((time.time()-t0)*1000, len(outs)))
for i, o in enumerate(outs[:4]):
    a = np.array(o)
    p("   out[%d] shape=%s dtype=%s min=%.3f max=%.3f mean=%.4f" % (i, a.shape, a.dtype, float(a.min()), float(a.max()), float(a.mean())))
