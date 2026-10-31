# -*- coding: utf-8 -*-
import icraft.xir as xir, icraft.xrt as xrt
def p(*a): print(*a, flush=True)
names = [n for n in dir(xir) if not n.startswith("_")]
p("xir 名字总数:", len(names))
p("含 graph 的:", [n for n in names if "raph" in n.lower()])
p("含 Model/GX 的:", [n for n in names if "model" in n.lower() or n.startswith("GX")][:10])
import icraft
p("icraft 子模块:", [n for n in dir(icraft) if not n.startswith("_")])
for sub in ("xir",):
    m = getattr(icraft, sub)
    p(sub, "attrs:", [n for n in dir(m) if "raph" in n.lower()][:10])
# 试 from icraft.xir import Graph
try:
    from icraft.xir import Graph as G2
    p("from icraft.xir import Graph OK")
except Exception as e:
    p("Graph import FAIL:", repr(e))
# 试 xir.Graph 是否存在其它层级
import sys
p("已加载 icraft.* 模块:", [m for m in sys.modules if m.startswith("icraft")][:20])
