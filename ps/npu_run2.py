# -*- coding: utf-8 -*-
"""加载 NPU 模型并建会话（先 import 后端注册节点类型）。"""
import numpy as np
import icraft.zg330backend      # 关键：注册 ZG330DeviceNode
import icraft.xir as xir, icraft.xrt as xrt

def p(*a): print(*a, flush=True)

CFG = "/root/npu/yolov5s_352x640_ZG.json"
net = xir.Network.CreateFromJsonFile(CFG)
p("net OK, target =", net.ai_target)
view = xir.NetworkView(net)
try:
    ins, outs = view.inputs(), view.outputs()
    p("inputs:", [(n.name()) if callable(getattr(n,"name",None)) else n for n in ins][:4])
    p("n_in =", len(ins), "n_out =", len(outs))
except Exception as e:
    p("读输入输出:", repr(e)[:100])

dev = xrt.Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
p("DEVICE_OK")
try:
    sess = xrt.Session.Create([xrt.ZG330Device], view, [dev])
    p("CREATE_OK")
    p("forwards =", len(sess.getForwards()))
except Exception as e:
    txt = str(e)
    p("CREATE_FAIL")
    for l in txt.splitlines():
        if any(k in l for k in ("Exception info", "Error", "not registered", "TypeError")):
            p("  |", l.strip()[:160])
