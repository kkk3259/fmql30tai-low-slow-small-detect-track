#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dump_table.py —— 把三域候选表按字读回来打成十六进制，用于核对记录布局。"""
import sys
import time
import cv2

REG = 0x400C0000
R_CTRL, R_FADDR, R_RADDR, R_STATUS = 0x00, 0x04, 0x08, 0x0C
R_WIN = 0x10
R_AR, R_RV, R_WD = 0x90, 0x94, 0x98
NPIX = 640 * 360
NW = 32


def rdw(reg, off):
    return reg.read(REG + off) & 0xFFFFFFFF


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "/root/ip2/vlines.png"
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        print("读不到", path)
        return
    if img.shape[:2] != (360, 640):
        img = cv2.resize(img, (640, 360), interpolation=cv2.INTER_AREA)

    from icraft.xrt import Device
    dev = Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
    reg = dev.defaultRegRegion()
    mem = dev.defaultMemRegion()
    ch = mem.malloc(NPIX)
    ch.write(0, img.tobytes(), NPIX)
    bp = ch.begin if not callable(ch.begin) else ch.begin()
    ad = getattr(bp, "addr", None)
    base = ad() if callable(ad) else ad
    reg.write(REG + R_FADDR, base)
    reg.write(REG + R_RADDR, base)
    time.sleep(0.02)

    for _ in range(4):
        a0 = rdw(reg, R_AR)
        reg.write(REG + R_CTRL, 0)
        time.sleep(0.005)
        reg.write(REG + R_CTRL, 1)
        time.sleep(0.030)
        if (rdw(reg, R_AR) - a0) > 100:
            break
    st = rdw(reg, R_STATUS)
    print("STATUS = 0x%08X  done=%d err=%d n_cand=%d" % (st, st & 1, (st >> 2) & 1, (st >> 8) & 0xFF))

    words = []
    for i in range(NW):
        reg.write(REG + R_WIN, i)
        reg.read(REG + R_WIN)
        words.append(rdw(reg, R_WIN))

    print("\n== 原始 32 字（小端字节序展开）==")
    for i, w in enumerate(words):
        bs = [(w >> s) & 0xFF for s in (0, 8, 16, 24)]
        print("W%02d 0x%08X  %s" % (i, w, " ".join("%3d" % b for b in bs)))

    print("\n== 按字节线性排列（前 60 字节）==")
    flat = []
    for w in words:
        flat += [(w >> s) & 0xFF for s in (0, 8, 16, 24)]
    for i in range(0, 60, 12):
        print("  [%02d] %s" % (i, " ".join("%3d" % b for b in flat[i:i + 12])))

    print("\n== 按 n + 7字节/条 解释 ==")
    n = flat[0]
    print("  n_cand(byte0) = %d" % n)
    for k in range(min(n, 8)):
        b = flat[1 + k * 7: 1 + (k + 1) * 7]
        if len(b) < 7:
            break
        print("  #%d bytes=%s  -> x=%d y=%d area=%d peak=%d"
              % (k, b, (b[0] << 8) | b[1], (b[2] << 8) | b[3], b[5], b[6]))


if __name__ == "__main__":
    main()
