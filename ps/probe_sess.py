# -*- coding: utf-8 -*-
"""probe_sess.py —— 打印 Session / Graph / Op 上取输入张量的可用接口。"""
import sys

sys.path.insert(0, "/root/ip2")
from icraft.xir import Network  # noqa
import icraft.xrt as xrt  # noqa
from icraft.zg330backend import ZG330Backend  # noqa
from icraft.host_backend import HostBackend  # noqa

M = "/root/npu/yolo11n_drone_trunc_ZG"
net = Network.CreateFromJsonFile(M + ".json")
net.lazyLoadParamsFromFile(M + ".raw", 0)
dev = xrt.Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
sess = xrt.Session.Create([ZG330Backend, HostBackend], net.view(0),
                          [dev, xrt.HostDevice.Default()])
sess.apply()

for name, obj in (("sess", sess), ("net", net), ("view", net.view(0))):
    cand = [a for a in dir(obj) if "input" in a.lower() or "tensor" in a.lower()]
    print(name, "->", cand[:12])

g = net.view(0)
print("ops[0] type:", type(g.ops[0]).__name__)
cand = [a for a in dir(g.ops[0]) if not a.startswith("_")]
print("op attrs:", cand[:20])
for a in ("inputs", "input", "getInputs", "inputsNum"):
    try:
        v = getattr(g.ops[0], a)
        print("  op.%s -> %r" % (a, v if not hasattr(v, "__len__") else len(v)))
    except Exception as e:
        print("  op.%s -> %s" % (a, str(e)[:60]))
