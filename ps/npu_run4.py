# -*- coding: utf-8 -*-
"""用后端类（ZG330Backend）而不是设备类去建会话。"""
import icraft.zg330backend as zb
import icraft.xir as xir, icraft.xrt as xrt
def p(*a): print(*a, flush=True)
net = xir.Network.CreateFromJsonFile("/root/npu/yolov5s_352x640_ZG.json")
view = xir.NetworkView(net)
dev = xrt.Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
p("dev ok")
try:
    sess = xrt.Session.Create([zb.ZG330Backend], view, [dev])
    p("CREATE_OK forwards=", len(sess.getForwards()))
except Exception as e:
    p("FAIL:", str(e).splitlines()[-1][:180] if str(e).splitlines() else repr(e)[:180])
