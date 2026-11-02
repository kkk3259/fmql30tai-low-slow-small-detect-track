#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe5.py —— 关键验证：候选表可能不止 8 条。

三域顶层是 .MAX_CAND(16)，表大小 = 1 + 16*7 = 113 字节 = 29 个字。
但 run() 只读了 16 个字（64 字节）= 前 8 条。
真目标很可能排在第 9~16 条，从来没被读出来。

本脚本读 32 个字（128 字节），解出前 16 条，不过滤，看真目标在第几名。
"""
import sys

import cv2

sys.path.insert(0, "/root/ip2")
import cam3d_test as C  # noqa: E402

pl = C.PL3D()

TARGETS = {
    "t2_twodrones": [(165, 92), (487, 248)],
    "t6_plane_bird": [(200, 268), (383, 180)],
    "t4_fourdrones": [(130, 152), (300, 176), (455, 118), (487, 232)],
}


def read_table(nwords=32):
    words = []
    for i in range(nwords):
        pl.reg.write(C.REG + C.R_WIN, i)
        pl.reg.read(C.REG + C.R_WIN)
        words.append(pl.reg.read(C.REG + C.R_WIN) & 0xFFFFFFFF)
    b = []
    for w in words:
        b += [(w >> 0) & 0xFF, (w >> 8) & 0xFF, (w >> 16) & 0xFF, (w >> 24) & 0xFF]
    n = b[0]
    out = []
    for j in range(min(n, 16)):
        s = 1 + j * 7
        if s + 6 >= len(b):
            break
        out.append({"r": j, "x": (b[s] << 8) | b[s + 1], "y": (b[s + 2] << 8) | b[s + 3],
                    "area": (b[s + 4] << 8) | b[s + 5], "peak": b[s + 6]})
    return n, out, b


for name, tgt in TARGETS.items():
    img = cv2.imread("/root/ip2/%s.png" % name)
    g = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (640, 360),
                   interpolation=cv2.INTER_AREA)
    pl.run(g)                      # 跑一帧
    n, out, b = read_table(32)
    print("%-16s n_cand=%d  解出 %d 条" % (name, n, len(out)), flush=True)
    for k in out:
        mark = ""
        for tx, ty in tgt:
            if abs(k["x"] - tx) + abs(k["y"] - ty) < 40:
                mark = "  <<< 命中真目标(%d,%d)" % (tx, ty)
        eb = "  [边界]" if not (24 <= k["y"] < 336) else ""
        print("   #%2d x=%4d y=%3d area=%4d peak=%3d%s%s"
              % (k["r"], k["x"], k["y"], k["area"], k["peak"], eb, mark), flush=True)
print("PROBE5_DONE")
