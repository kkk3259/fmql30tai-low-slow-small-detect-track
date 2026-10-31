#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t3d.py —— 三域位流板上实测：跑一帧 + 读候选 + 读 raw 快照。

用法: t3d.py <img.png> [raw_word_index]
"""
import sys
import time
import cv2

REG = 0x400C0000
R_CTRL, R_FADDR, R_RADDR, R_STATUS = 0x00, 0x04, 0x08, 0x0C
R_WIN, R_AR, R_RV, R_WD = 0x10, 0x90, 0x94, 0x98
R_SNAP1, R_SNAP2 = 0xC0, 0xC4
R_CAPIDX, R_CAPDATA = 0xB4, 0xB8
NPIX = 640 * 360


def rdw(reg, off):
    return reg.read(REG + off) & 0xFFFFFFFF


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "/root/ip2/card_synth.png"
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        print("读不到", path)
        return
    if img.shape[:2] != (360, 640):
        img = cv2.resize(img, (640, 360), interpolation=cv2.INTER_AREA)
    print("图像 %s  %dx%d  灰度 %d~%d" % (path.split("/")[-1], img.shape[1], img.shape[0],
                                          img.min(), img.max()))

    from icraft.xrt import Device
    dev = Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
    reg = dev.defaultRegRegion()
    mem = dev.defaultMemRegion()
    print("VERSION = 0x%08X" % rdw(reg, 0x14))

    ch = mem.malloc(NPIX)
    ch.write(0, img.tobytes(), NPIX)
    bp = ch.begin if not callable(ch.begin) else ch.begin()
    ad = getattr(bp, "addr", None)
    base = ad() if callable(ad) else ad
    reg.write(REG + R_FADDR, base)
    reg.write(REG + R_RADDR, base)
    time.sleep(0.02)

    st = 0
    for attempt in range(4):
        a0 = rdw(reg, R_AR)
        t0 = time.time()
        reg.write(REG + R_CTRL, 0)
        time.sleep(0.005)
        reg.write(REG + R_CTRL, 1)
        time.sleep(0.030)
        if (rdw(reg, R_AR) - a0) > 100:
            break
        print("  第 %d 次触发 AR 没涨，重试" % (attempt + 1))
    for _ in range(3000):
        st = rdw(reg, R_STATUS)
        if st & 1:
            break
        time.sleep(0.001)
    dt = (time.time() - t0) * 1000
    ar = rdw(reg, R_AR) - a0
    rv = rdw(reg, R_RV)
    print("STATUS = 0x%08X  done=%d err=%d n_cand=%d  用时 %.1f ms  AR+%d RV=%d"
          % (st, st & 1, (st >> 2) & 1, (st >> 8) & 0xFF, dt, ar, rv))

    # 候选（113 字窗口：写索引读同一地址）
    n = (st >> 8) & 0xFF
    if 1 <= n <= 8:
        reg.write(REG + R_WIN, 0)
        blob = []
        for i in range((1 + 8 * 7 + 3) // 4):
            reg.write(REG + R_WIN, i)
            reg.read(REG + R_WIN)
            blob += [(rdw(reg, R_WIN) >> s) & 0xFF for s in (0, 8, 16, 24)]
        print("表头 n = %d" % blob[0])
        for k in range(min(blob[0], 8)):
            b = blob[1 + k * 7: 1 + (k + 1) * 7]
            print("  #%d x=%d y=%d area=%d peak=%d"
                  % (k, (b[0] << 8) | b[1], (b[2] << 8) | b[3], b[4], b[5]))

    # raw 快照（若位流支持）
    for w in range(8):
        try:
            reg.write(REG + R_SNAP1, w)
            v = rdw(reg, R_SNAP2)
        except Exception:
            break
        if w == 0 or v:
            print("  snap[%d] = 0x%08X" % (w, v))


if __name__ == "__main__":
    main()
