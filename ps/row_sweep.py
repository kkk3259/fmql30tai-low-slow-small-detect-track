#!/usr/bin/env python3
# row_sweep.py —— 竖直方向定位检查：把同一个目标放到不同的 y，看 PL 报回来的 y 对不对
# 说明：本版直接用 0x18~0x38 的“兼容视图”（9 个 32 位字 = 36 字节），不写任何窗口索引寄存器，
#       避免把 0x10（FRAME_ID）误当窗口地址。
import mmap
import os
import struct
import time

import numpy as np

W, H = 640, 360
BASE = 0x43C00000
FRAME_OFF = 0


def main():
    fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
    reg = mmap.mmap(fd, 4096, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=BASE)
    size = int(open("/sys/class/u-dma-buf/udmabuf0/size").read().strip())
    bfd = os.open("/dev/udmabuf0", os.O_RDWR | os.O_SYNC)
    um = mmap.mmap(bfd, size, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)
    open("/sys/class/u-dma-buf/udmabuf0/sync_offset", "w").write(str(FRAME_OFF) + "\n")
    open("/sys/class/u-dma-buf/udmabuf0/sync_size", "w").write(str(W * H) + "\n")

    def rd(o):
        return struct.unpack("<I", reg[o:o + 4])[0]

    def wr(o, v):
        struct.pack_into("<I", reg, o, v & 0xFFFFFFFF)

    wr(0x04, 0x30100000 + FRAME_OFF)
    wr(0x08, 0x30100000 + 0xF00000)
    print("VERSION=0x%08X" % rd(0x14))

    def run(img):
        um[FRAME_OFF:FRAME_OFF + W * H] = img.astype(np.uint8).tobytes()
        open("/sys/class/u-dma-buf/udmabuf0/sync_for_device", "w").write("1\n")
        wr(0x00, 1)
        t0 = time.time()
        st = 0
        while True:
            st = rd(0x0C)
            if st & 0x6 or time.time() - t0 > 2:
                break
        ms = (time.time() - t0) * 1000
        b = []
        for i in range(9):
            w = rd(0x18 + 4 * i)
            b += [(w >> (8 * k)) & 0xFF for k in range(4)]
        n = b[0]
        cands = []
        for c in range(min(n, 5)):
            o = 1 + 7 * c
            cands.append((((b[o] << 8) | b[o + 1]), ((b[o + 2] << 8) | b[o + 3]), ((b[o + 4] << 8) | b[o + 5]), b[o + 6]))
        return st, ms, n, cands

    print("\n%8s %8s | %-34s %s" % ("目标(x,y)", "边长", "PL 报回 (x,y,area,peak)", "耗时"))
    for side in (8, 16):
        for ty in (20, 60, 100, 140, 180, 220, 260, 300, 340):
            tx = 320
            img = np.full((H, W), 40, np.uint8)
            y0 = max(0, ty - side // 2)
            x0 = max(0, tx - side // 2)
            img[y0:y0 + side, x0:x0 + side] = 240
            st, ms, n, cands = run(img)
            best = sorted(cands, key=lambda c: -c[2])[:2]
            s = "; ".join("(%d,%d,a=%d,p=%d)" % c for c in best) or "无"
            print("%8s %8d | %-34s %.1f ms n=%d" % ("(%d,%d)" % (tx, ty), side, s, ms, n))


if __name__ == "__main__":
    main()
