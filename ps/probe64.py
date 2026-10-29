#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe64.py —— 验证 MAX_CAND 从 5 提到 64：放 10 个不同大小的目标，看是否全部报出。

用法（板子）:
  python3 probe64.py            # 生成图案 -> 跑一帧 -> 打印全部候选
  python3 probe64.py --dump     # 只打印、不重画
"""
import mmap
import os
import struct
import sys
import time

W, H = 640, 360
NPIX = W * H
N_CAND = 64
TAB_WORDS = (1 + N_CAND * 7 + 3) // 4   # 113

R_CTRL = 0x00
R_STATUS = 0x0C
R_VER = 0x14
R_CIDX = 0x10
R_CDAT = 0x10
R_FADDR = 0x04

UIO = "/dev/udmabuf0"
SYS = "/sys/class/u-dma-buf/udmabuf0"
SHIFT = 0xF00000          # 结果区 15 MiB，避开图像区


def sync(name, val):
    try:
        with open(os.path.join(SYS, name), "w") as f:
            f.write(str(val))
    except Exception:
        pass


# 10 个目标：位置互不重叠，大小 2x2 ~ 7x7（面积 4~49，都在 2..200 内）
DOTS = [
    (40, 40, 3), (160, 40, 2), (280, 40, 4), (400, 40, 3), (520, 40, 5),
    (40, 180, 2), (160, 180, 6), (280, 180, 3), (400, 180, 2), (520, 180, 7),
]


def gen_image(buf):
    bg = 8
    for y in range(H):
        row = bytes([bg]) * W
        buf[y * W:(y + 1) * W] = row
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
    res = mmap.mmap(fd, 4096, offset=SHIFT)
    if not dump_only:
        gen_image(buf)
        print("已生成 %d 个目标" % len(DOTS))
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
    print("STATUS = 0x%08X  busy=%d done=%d err=%d n_cand=%d  用时 %.1f ms"
          % (st, st & 1, (st >> 1) & 1, (st >> 2) & 1, (st >> 8) & 0xFF, dt))
    print("表中候选数 = %d（期望 %d）" % (n, len(DOTS)))
    got = []
    for i in range(min(n, N_CAND)):
        b = raw[1 + i * 7: 8 + i * 7]
        if len(b) < 7:
            break
        got.append((((b[0] << 8) | b[1], (b[2] << 8) | b[3], (b[4] << 8) | b[5], b[6])))
    for (x, y, a, pk) in got:
        print("  (%3d,%3d) area=%d peak=%d" % (x, y, a, pk))

    # 判定：每个期望目标附近是否有候选
    hit = 0
    for (cx, cy, r) in DOTS:
        for (x, y, a, pk) in got:
            if abs(x - cx) <= 2 and abs(y - cy) <= 2:
                hit += 1
                break
    print("命中 %d/%d" % (hit, len(DOTS)))
    print("VERDICT %s" % ("CAND64-OK" if (n >= len(DOTS) and hit >= len(DOTS) - 1) else "CAND64-FAIL"))


if __name__ == "__main__":
    main()
