#!/usr/bin/env python3
# size_sweep_ms.py —— 多尺度验证：全分辨率 vs 2x 降采样画布，看各自能检出多大
# 做法：目标画在全分辨率 640x360 上；A 组直接用；B 组降采样 2x 放进 320x180，其余填 0，
#       触发后把坐标 x2、面积 x4 映回原尺度。
import mmap
import os
import struct
import time

import cv2
import numpy as np

W, H = 640, 360
BASE = 0x43C00000


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
        ms = (time.time() - t0) * 1000
        b = []
        for i in range(9):
            w = rd(0x18 + 4 * i)
            b += [(w >> (8 * k)) & 0xFF for k in range(4)]
        n = b[0]
        c = []
        for j in range(min(n, 5)):
            o = 1 + 7 * j
            c.append((((b[o] << 8) | b[o + 1]), ((b[o + 2] << 8) | b[o + 3]), ((b[o + 4] << 8) | b[o + 5]), b[o + 6]))
        return ms, n, c

    print("\n%5s | %-24s | %-24s | %-24s" % ("边长", "A 全分辨率", "B 2x→映回", "C 3x→映回"))
    for side in (2, 4, 6, 8, 12, 15, 20, 24, 30, 40, 50, 60, 70):
        tx, ty = 320, 180
        img = np.full((H, W), 40, np.uint8)
        x0 = tx - side // 2
        y0 = ty - side // 2
        img[y0:y0 + side, x0:x0 + side] = 240

        # A：全分辨率
        msA, nA, cA = run(img)
        sA = "未检出"
        if cA:
            b = max(cA, key=lambda t: t[2])
            sA = "(%d,%d,a=%d) %s" % (b[0], b[1], b[2], "OK" if abs(b[0] - tx) <= 3 and abs(b[1] - ty) <= 3 else "偏离")

        # B：2x 降采样画布
        small = cv2.resize(img, (W // 2, H // 2), interpolation=cv2.INTER_AREA)
        canvas = np.zeros((H, W), np.uint8)
        canvas[0:H // 2, 0:W // 2] = small
        msB, nB, cB = run(canvas)
        sB = "未检出"
        if cB:
            mx = max(cB, key=lambda t: t[2])
            # 映回原尺度：坐标 x2，面积 x4
            ox, oy, oa = mx[0] * 2 + 1, mx[1] * 2 + 1, mx[2] * 4
            sB = "(%d,%d,a=%d) %s" % (ox, oy, oa, "OK" if abs(ox - tx) <= 6 and abs(oy - ty) <= 6 else "偏离")
        # C：3x 降采样画布（覆盖 20~60px）
        sw, sh = W // 3, H // 3
        small3 = cv2.resize(img, (sw, sh), interpolation=cv2.INTER_AREA)
        canvas3 = np.zeros((H, W), np.uint8)
        canvas3[0:sh, 0:sw] = small3
        msC, nC, cC = run(canvas3)
        sC = "未检出"
        if cC:
            mz = max(cC, key=lambda t: t[2])
            ox, oy, oa = mz[0] * 3 + 1, mz[1] * 3 + 1, mz[2] * 9
            sC = "(%d,%d,a=%d) %s" % (ox, oy, oa, "OK" if abs(ox - tx) <= 9 and abs(oy - ty) <= 9 else "偏离")
        print("%5d | %-24s | %-24s | %-24s" % (side, sA, sB, sC))


if __name__ == "__main__":
    main()
