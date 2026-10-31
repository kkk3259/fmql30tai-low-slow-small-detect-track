# -*- coding: utf-8 -*-
import numpy as np, ctypes
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
shape=[1,352,640,3]
a=np.zeros(shape,dtype=np.uint8); a[...,0]=128; a[...,1]=128; a[...,2]=128
tt.setShape(shape)
outs = sess.forward([xrt.Tensor(a, tt)])
o = outs[0]
p("dtype =", o.dtype, " defined =", o.defined())
mp = o.data()
p("MemPtr type =", type(mp).__name__, " methods:", [n for n in dir(mp) if not n.startswith("_")][:14])
# 试 1: MemPtr.as_bytes
for meth in ("as_bytes","asBytes","bytes","tobytes","as_numpy"):
    if hasattr(mp, meth):
        try:
            b = getattr(mp, meth)()
            p("  mp."+meth, "->", type(b).__name__, len(b) if hasattr(b,"__len__") else "")
        except Exception as e:
            p("  mp."+meth, "FAIL", repr(e)[:70])
# 试 2: Tensor.to('cpu') / read()
for meth, args in (("to",("cpu",)), ("read",()), ("dump",())):
    if hasattr(o, meth):
        try:
            v = getattr(o, meth)(*args)
            p("  o."+meth, "->", type(v).__name__, getattr(v,"shape",""))
        except Exception as e:
            p("  o."+meth, "FAIL", repr(e)[:70])
