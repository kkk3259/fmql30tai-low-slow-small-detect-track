# -*- coding: utf-8 -*-
"""cls128_drone_ZG 前向：确认输入形状与耗时（输出回读暂不处理）。"""
import numpy as np, time
import icraft.xir as xir, icraft.xrt as xrt
import icraft.host_backend as hb
from icraft.zg330backend import ZG330Backend
def p(*a): print(*a, flush=True)

JSON = "/root/npu/cls128_drone_ZG.json"
RAW  = "/root/npu/cls128_drone_ZG.raw"
net = xir.Network.CreateFromJsonFile(JSON)
net.lazyLoadParamsFromFile(RAW)
p("NET_OK ops =", len(net.ops))
tt = net.ops[0].outputs[0].tensorType()
p("INPUT tensorType =", str(tt)[:160])
try:
    shp = list(tt['shape']) if hasattr(tt,'__getitem__') else None
except Exception:
    shp = None
p("INPUT shape attr =", shp)

dev = xrt.Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
sess = xrt.Session.Create([ZG330Backend, hb.HostBackend], net.view(0), [dev, xrt.HostDevice.Default()])
t0=time.time(); sess.apply(); p("APPLY_OK %.1f ms, forwards=%d" % ((time.time()-t0)*1000, len(sess.getForwards())))

shape=[1,128,128,3]
a=np.zeros(shape, dtype=np.uint8)
tt.setShape(shape)
t0=time.time()
outs = sess.forward([xrt.Tensor(a, tt)])
p("FORWARD_OK %.2f ms, 输出 %d 个" % ((time.time()-t0)*1000, len(outs)))
