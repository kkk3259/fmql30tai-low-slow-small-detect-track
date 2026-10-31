# -*- coding: utf-8 -*-
"""输出张量先 to(host) 再 read。"""
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
a = np.zeros(shape, dtype=np.uint8); a[..., 1] = 90
tt.setShape(shape)
outs = sess.forward([xrt.Tensor(a, tt)])
o = outs[0]
p("FWD_OK")

hd = xrt.HostDevice.Default()
p("HostDevice methods:", [n for n in dir(hd) if not n.startswith("_")][:12])
for getter in ("defaultMemRegion", "getMemRegion"):
    m = getattr(hd, getter, None)
    if m is None: continue
    try:
        hm = m("host") if getter == "getMemRegion" else m()
        p(getter, "->", type(hm).__name__)
        ht = o.to(hm)
        p("  to(host) OK, addr =", hex(ht.data().addr()))
        buf = bytearray(4096)
        ht.read(buf, 0, 4096)
        f = np.frombuffer(bytes(buf), dtype=np.float32)
        p("  READ OK f32[:8] =", np.round(f[:8], 4).tolist())
        u = np.frombuffer(bytes(buf), dtype=np.uint8)
        p("  u8[:8] =", u[:8].tolist())
        break
    except Exception as e:
        p(getter, "FAIL", repr(e)[:120])
