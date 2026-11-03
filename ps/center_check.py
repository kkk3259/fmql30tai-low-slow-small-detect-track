#!/usr/bin/env python3
# center_check.py —— 质心坐标专项：不同边长 × 不同位置，验证 area*x 不再溢出
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
    open("/sys/class/u-dma-buf/udmabuf0/sync_offset", "w").write("0\n")
    open("/sys/class/u-dma-buf/udmabuf0/sync_size", "w").write(str(W * H) + "\n")

    def rd(o):
        return struct.unpack("<I", reg[o:o + 4])[0]

    def wr(o, v):
        struct.pack_into("<I", reg, o, v & 0xFFFFFFFF)

    wr(0x04, 0x30100000)
    wr(0x08, 0x31000000)
    print("VERSION=0x%08X" % rd(0x14))

    def run(img):
        um[0:W * H] = img.astype(np.uint8).tobytes()
        open("/sys/class/u-dma-buf/udmabuf0/sync_for_device", "w").write("1\n")
        wr(0x00, 1)
        t0 = time.time()
        st = 0
        while True:
            st = rd(0x0C)
            if st & 0x6 or time.time() - t0 > 2:
                break
        b = []
        for i in range(9):
            w = rd(0x18 + 4 * i)
            b += [(w >> (8 * k)) & 0xFF for k in range(4)]
        n = b[0]
        c = []
        for j in range(min(n, 5)):
            o = 1 + 7 * j
            c.append((((b[o] << 8) | b[o + 1]), ((b[o + 2] << 8) | b[o + 3]), ((b[o + 4] << 8) | b[o + 5]), b[o + 6]))
        return st, (time.time() - t0) * 1000, n, c

    print("\n%6s %10s | %-30s %s" % ("边长", "目标中心", "PL 报回 (x,y,area,peak)", "判定"))
    cases = []
    for side in (8, 16, 32, 48, 64):
        for (cx, cy) in ((320, 180), (560, 180), (560, 320), (80, 320)):
            x0 = max(0, min(W - side, cx - side // 2))
            y0 = max(0, min(H - side, cy - side // 2))
            cases.append((side, x0 + side // 2, y0 + side // 2, x0, y0))
    for (side, ecx, ecy, x0, y0) in cases:
        img = np.full((H, W), 40, np.uint8)
        img[y0:y0 + side, x0:x0 + side] = 240
        st, ms, n, c = run(img)
        if not c:
            print("%6d (%3d,%3d) | %-30s 未检出" % (side, ecx, ecy, "-"))
            continue
        best = max(c, key=lambda t: t[2])
        ok = (abs(best[0] - ecx) <= 2) and (abs(best[1] - ecy) <= 2)
        print("%6d (%3d,%3d) | (%3d,%3d,a=%4d,p=%3d)%s %.1fms n=%d" % (
            side, ecx, ecy, best[0], best[1], best[2], best[3], "  OK" if ok else "  <-- 错", ms, n))


if __name__ == "__main__":
    main()
