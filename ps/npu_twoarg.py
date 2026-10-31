# -*- coding: utf-8 -*-
"""试 forward(inputs, outputs)：自己分配输出张量，就能直接读 numpy。"""
import numpy as np
import icraft.xir as xir, icraft.xrt as xrt
import icraft.host_backend as hb
from icraft.zg330backend import ZG330Backend
def p(*a): print(*a, flush=True)

net = xir.Network.CreateFromJsonFile("/root/npu/cls128_drone_ZG.json")
net.lazyLoadParamsFromFile("/root/npu/cls128_drone_ZG.raw")
v = net.view(0)
ov = list(v.outputs())
p("输出值个数 =", len(ov))
for i, x in enumerate(ov):
    p("  out[%d] type = %s" % (i, str(x.tensorType())[:120]))

dev = xrt.Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
sess = xrt.Session.Create([ZG330Backend, hb.HostBackend], v, [dev, xrt.HostDevice.Default()])
sess.apply()

itt = net.ops[0].outputs[0].tensorType(); ishape=[1,128,128,3]
a = np.zeros(ishape, dtype=np.uint8); a[...,1]=90
itt.setShape(ishape)
tin = xrt.Tensor(a, itt)

# 自己造输出张量（float32，形状按 tensorType 里的 shape）
outs_host = []
for x in ov:
    tt = x.tensorType()
    t = str(tt)
    p("   tt str:", t[:150])
    shp = [1, 2]
    outs_host.append(xrt.Tensor(np.zeros(shp, dtype=np.float32), tt))
p("host outputs 造好", len(outs_host))
try:
    sess.forward([tin], outs_host)
    p("TWOARG_FORWARD_OK")
    for i, t in enumerate(outs_host):
        p("  out[%d] addr=%s" % (i, hex(t.data().addr())))
except Exception as e:
    p("TWOARG_FORWARD_FAIL", repr(e)[:200])
