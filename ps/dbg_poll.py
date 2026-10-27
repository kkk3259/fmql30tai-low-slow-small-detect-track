#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dbg_poll.py —— 在板子上触发一帧，并在 F_WAIT 超时之前高频采样调试寄存器。
   目的：区分「CFAR 根本没出 valid」和「CCL 收到了但没出结果」。
   关键：chain_rst_n 只在 F_FEED/F_WAIT 期间为 1，一旦超时进 F_FIN 整链复位，
        此时读 DBG 一定是 0（之前的误判就出在这里）。
"""
import mmap, os, struct, sys, time

AXI_BASE   = 0x43C00000
UMB        = "/dev/udmabuf0"
UMB_SIZE   = 0xF00000 + 0x1000          # 结果区在 +0xF00000
W, H       = 640, 360
NPIX       = W * H

R_CTRL   = 0x00
R_FADDR  = 0x04
R_RADDR  = 0x08
R_STATUS = 0x0C
R_FID    = 0x10
R_VER    = 0x14
R_PCOUNT = 0x18
R_STAT1  = 0x1C   # {fifo_level[15:0], 5'd0, fst[2:0], err_code[7:0]}
R_CCL    = 0x20   # {8'd0, ch_dbg_px[17:0], 3'd0, ch_dbg_state[2:0]}
R_HAND   = 0x24   # {ocount[5:0], ch_o_valid, rd_done, rd_error, wr_done, wr_error, 21'd0}

FST = {0: "IDLE", 1: "RST", 2: "FILL", 3: "FEED", 4: "WAIT", 5: "WRITE", 6: "FIN"}


def main():
    fa = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
    ax = mmap.mmap(fa, 0x1000, offset=AXI_BASE)

    def rd(o):
        return struct.unpack_from("<I", ax, o)[0]

    def wr(o, v):
        struct.pack_into("<I", ax, o, v & 0xFFFFFFFF)

    uf = os.open(UMB, os.O_RDWR | os.O_SYNC)
    um = mmap.mmap(uf, UMB_SIZE, offset=0)

    # ---------- 1) 往 udmabuf0 写测试图案（与仿真基线一致）----------
    img = bytearray(NPIX)
    for y in range(H):
        base = y * W
        for x in range(W):
            img[base + x] = 8 + ((x >> 6) & 0x0F)
    for (cx, cy) in ((106, 72), (106, 216), (320, 72), (320, 216)):
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                img[(cy + dy) * W + (cx + dx)] = 240
    for y in range(10, 50):
        for x in range(440, 480):
            img[y * W + x] = 200
    um[0:NPIX] = img
    print("IMG OK  frame=0x%08X result=0x%08X ver=0x%08X"
          % (rd(R_FADDR), rd(R_RADDR), rd(R_VER)))

    # ---------- 2) 触发 ----------
    rd(R_STATUS)          # 清 done
    wr(R_FID, 1)
    wr(R_CTRL, 1)

    # ---------- 3) 高频采样（覆盖 IDLE→FEED→WAIT→超时）----------
    t0 = time.time()
    print("  t(ms)  ST          FST    err  fifo    pcount   ccl_st px     ocount ovalid")
    hi_px, hi_oc = 0, 0
    for _ in range(60):
        st = rd(R_STATUS)
        s1 = rd(R_STAT1)
        ccl = rd(R_CCL)
        hd = rd(R_HAND)
        pc = rd(R_PCOUNT)
        fifo_lv = (s1 >> 16) & 0xFFFF
        fst = (s1 >> 8) & 0x7
        err = s1 & 0xFF
        cst = ccl & 0x7
        cpx = (ccl >> 11) & 0x3FFFF
        oc = (hd >> 26) & 0x3F
        ov = (hd >> 25) & 1
        hi_px = max(hi_px, cpx)
        hi_oc = max(hi_oc, oc)
        print("%8.1f  0x%08X  %-6s %3d  %6d  %8d  %3d   %6d  %2d  %d"
              % ((time.time() - t0) * 1000, st, FST.get(fst, "?"), err,
                 fifo_lv, pc, cst, cpx, oc, ov))
        if (st & 0x7) == 0 and (st >> 2 & 1) == 0 and err:
            break
        time.sleep(0.02)

    print("--- 峰值：ch_dbg_px=%d  ocount=%d ---" % (hi_px, hi_oc))

    # ---------- 4) 读结果区（成功时才有内容）----------
    st = rd(R_STATUS)
    print("END ST=0x%08X done=%d busy=%d err=%d ncand=%d"
          % (st, (st >> 1) & 1, st & 1, (st >> 2) & 1, (st >> 8) & 0xFF))
    if (st >> 1) & 1:
        res = um[UMB_SIZE - 0x1000:UMB_SIZE - 0x1000 + 64]
        print("RES:", " ".join("%02X" % b for b in res[:40]))
        print("ncand=%d" % res[0])


if __name__ == "__main__":
    main()
