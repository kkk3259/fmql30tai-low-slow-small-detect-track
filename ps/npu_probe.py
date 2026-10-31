# -*- coding: utf-8 -*-
"""在板上尝试加载 ICraft 编译好的 NPU 模型（yolov5s_352x640_ZG）。"""
import os, sys, json, traceback

MODEL = "/root/npu/yolov5s_352x640_ZG.raw"
CFG   = "/root/npu/yolov5s_352x640_ZG.json"

def p(*a): print(*a, flush=True)

p("== 1. import icraft ==")
try:
    import icraft.xrt as xrt
    import icraft.xir as xir
    p("   ok:", xrt.__file__)
except Exception as e:
    p("   FAIL:", repr(e)); sys.exit(1)

for mod in ("icraft.zg330backend", "icraft.host_backend"):
    try:
        __import__(mod); p("   import ok:", mod)
    except Exception as e:
        p("   import FAIL:", mod, repr(e))

p("== 2. 看模型 json 结构 ==")
try:
    cfg = json.load(open(CFG))
    p("   keys:", list(cfg.keys())[:12])
except Exception as e:
    p("   json FAIL:", repr(e))

p("== 3. 找加载模型的入口 ==")
names = [n for n in dir(xrt) if not n.startswith("_")]
p("   xrt:", names)
for n in names:
    if "Session" in n or "Model" in n or "Graph" in n or "Op" in n:
        p("   ->", n, getattr(xrt, n))

p("== 4. 试 Device.Open（需要平台位流在位）==")
try:
    url = "axi://zg330aiu?npu=0x40000000&dma=0x80000000"
    dev = xrt.Device.Open(url)
    p("   DEVICE_OK")
    p("   mem =", type(dev.defaultMemRegion()).__name__)
    reg = dev.defaultRegRegion()
    p("   VERSION =", hex(reg.read(0x400C0000 + 0x14)))
except Exception as e:
    p("   OPEN_FAIL:", repr(e))
