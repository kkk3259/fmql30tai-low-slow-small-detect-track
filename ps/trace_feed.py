#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""trace_feed.py —— 触发一帧后以 100us 间隔采样，抓 F_FEED 期间的 cfv / ccl_px 走势。
   R_CCL = {8'd0, px[17:0], 3'd0, state[2:0]}  -> px=(v>>6)&0x3FFFF, state=v&7
   R_STAT1 = {fifo[31:16], 5'd0, fst[10:8], err[7:0]}
"""
import mmap, os, struct, time

AXI_BASE = 0x43C00000
R_CTRL, R_STATUS, R_STAT1, R_CCL, R_THV, R_CFV = 0x00, 0x0C, 0x1C, 0x20, 0x28, 0x2C
FST = {0: "IDLE", 1: "RST", 2: "FILL", 3: "FEED", 4: "WAIT", 5: "WRITE", 6: "FIN"}

fa = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
ax = mmap.mmap(fa, 0x1000, offset=AXI_BASE)


def rd(o):
    return struct.unpack_from("<I", ax, o)[0]


def wr(o, v):
    struct.pack_into("<I", ax, o, v & 0xFFFFFFFF)


wr(R_CTRL, 1)
t0 = time.time()
print("  t(us)  FST   err  fifo   thv      cfv      px     cclst")
for _ in range(400):
    s1 = rd(R_STAT1)
    ccl = rd(R_CCL)
    thv = rd(R_THV)
    cfv = rd(R_CFV)
    fst = (s1 >> 8) & 0x7
    err = s1 & 0xFF
    fifo = (s1 >> 16) & 0xFFFF
    px = (ccl >> 6) & 0x3FFFF
    st = ccl & 0x7
    print("%8.0f  %-5s %3d %6d %7d %8d %8d  %d"
          % ((time.time() - t0) * 1e6, FST.get(fst, "?"), err, fifo, thv, cfv, px, st))
    if (rd(R_STATUS) & 0x1) == 0 and err:
        break
    time.sleep(0.0001)
print("END")
