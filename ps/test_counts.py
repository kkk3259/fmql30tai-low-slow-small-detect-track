#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# test_counts.py —— 只读 STATUS（/dev/mem，永远非缓存），验证 CPU->PL 方向是否当帧生效
import os, sys, time, struct, mmap as MM

UDMA = "/dev/udmabuf0"
SYS  = "/sys/class/u-dma-buf/udmabuf0"
DEVMEM = "/dev/mem"
REG = 0x43C00000
W, H = 640, 360
NPIX = W * H
RES_OFF = 0xF00000


def sysfs(name, val=None):
    p = os.path.join(SYS, name)
    if val is None:
        with open(p) as f:
            return f.read().strip()
    with open(p, "w") as f:
        f.write(str(val))


def main():
    fd = os.open(UDMA, os.O_RDWR | os.O_SYNC)
    m = MM.mmap(fd, int(sysfs("size"), 0), MM.MAP_SHARED,
                prot=MM.PROT_READ | MM.PROT_WRITE)
    rfd = os.open(DEVMEM, os.O_RDWR | os.O_SYNC)
    reg = MM.mmap(rfd, 0x1000, MM.MAP_SHARED, offset=REG)

    def rd(o):
        return struct.unpack_from("<I", reg, o)[0]

    def wr(o, v):
        struct.pack_into("<I", reg, o, v & 0xFFFFFFFF)

    def wait_done(ms=3000):
        t0 = time.time()
        while (time.time() - t0) * 1000 < ms:
            st = rd(0x0C)
            if st & 0x06:
                return st
            time.sleep(0.002)
        return rd(0x0C)

    def build(dots):
        buf = bytearray(NPIX)
        for y in range(H):
            base = y * W
            v = 8 + ((y >> 4) & 15)
            buf[base:base + W] = bytes([v]) * W
        for (cx, cy) in dots:
            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    xx, yy = cx + dx, cy + dy
                    if 0 <= xx < W and 0 <= yy < H:
                        buf[yy * W + xx] = 240
        return bytes(buf)

    cases = [
        ("A 1点", [(100, 120)], 1),
        ("B 3点", [(100, 120), (300, 200), (500, 300)], 3),
        ("C 1点", [(320, 180)], 1),
        ("D 2点", [(80, 60), (560, 320)], 2),
    ]
    ok = 0
    for tag, dots, expect in cases:
        m[0:NPIX] = build(dots)
        sysfs("sync_for_device", 1)
        wr(0x00, 1)
        st = wait_done()
        n = (st >> 8) & 0xFF
        print("[%s] 期望 %d，STATUS 报告 %d   (ST=0x%08X done=%d err=%d)" %
              (tag, expect, n, st, (st >> 1) & 1, (st >> 2) & 1))
        if n == expect:
            ok += 1
        time.sleep(0.05)
    print("VERDICT", "CPU2PL-OK" if ok == len(cases) else "CPU2PL-BAD (%d/%d)" % (ok, len(cases)))
    m.close(); os.close(fd); reg.close(); os.close(rfd)


if __name__ == "__main__":
    main()
