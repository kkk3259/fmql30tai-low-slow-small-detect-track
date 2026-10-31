# -*- coding: utf-8 -*-
import numpy as np
import icraft.xir as xir, icraft.xrt as xrt
import icraft.host_backend as hb
from icraft.zg330backend import ZG330Backend
def p(*a): print(*a, flush=True)
net = xir.Network.CreateFromJsonFile("/root/npu/yolov5s_352x640_ZG.json")
net.lazyLoadParamsFromFile("/root/npu/yolov5s_352x640_ZG.raw")
dev = xrt.Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
sess = xrt.Session.Create([ZG330Backend, hb.HostBackend], net.view(0), [dev, xrt.HostDevice.Default()])
sess.apply()
tt = net.ops[0].outputs[0].tensorType()
shape = [1, 352, 640, 3]
arr = np.zeros(shape, dtype=np.uint8); arr[...,0]=128; arr[...,1]=128; arr[...,2]=128
tt.setShape(shape)
outs = sess.forward([xrt.Tensor(arr, tt)])
p("OUT_N", len(outs), " type =", type(outs[0]).__name__)
o = outs[0]
p("Tensor methods:", [n for n in dir(o) if not n.startswith("_")][:24])
for meth in ("data", "buffer", "numpy", "toNumpy", "rawData"):
    if hasattr(o, meth):
        try:
            v = getattr(o, meth)()
            p("  ", meth, "->", type(v).__name__, getattr(v, "shape", ""))
        except Exception as e:
            p("  ", meth, "FAIL", repr(e)[:80])
