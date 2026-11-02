#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe3.py —— 不过滤，看 PL 给出的全部候选（含边界），确认 unpack 是否把它们全滤掉。"""
import sys

import cv2

sys.path.insert(0, "/root/ip2")
import cam3d_test as C  # noqa: E402
from cam3d_test import PL3D  # noqa: E402

pl = PL3D()


def raw_all(gray):
    c, st, dt = pl.run(gray)
    # 再读一遍原始字，自己解（不过滤）
    words = []
    for i in range(16):
        pl.reg.write(C.REG + C.R_WIN, i)
        pl.reg.read(C.REG + C.R_WIN)
        words.append(pl.reg.read(C.REG + C.R_WIN) & 0xFFFFFFFF)
    b = []
    for w in words:
        b += [(w >> 0) & 0xFF, (w >> 8) & 0xFF, (w >> 16) & 0xFF, (w >> 24) & 0xFF]
    n = b[0]
    out = []
    for j in range(n):
        s = 1 + j * 7
        if s + 6 >= len(b):
            break
        out.append({"x": (b[s] << 8) | b[s + 1], "y": (b[s + 2] << 8) | b[s + 3],
                    "area": (b[s + 4] << 8) | b[s + 5], "peak": b[s + 6]})
    return n, out, st, dt


for name in ("t2_twodrones", "t6_plane_bird", "t4_fourdrones"):
    img = cv2.imread("/root/ip2/%s.png" % name)
    g = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (640, 360),
                   interpolation=cv2.INTER_AREA)
    n, out, st, dt = raw_all(g)
    print("%-16s n_cand=%d dt=%.1fms  过滤后=%d" % (name, n, dt, len(out)), flush=True)
    for k in out[:10]:
        print("     x=%4d y=%3d area=%4d peak=%3d%s"
              % (k["x"], k["y"], k["area"], k["peak"],
                 "   <-- 被边界过滤" if not (24 <= k["y"] < 336) else ""), flush=True)
print("PROBE3_DONE")
