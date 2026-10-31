# -*- coding: utf-8 -*-
import icraft.zg330backend as zb, icraft.xrt as xrt
def p(*a): print(*a, flush=True)
p("zg330backend:", [n for n in dir(zb) if not n.startswith("_")][:20])
for n in dir(zb):
    if "init" in n.lower() or "register" in n.lower() or "load" in n.lower():
        p("  候选:", n)
p("ZG330Device:", [n for n in dir(xrt.ZG330Device) if not n.startswith("_")][:12])
p("xrt 里含 node 的:", [n for n in dir(xrt) if "ode" in n][:10])
