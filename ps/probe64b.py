#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe64b.py —— 真正验证 MAX_CAND=64：放 40 个「小于 5×5 结构元」的小亮点。
理论：结构元 5×5 只能检出 ≤4 px 的目标；40 个 2~4 px 的点应当全部报出。
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
R_CIDX = 0x40          # 写：字索引（读回索引）
R_CDAT = 0x44          # 读：该字
R_FADDR = 0x04

UIO = "/dev/udmabuf0"
SYS = "/sys/class/u-dma-buf/udmabuf0"


def sync(name, val):
    try:
        with open(os.path.join(SYS, name), "w") as f:
            f.write(str(val))
    except Exception:
        pass


# 40 个目标：8 列 × 5 行，尺寸 2~4 px（都小于 5×5 结构元）
DOTS = []
for r in range(5):
    for c in range(8):
        DOTS.append((45 + c * 70, 40 + r * 65, 2 + ((r * 8 + c) % 3)))


def gen_image(buf):
    buf[0:NPIX] = bytes([8]) * NPIX
    for (cx, cy, r) in DOTS:
        for yy in range(cy - r // 2, cy - r // 2 + r):
            if 0 <= yy < H:
                for xx in range(cx - r // 2, cx - r // 2 + r):
                    if 0 <= xx < W:
                        buf[yy * W + xx] = 240


def main():
    dump_only = "--dump" in sys.argv
    reg = mmap.mmap(os.open("/dev/mem", os.O_RDWR | os.O_SYNC), 4096, offset=0x43C00000)

    def rd(o):
        return struct.unpack_from("<I", reg, o)[0]

    def wr(o, v):
        struct.pack_into("<I", reg, o, v & 0xFFFFFFFF)

    print("PL VERSION = 0x%08X" % rd(R_VER))
    fd = os.open(UIO, os.O_RDWR)
    buf = mmap.mmap(fd, NPIX, offset=0)
    if not dump_only:
        gen_image(buf)
        print("已生成 %d 个目标" % len(DOTS))
    sync("sync_offset", 0)
    sync("sync_size", NPIX)
    sync("sync_for_device", 1)

    wr(R_CTRL, 1)
    t0 = time.time()
    st = 0
    while (time.time() - t0) < 3.0:
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
    print("STATUS = 0x%08X  busy=%d done=%d err=%d n_cand=%d  用时 %.1f ms"
          % (st, st & 1, (st >> 1) & 1, (st >> 2) & 1, (st >> 8) & 0xFF, dt))
    print("表中候选数 = %d（期望 %d）" % (n, len(DOTS)))
    got = []
    for i in range(min(n, N_CAND)):
        b = raw[1 + i * 7: 8 + i * 7]
        if len(b) < 7:
            break
        got.append((((b[0] << 8) | b[1], (b[2] << 8) | b[3], (b[4] << 8) | b[5], b[6])))
    hit = 0
    for (cx, cy, r) in DOTS:
        for (x, y, a, pk) in got:
            if abs(x - cx) <= 2 and abs(y - cy) <= 2:
                hit += 1
                break
    print("命中 %d/%d" % (hit, len(DOTS)))
    print("VERDICT %s" % ("CAND64-OK" if (n >= 35 and hit >= 35) else "CAND64-FAIL"))


if __name__ == "__main__":
    main()
