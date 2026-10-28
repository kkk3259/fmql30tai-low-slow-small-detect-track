#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# test_evict.py —— 用“冲缓存”把 CPU 里的旧行挤掉，再看 PL 写进 DDR 的候选表
import os, sys, time, struct, mmap as MM

UDMA = "/dev/udmabuf0"
SYS  = "/sys/class/u-dma-buf/udmabuf0"
DEVMEM = "/dev/mem"
REG = 0x43C00000
W, H = 640, 360
NPIX = W * H
RES_OFF = 0xF00000

EVICT = bytearray(8 * 1024 * 1024)   # 8 MB 冲缓存缓冲


def sysfs(name, val=None):
    p = os.path.join(SYS, name)
    if val is None:
        with open(p) as f:
            return f.read().strip()
    with open(p, "w") as f:
        f.write(str(val))


def evict_cache():
    # 顺序写 8 MB，把 L2（512 KB 级）里的旧行全部挤出去
    for i in range(0, len(EVICT), 4096):
        EVICT[i] = (i >> 12) & 0xFF
    return sum(EVICT[::4096]) & 0xFF


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
            buf[y * W:(y + 1) * W] = bytes([8 + ((y >> 4) & 15)]) * W
        for (cx, cy) in dots:
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    xx, yy = cx + dx, cy + dy
                    if 0 <= xx < W and 0 <= yy < H:
                        buf[yy * W + xx] = 240
        return bytes(buf)

    def decode(raw):
        n = raw[0]
        out = []
        for i in range(min(n, 5)):
            b = raw[1 + i * 7:8 + i * 7]
            if len(b) < 7:
                break
            out.append(((b[0] << 8) | b[1], (b[2] << 8) | b[3], b[5] * 256 + b[6], b[6]))
        return n, out

    cases = [[(100, 120), (400, 200)], [(320, 180)], [(60, 300), (500, 60), (580, 340)]]
    for dots in cases:
        m[0:NPIX] = build(dots)
        sysfs("sync_for_device", 1)
        wr(0x00, 1)
        st = wait_done()
        before = bytes(m[RES_OFF:RES_OFF + 36])
        evict_cache()
        after = bytes(m[RES_OFF:RES_OFF + 36])
        n1, c1 = decode(before)
        n2, c2 = decode(after)
        print("输入 %s" % (dots,))
        print("  冲缓存前: n=%d %s" % (n1, c1))
        print("  冲缓存后: n=%d %s   (STATUS n=%d)" % (n2, c2, (st >> 8) & 0xFF))
        sysfs("sync_for_cpu", 1)
        n3, c3 = decode(bytes(m[RES_OFF:RES_OFF + 36]))
        print("  再 sync_for_cpu: n=%d %s" % (n3, c3))
        time.sleep(0.05)

    m.close(); os.close(fd); reg.close(); os.close(rfd)


if __name__ == "__main__":
    main()
