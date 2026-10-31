# -*- coding: utf-8 -*-
import numpy as np
import icraft.xir as xir, icraft.xrt as xrt
import icraft.host_backend as hb
from icraft.zg330backend import ZG330Backend
def p(*a): print(*a, flush=True)

for name in ("copyData", "copyFrom", "read", "to", "data"):
    m = getattr(xrt.Tensor, name, None)
    if m is not None:
        p("### %s docs:" % name, (m.__doc__ or "").strip()[:400])

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
chunk = dev.defaultMemRegion().malloc(65536, 0, 64)
p("chunk addr =", hex(chunk.begin.addr()))
for call, fn in (
    ("o.copyData(chunk)", lambda: o.copyData(chunk)),
    ("o.copyData(chunk,0)", lambda: o.copyData(chunk, 0)),
    ("o.copyTo(chunk)", lambda: o.copyTo(chunk)),
):
    try:
        fn(); p(call, "OK")
        break
    except Exception as e:
        p(call, "ERR", str(e)[:220])
