# -*- coding: utf-8 -*-
"""按厂商 icraft_utils.py 的官方写法建立 NPU 会话并跑一次前向。"""
import numpy as np
import icraft.xir as xir, icraft.xrt as xrt
import icraft.host_backend as hb
from icraft.zg330backend import ZG330Backend, OcmOpt

def p(*a): print(*a, flush=True)

JSON = "/root/npu/yolov5s_352x640_ZG.json"
RAW  = "/root/npu/yolov5s_352x640_ZG.raw"

p("1) 加载网络")
net = xir.Network.CreateFromJsonFile(JSON)
net.lazyLoadParamsFromFile(RAW)
p("   ok")

p("2) 打开设备")
dev = xrt.Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
p("   ok")

p("3) 建会话（ZG330Backend + HostBackend）")
sess = xrt.Session.Create([ZG330Backend, hb.HostBackend], net.view(0),
                          [dev, xrt.HostDevice.Default()])
p("   ok, forwards =", len(sess.getForwards()))

p("4) 看输入输出")
v = net.view(0)
try:
    ins = v.inputs(); outs = v.outputs()
    for nm, coll in (("in", ins), ("out", outs)):
        for i, t in enumerate(coll):
            p("   %s[%d] name=%s shape=%s" % (nm, i, t.name(), [d for d in t.shape()]))
except Exception as e:
    p("   读形状失败:", repr(e)[:120])
