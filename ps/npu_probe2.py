# -*- coding: utf-8 -*-
"""探测 xir.Graph / xrt.Session 的接口，为真正跑 NPU 做铺垫。"""
import json, sys
import icraft.xrt as xrt
import icraft.xir as xir

def p(*a): print(*a, flush=True)

p("== xir 顶层 ==")
p("  ", [n for n in dir(xir) if not n.startswith("_")][:30])
G = getattr(xir, "Graph", None)
p("== Graph ==", G)
if G:
    p("   methods:", [n for n in dir(G) if not n.startswith("_")][:40])
p("== Session ==")
p("   methods:", [n for n in dir(xrt.Session) if not n.startswith("_")][:40])

p("== 试加载 json ==")
try:
    g = G.load("/root/npu/yolov5s_352x640_ZG.json")
    p("   Graph.load OK")
    p("   graph:", [n for n in dir(g) if not n.startswith("_")][:40])
    p("   name =", getattr(g, "name", None))
except Exception as e:
    p("   Graph.load FAIL:", repr(e))
    # 试别的入口
    for attr in ("GraphMeta", "load", "Op", "Tensor"):
        if hasattr(xir, attr):
            p("   has xir." + attr)
