#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""seq_test.py —— 连续多帧一致性测试（三域位流）。

对同一张图连跑 N 帧，每帧单独打印 AR 增量与候选，用来判定：
  - 帧到底跑没跑（看 AR 增量，不看 done 位）
  - 连续帧结果是否稳定（有没有"第二帧读到旧表"）
"""
import sys
import time

REG = 0x400C0000
R_CTRL, R_FADDR, R_RADDR, R_STATUS = 0x00, 0x04, 0x08, 0x0C
R_WIN, R_AR, R_RV = 0x10, 0x90, 0x94
NPIX = 640 * 360


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "/root/ip2/vs_300.png"
    nframe = int(sys.argv[2]) if len(sys.argv) > 2 else 4

    import cv2
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        print("FLAG read_fail")
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

    for k in range(nframe):
        a0 = reg.read(REG + R_AR) & 0xFFFFFFFF
        reg.write(REG + R_CTRL, 0)
        time.sleep(0.01)
        reg.write(REG + R_CTRL, 1)
        time.sleep(0.05)
        a1 = reg.read(REG + R_AR) & 0xFFFFFFFF
        st = reg.read(REG + R_STATUS) & 0xFFFFFFFF
        grew = a1 - a0
        print("FRAME %d  AR+=%d  %s  STATUS=0x%08X n=%d"
              % (k, grew, "RAN" if grew > 3000 else "NOT_RUN", st, (st >> 8) & 0xFF))
        # 读第 4 条（跳过 pad 带的 4 条）
        words = []
        for i in range(16):
            reg.write(REG + R_WIN, i)
            reg.read(REG + R_WIN)
            words.append(reg.read(REG + R_WIN) & 0xFFFFFFFF)
        flat = []
        for w in words:
            flat += [(w >> s) & 0xFF for s in (0, 8, 16, 24)]
        for j in range(1, min(9, len(flat) // 7 + 1)):
            b = flat[1 + (j - 1) * 7: 1 + j * 7]
            if len(b) < 7:
                break
            print("    #%d x=%d y=%d area=%d peak=%d"
                  % (j - 1, (b[0] << 8) | b[1], (b[2] << 8) | b[3],
                     (b[4] << 8) | b[5], b[6]))


if __name__ == "__main__":
    main()
