# -*- coding: utf-8 -*-
"""试 Session.Create 的各种签名，找模型加载入口。"""
import icraft.xrt as xrt
def p(*a): print(*a, flush=True)

dev = xrt.Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
p("DEVICE_OK")
CFG = "/root/npu/yolov5s_352x640_ZG.json"
RAW = "/root/npu/yolov5s_352x640_ZG.raw"

tries = [
    ("Create(dev, cfg_path)",      lambda: xrt.Session.Create(dev, CFG)),
    ("Create(cfg_path)",           lambda: xrt.Session.Create(CFG)),
    ("Create(dev, raw_path)",      lambda: xrt.Session.Create(dev, RAW)),
    ("CreateWithBackends(dev,cfg)",lambda: xrt.Session.CreateWithBackends(dev, [CFG])),
]
for name, fn in tries:
    try:
        s_ = fn()
        p("  OK  ", name, type(s_).__name__)
        p("       methods:", [n for n in dir(s_) if not n.startswith("_")][:12])
        break
    except Exception as e:
        p("  FAIL", name, ":", repr(e)[:160])
p("Session.Create help:", (xrt.Session.Create.__doc__ or "")[:400])
