#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_sizes.py —— 用 SE=21 的结构元量一遍「能检出多大的目标」

背景：Top-Hat 开运算会把「比结构元大的亮块」当背景抹掉，所以 SE=21 只能输出
边长 <= 20 px 的目标；CCL 还有面积门限 MIN_AREA=2 / MAX_AREA=200。

为了把「结构元做不到」和「面积门限滤掉」区分开，除了实心方块还放了空心方框
（边框 1 px 厚，面积远小于实心，能通过面积门限）。

用法（板子）: python3 probe_sizes.py
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
R_CIDX = 0x40          # 写：候选表字索引（注意 0x10 是 FRAME_ID，早期此处写错成 0x10）
R_CDAT = 0x44          # 读：该字数据

UIO = "/dev/udmabuf0"
SYS = "/sys/class/u-dma-buf/udmabuf0"
SHIFT = 0xF00000

# (中心 x, 中心 y, 边长, 是否空心, 说明)
TARGETS = [
    (70, 60, 3, False, "实心 3px  area=9"),
    (180, 60, 6, False, "实心 6px  area=36"),
    (300, 60, 10, False, "实心 10px area=100"),
    (430, 60, 20, False, "实心 20px area=400(超面积上限)"),
    (560, 60, 30, False, "实心 30px area=900(超上限+超结构元)"),
    (70, 250, 20, True, "空心 20px 边框 area=76"),
    (300, 250, 30, True, "空心 30px 边框 area=116(边长超 SE-1)"),
    (520, 250, 10, True, "空心 10px 边框 area=36"),
]


def sync(name, val):
    try:
        with open(os.path.join(SYS, name), "w") as f:
            f.write(str(val))
    except Exception:
        pass


def gen_image(buf):
    buf[:] = bytes([8]) * NPIX
    for (cx, cy, s, hollow, _d) in TARGETS:
        x0 = cx - s // 2
        y0 = cy - s // 2
        for yy in range(y0, y0 + s):
            if not (0 <= yy < H):
                continue
            for xx in range(x0, x0 + s):
                if not (0 <= xx < W):
                    continue
                edge = (xx == x0 or xx == x0 + s - 1 or yy == y0 or yy == y0 + s - 1)
                if hollow and not edge:
                    continue
                buf[yy * W + xx] = 240


def main():
    reg = mmap.mmap(os.open("/dev/mem", os.O_RDWR | os.O_SYNC), 4096, offset=0x43C00000)

    def rd(o):
        return struct.unpack_from("<I", reg, o)[0]

    def wr(o, v):
        struct.pack_into("<I", reg, o, v & 0xFFFFFFFF)

    print("PL VERSION = 0x%08X" % rd(R_VER))
    fd = os.open(UIO, os.O_RDWR)
    buf = mmap.mmap(fd, NPIX, offset=0)
    gen_image(buf)
    print("已生成 %d 个目标" % len(TARGETS))
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
    print("STATUS = 0x%08X  done=%d err=%d n_cand=%d  用时 %.1f ms"
          % (st, (st >> 1) & 1, (st >> 2) & 1, (st >> 8) & 0xFF, dt))

    got = []
    for i in range(min(n, N_CAND)):
        b = raw[1 + i * 7: 8 + i * 7]
        if len(b) < 7:
            break
        got.append((((b[0] << 8) | b[1], (b[2] << 8) | b[3], (b[4] << 8) | b[5], b[6])))
    for (x, y, a, pk) in got:
        print("  (%3d,%3d) area=%d peak=%d" % (x, y, a, pk))

    print("\n%-42s %s" % ("目标", "检出"))
    hit = 0
    for (cx, cy, s, hollow, desc) in TARGETS:
        ok = any(abs(x - cx) <= 3 and abs(y - cy) <= 3 for (x, y, a, pk) in got)
        hit += 1 if ok else 0
        print("  %-42s %s" % (desc, "YES" if ok else "-"))
    print("\n共检出 %d / %d" % (hit, len(TARGETS)))
    print("VERDICT SIZE-SCAN-DONE")


if __name__ == "__main__":
    main()
