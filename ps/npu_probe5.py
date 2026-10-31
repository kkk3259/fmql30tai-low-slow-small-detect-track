# -*- coding: utf-8 -*-
import icraft.xir as xir
def p(*a): print(*a, flush=True)
names = [n for n in dir(xir) if not n.startswith("_")]
for k in ("Network", "View", "load", "Load", "Graph", "parse", "from_", "Proto", "Serializer", "Import"):
    hit = [n for n in names if k in n]
    if hit: p(k, "->", hit[:6])
p("全部含大写开头的名字数:", len([n for n in names if n[0].isupper()]))
