# -*- coding: utf-8 -*-
import numpy as np
import icraft.xir as xir, icraft.xrt as xrt
import icraft.host_backend as hb
from icraft.zg330backend import ZG330Backend
def p(*a): print(*a, flush=True)
net = xir.Network.CreateFromJsonFile("/root/npu/cls128_drone_ZG.json")
net.lazyLoadParamsFromFile("/root/npu/cls128_drone_ZG.raw")
dev = xrt.Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
sess = xrt.Session.Create([ZG330Backend, hb.HostBackend], net.view(0), [dev, xrt.HostDevice.Default()])
sess.apply()
tt = net.ops[0].outputs[0].tensorType(); shape=[1,128,128,3]
a = np.zeros(shape, dtype=np.uint8); a[...,:]=90
tt.setShape(shape)
outs = sess.forward([xrt.Tensor(a, tt)])
o = outs[0]
addr = o.data().addr()
p("OUT addr =", hex(addr))
reg = dev.defaultMemRegion()
p("MemRegion methods:", [n for n in dir(reg) if not n.startswith("_")][:18])
for meth, args in (("read",(addr, 32)), ("read",(32, addr)),):
    if hasattr(reg, meth):
        try:
            v = getattr(reg, meth)(*args)
            p("  reg.%s%s ->" % (meth, args), type(v).__name__, (len(v) if hasattr(v,"__len__") else v))
            break
        except Exception as e:
            p("  reg.%s FAIL %s" % (meth, repr(e)[:80]))
