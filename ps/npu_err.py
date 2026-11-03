# -*- coding: utf-8 -*-
"""抓 Session.Create 的完整错误关键行。"""
import icraft.xir as xir, icraft.xrt as xrt
net = xir.Network.CreateFromJsonFile("/root/npu/yolov5s_352x640_ZG.json")
view = xir.NetworkView(net)
dev = xrt.Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
try:
    sess = xrt.Session.Create([xrt.ZG330Device], view, [dev])
    print("CREATE_OK")
except Exception as e:
    txt = str(e)
    lines = txt.splitlines()
    print("TOTAL_LINES", len(lines))
    keys = ("error", "Error", "symbol", "lib", "No such", "cannot", "failed", "assert", "zg330", "backend")
    shown = 0
    for l in lines:
        if any(k in l for k in keys):
            print("  |", l.strip()[:170]); shown += 1
            if shown >= 14: break
    if shown == 0:
        for l in lines[-12:]:
            print("  ~", l.strip()[:170])
