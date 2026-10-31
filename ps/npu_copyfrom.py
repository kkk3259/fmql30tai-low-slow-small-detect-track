# -*- coding: utf-8 -*-
"""copyFrom：把设备端输出拷进我们自己造的 host 张量。"""
import numpy as np
import icraft.xir as xir, icraft.xrt as xrt
import icraft.host_backend as hb
from icraft.zg330backend import ZG330Backend
def p(*a): print(*a, flush=True)

net = xir.Network.CreateFromJsonFile("/root/npu/cls128_drone_ZG.json")
net.lazyLoadParamsFromFile("/root/npu/cls128_drone_ZG.raw")
v = net.view(0)
ov = list(v.outputs())
dev = xrt.Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
sess = xrt.Session.Create([ZG330Backend, hb.HostBackend], v, [dev, xrt.HostDevice.Default()])
sess.apply()
itt = net.ops[0].outputs[0].tensorType(); ishape=[1,128,128,3]
a = np.zeros(ishape, dtype=np.uint8); a[...,1]=90
itt.setShape(ishape)
outs = sess.forward([xrt.Tensor(a, itt)])
p("FWD_OK n =", len(outs))
for i, o in enumerate(outs):
    tt = ov[i].tensorType()
    host = np.zeros([1,2], dtype=np.float32)
    try:
        ht = xrt.Tensor(host, tt)
        ht.copyFrom(0, o, 0, 8)
        buf = bytearray(16)
        try:
            ht.read(buf, 0, 16)
            f = np.frombuffer(bytes(buf), dtype=np.float32)
            p("out[%d] copyFrom+read -> %s" % (i, np.round(f[:4], 6).tolist()))
        except Exception as e2:
            p("out[%d] read-after-copy FAIL %s" % (i, repr(e2)[:80]))
        p("out[%d] copyFrom OK host=%s" % (i, np.round(host[0], 5).tolist()))
    except Exception as e:
        p("out[%d] copyFrom FAIL %s" % (i, repr(e)[:110]))
