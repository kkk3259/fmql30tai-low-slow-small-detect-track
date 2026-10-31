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
shape=[1,352,640,3]
a=np.zeros(shape,dtype=np.uint8); a[...,0]=128; a[...,1]=128; a[...,2]=128
tt.setShape(shape)
outs = sess.forward([xrt.Tensor(a, tt)])
p("FWD_OK n =", len(outs))
for i in range(len(outs)):
    try:
        v = np.array(outs[i])
        p("  out[%d] np.ok shape=%s dtype=%s max=%.3f" % (i, v.shape, v.dtype, float(v.max())))
    except Exception as e:
        p("  out[%d] np.FAIL %s" % (i, repr(e)[:90]))
try:
    dev.reset(1); p("RESET_OK")
except Exception as e:
    p("RESET_FAIL", repr(e)[:60])
