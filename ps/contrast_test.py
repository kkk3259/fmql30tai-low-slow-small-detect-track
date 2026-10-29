#!/usr/bin/env python3
# contrast_test.py —— 固定目标尺寸、改变对比度，验证“CFAR 门限随对比度上升”的假设
import ctypes
import mmap
import os
import struct
import sys
import time

import numpy as np

W, H = 640, 360
BASE = 0x43C00000
R_CTRL, R_STAT, R_FADDR, R_RADDR, R_FID, R_VER = 0x00, 0x0C, 0x04, 0x08, 0x10, 0x14
R_LEG = 0x18
BUF = "/dev/udmabuf0"
FRAME_OFF, RES_OFF = 0, 0xF00000


def rd(buf, off):
    return struct.unpack("<I", buf[off:off + 4])[0]


def wr(buf, off, val):
    struct.pack_into("<I", buf, off, val & 0xFFFFFFFF)


def main():
    libc = ctypes.CDLL("libc.so.6", use_errno=True)
    fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
    reg = mmap.mmap(fd, 4096, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE,
                    offset=BASE)
    size = int(open("/sys/class/u-dma-buf/udmabuf0/size").read().strip())
    bfd = os.open(BUF, os.O_RDWR | os.O_SYNC)
    um = mmap.mmap(bfd, size, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)

    with open("/sys/class/u-dma-buf/udmabuf0/sync_size", "w") as f:
        f.write(str(W * H) + "\n")
    with open("/sys/class/u-dma-buf/udmabuf0/sync_offset", "w") as f:
        f.write(str(FRAME_OFF) + "\n")

    wr(reg, R_FADDR, 0x30100000 + FRAME_OFF)
    wr(reg, R_RADDR, 0x30100000 + RES_OFF)
    print("VERSION = 0x%08X" % rd(reg, R_VER))

    def run(img):
        um[FRAME_OFF:FRAME_OFF + W * H] = img.astype(np.uint8).tobytes()
        with open("/sys/class/u-dma-buf/udmabuf0/sync_for_device", "w") as f:
            f.write("1\n")
        wr(reg, R_CTRL, 1)
        t0 = time.time()
        while True:
            st = rd(reg, R_STAT)
            if st & 0x2 or st & 0x4:
                break
            if time.time() - t0 > 2.0:
                return None, None, -1
        ms = (time.time() - t0) * 1000
        n = rd(reg, R_LEG) & 0xFF
        cands = []
        for i in range(min(n, 5)):
            v = [rd(reg, R_LEG + 4 * i + 4)]
            b = struct.pack("<I", v[0])
            hi, lo = b[0], b[1]
            x = (hi << 8) | lo if False else None
        # 兼容视图本身是“每字 4 字节 = 一个候选的 4 个字节”，读错了，改用窗口
        return n, ms, st

    def run2(img):
        um[FRAME_OFF:FRAME_OFF + W * H] = img.astype(np.uint8).tobytes()
        with open("/sys/class/u-dma-buf/udmabuf0/sync_for_device", "w") as f:
            f.write("1\n")
        wr(reg, R_CTRL, 1)
        t0 = time.time()
        while True:
            st = rd(reg, R_STAT)
            if st & 0x2 or st & 0x4:
                break
            if time.time() - t0 > 2.0:
                return None, -1, -1
        ms = (time.time() - t0) * 1000
        n = rd(reg, R_LEG) & 0xFF
        cands = []
        for i in range(min(n, 8)):
            wr(reg, R_LEG + 4, 0)   # 0x1C = 窗口数据
            wr(reg, 0x1C, i)
            wr_bytes = []
            for k in range(7):
                wr(reg, 0x1C, i * 7 + k)
                wr_bytes.append(rd(reg, 0x1C) & 0xFF)
            if len(wr_bytes) >= 6 and wr_bytes[6] > 0:
                x = (wr_bytes[0] << 8) | wr_bytes[1]
                y = (wr_bytes[2] << 8) | wr_bytes[3]
                area = (wr_bytes[4] << 8) | wr_bytes[5]
                cands.append((x, y, area, wr_bytes[6]))
        return n, ms, cands

    for size_px in (10, 12, 15, 20, 25):
        for fg, bg in ((240, 40), (200, 100), (160, 110), (120, 90), (100, 80)):
            img = np.full((H, W), bg, np.uint8)
            a = size_px // 2
            img[180 - a:180 - a + size_px, 320 - a:320 - a + size_px] = fg
            n, ms, cands = run2(img)
            if n is None:
                print("size=%2d C=%3d : TIMEOUT" % (size_px, fg - bg))
            else:
                hit = [c for c in cands if abs(c[0] - 320) < 60 and abs(c[1] - 180) < 60]
                print("size=%2d C=%3d : n=%d %.1fms 命中=%s"
                      % (size_px, fg - bg, n, ms, hit[:2] if hit else "无"))


if __name__ == "__main__":
    main()
