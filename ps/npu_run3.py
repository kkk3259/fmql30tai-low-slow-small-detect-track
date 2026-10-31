# -*- coding: utf-8 -*-
import icraft.zg330backend
import icraft.xir as xir, icraft.xrt as xrt
def p(*a): print(*a, flush=True)
p("A import ok")
net = xir.Network.CreateFromJsonFile("/root/npu/yolov5s_352x640_ZG.json")
p("B net ok")
view = xir.NetworkView(net)
p("C view ok")
dev = xrt.Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
p("D dev ok")
try:
    sess = xrt.Session.Create([xrt.ZG330Device], view, [dev])
    p("E CREATE_OK forwards=", len(sess.getForwards()))
except Exception as e:
    p("E CREATE_FAIL")
    for l in str(e).splitlines():
        if any(k in l for k in ("Exception info", "not registered", "TypeError", "Check failed")):
            p("   |", l.strip()[:160])
