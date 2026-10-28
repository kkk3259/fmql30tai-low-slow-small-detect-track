#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_one.py —— 一次只放一个实心方块，隔离「尺寸」这一个变量

用法（板子）:
  python3 probe_one.py 3 10 20     # 依次测 3px / 10px / 20px
"""
import mmap
import os
import struct
import sys
import time

W, H = 640, 360
NPIX = W * H
N_CAND = 64
TAB_WORDS = (1 + N_CAND * 7 + 3) // 4

R_CTRL = 0x00
R_STATUS = 0x0C
R_VER = 0x14
R_CIDX = 0x10
R_CDAT = 0x10

UIO = "/dev/udmabuf0"
SYS = "/sys/class/u-dma-buf/udmabuf0"


def sync(name, val):
    try:
        with open(os.path.join(SYS, name), "w") as f:
            f.write(str(val))
    except Exception:
        pass


def main():
    sizes = [int(a) for a in sys.argv[1:]] or [3, 6, 10, 20, 30]
    reg = mmap.mmap(os.open("/dev/mem", os.O_RDWR | os.O_SYNC), 4096, offset=0x43C00000)

    def rd(o):
        return struct.unpack_from("<I", reg, o)[0]

    def wr(o, v):
        struct.pack_into("<I", reg, o, v & 0xFFFFFFFF)

    print("PL VERSION = 0x%08X" % rd(R_VER))
    fd = os.open(UIO, os.O_RDWR)
    buf = mmap.mmap(fd, NPIX, offset=0)
    cx, cy = 320, 180

    for s in sizes:
        buf[:] = bytes([8]) * NPIX
        x0 = cx - s // 2
        y0 = cy - s // 2
        for yy in range(y0, y0 + s):
            for xx in range(x0, x0 + s):
                buf[yy * W + xx] = 240
        sync("sync_offset", 0)
        sync("sync_size", NPIX)
        sync("sync_for_device", 1)

        wr(R_CTRL, 1)
        t0 = time.time()
        st = 0
        while (time.time() - t0) < 2.0:
            st = rd(R_STATUS)
            if st & 0x06:
                break
        dt = (time.time() - t0) * 1000.0

        words = []
        for i in range(TAB_WORDS):
            wr(R_CIDX, i)
            words.append(rd(R_CDAT))
        raw = b"".join(struct.pack("<I", w) for w in words)
        n = raw[0]
        got = []
        for i in range(min(n, N_CAND)):
            b = raw[1 + i * 7: 8 + i * 7]
            if len(b) < 7:
                break
            got.append(((b[0] << 8) | b[1], (b[2] << 8) | b[3], b[5], b[6]))
        near = [(x, y, a, p) for (x, y, a, p) in got if abs(x - cx) <= 4 and abs(y - cy) <= 4]
        print("边长 %2d px -> n_cand=%d  用时 %.1f ms  中心处候选: %s"
              % (s, n, dt, near if near else "无"))


if __name__ == "__main__":
    main()
