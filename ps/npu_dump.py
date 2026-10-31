# -*- coding: utf-8 -*-
import numpy as np, traceback
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
p("o.defined", o.defined(), " addr =", hex(o.data().addr()))
# 试 dump 的几种签名
for args in (( "/root/ip2/out0.bin",), ("bin","/root/ip2/out0.bin"), ("/root/ip2/out0.ftmp",) ):
    try:
        o.dump(*args); p("dump", args, "OK")
        break
    except Exception as e:
        p("dump", args, "FAIL", repr(e)[:60])
# 试 copyData：拷到 host tensor
try:
    h = xrt.Tensor(np.zeros([1,2],np.float32), net.view(0).outputs[0].tensorType())
    p("host tensor ok")
except Exception as e:
    p("host tensor FAIL", repr(e)[:60])
