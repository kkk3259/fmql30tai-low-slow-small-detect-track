# -*- coding: utf-8 -*-
"""真正把 NPU 模型加载进 Session 并跑一次前向。"""
import sys
import icraft.xir as xir, icraft.xrt as xrt
def p(*a): print(*a, flush=True)

CFG = "/root/npu/yolov5s_352x640_ZG.json"
p("== 1. 加载网络 ==")
net = xir.Network.CreateFromJsonFile(CFG)
p("   net OK, ai_target =", net.ai_target, " icraft =", net.icraft_version)
ops = net.getOpsById  # 只确认存在
p("== 2. 建视图 ==")
view = None
for desc, fn in (("NetworkView(net)", lambda: xir.NetworkView(net)),
                 ("net.view()", lambda: net.view())):
    try:
        view = fn(); p("   OK:", desc, type(view).__name__); break
    except Exception as e:
        p("   FAIL:", desc, repr(e)[:120])
if view is None:
    sys.exit(1)
try:
    ins = view.inputs; outs = view.outputs
    p("   inputs:", [ (i.name, [t.name for t in i.tensors]) if hasattr(i,"tensors") else i for i in ins][:4])
    p("   n_in =", len(ins), " n_out =", len(outs))
except Exception as e:
    p("   读 inputs/outputs 失败:", repr(e)[:120])

p("== 3. 开会话 ==")
dev = xrt.Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
sess = None
for desc, fn in (("Create([ZG330Device], view, [dev])", lambda: xrt.Session.Create([xrt.ZG330Device], view, [dev])),
                 ("Create([dev], view)", lambda: xrt.Session.Create([dev], view))):
    try:
        sess = fn(); p("   OK:", desc); break
    except Exception as e:
        p("   FAIL:", desc, repr(e)[:200])
if sess is None:
    sys.exit(1)
p("   forwards =", len(sess.getForwards()) if hasattr(sess,"getForwards") else "?")
