#!/usr/bin/env python3
# raw_dump.py —— 画一个 8x8 亮点，把候选表原样打出来（十六进制），用来判断解码是否错
import mmap
import os
import struct
import time

import numpy as np

W, H = 640, 360
BASE = 0x43C00000
FRAME_OFF, RES_OFF = 0, 0xF00000


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
    wr(0x08, 0x30100000 + RES_OFF)
    print("VERSION=0x%08X  FADDR=0x%08X  RADDR=0x%08X" % (rd(0x14), rd(0x04), rd(0x08)))

    for (tx, ty) in ((320, 180),):
        img = np.full((H, W), 40, np.uint8)
        img[ty:ty + 8, tx:tx + 8] = 240
        um[FRAME_OFF:FRAME_OFF + W * H] = img.astype(np.uint8).tobytes()
        open("/sys/class/u-dma-buf/udmabuf0/sync_for_device", "w").write("1\n")
        wr(0x00, 1)
        t0 = time.time()
        while True:
            st = rd(0x0C)
            if st & 0x6:
                break
            if time.time() - t0 > 2:
                break
        print("目标 (%d,%d)  8x8  STATUS=0x%08X  耗时 %.1f ms" % (tx, ty, st, (time.time() - t0) * 1000))
        words = [rd(0x18 + 4 * i) for i in range(9)]
        print("legacy 0x18..0x38:")
        for i, w in enumerate(words):
            print("  [%d] 0x%08X  bytes=%s" % (i, w, " ".join("%02X" % ((w >> (8 * k)) & 0xFF) for k in range(4))))
        b = []
        for w in words:
            b += [(w >> (8 * k)) & 0xFF for k in range(4)]
        print("36 字节:", " ".join("%02X" % x for x in b[:36]))
        n = b[0]
        print("n_cand =", n)
        for c in range(min(n, 5)):
            o = 1 + 7 * c
            print("  cand%d: x=%d y=%d area=%d peak=%d" % (c, (b[o] << 8) | b[o + 1], (b[o + 2] << 8) | b[o + 3], b[o + 5], b[o + 6]))


if __name__ == "__main__":
    main()
