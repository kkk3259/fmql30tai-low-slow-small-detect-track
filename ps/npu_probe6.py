# -*- coding: utf-8 -*-
import icraft.xir as xir
def p(*a): print(*a, flush=True)
p("Network:", [n for n in dir(xir.Network) if not n.startswith("_")][:30])
p("NetworkView:", [n for n in dir(xir.NetworkView) if not n.startswith("_")][:20])
# 试加载
try:
    net = xir.Network()
    p("Network() OK")
    for meth in ("load", "Load", "import", "parse", "fromJson", "loadJson"):
        if hasattr(net, meth):
            p("   有方法", meth)
    if hasattr(net, "load"):
        r = net.load("/root/npu/yolov5s_352x640_ZG.json")
        p("   load 返回:", r)
        p("   节点数:", len(getattr(net, "ops", [])))
except Exception as e:
    p("Network() FAIL:", repr(e)[:200])
