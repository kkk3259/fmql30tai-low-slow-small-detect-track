# -*- coding: utf-8 -*-
"""cls128 前向 + 读回输出（用 Tensor.read(buffer, off, size)）。"""
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
a = np.zeros(shape, dtype=np.uint8)
a[..., 1] = 90          # 绿色偏置，验证输入真的进去了
tt.setShape(shape)
outs = sess.forward([xrt.Tensor(a, tt)])
p("FWD_OK n =", len(outs))

for i, o in enumerate(outs):
    for nbytes in (64, 1024):
        buf = bytearray(nbytes)
        try:
            o.read(buf, 0, nbytes)
            arr = np.frombuffer(bytes(buf), dtype=np.float32)
            p("out[%d] read %dB  f32[:6]=%s" % (i, nbytes, np.round(arr[:6], 4).tolist()))
            u8 = np.frombuffer(bytes(buf), dtype=np.uint8)
            p("          u8[:8]=%s" % (u8[:8].tolist(),))
            break
        except Exception as e:
            p("out[%d] read %dB FAIL %s" % (i, nbytes, repr(e)[:90]))
