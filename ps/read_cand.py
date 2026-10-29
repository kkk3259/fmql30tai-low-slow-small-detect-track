#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# read_cand.py —— 走 AXI-Lite 寄存器读候选表（0x40~0x60），彻底绕开 DDR 与缓存一致性问题
#   /dev/mem 映射 0x43C00000 是 uncached，读寄存器一直是可靠的。
import os, sys, time, struct, mmap as MM

UDMA = "/dev/udmabuf0"
SYS = "/sys/class/u-dma-buf/udmabuf0"
DEVMEM = "/dev/mem"
REG = 0x43C00000
W, H = 640, 360
NPIX = W * H

R_CTRL, R_FADDR, R_RADDR, R_STATUS = 0x00, 0x04, 0x08, 0x0C
R_FID, R_VER = 0x10, 0x14
R_DBG0, R_DBG1, R_DBG2, R_DBG3 = 0x18, 0x1C, 0x20, 0x24
R_THV, R_CFV, R_RDY, R_VC = 0x28, 0x2C, 0x30, 0x34
CAND_BASE = 0x18          # 9 个 32 位字 = 36 字节候选表
R_STMIRROR = 0x3C
R_FSM = 0x3C


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
            st = rd(R_STATUS)
            if st & 0x06:
                return st
            time.sleep(0.002)
        return rd(R_STATUS)

    def cand_bytes():
        out = bytearray()
        for i in range(9):
            out += struct.pack("<I", rd(CAND_BASE + 4 * i))
        return bytes(out)

    def decode(raw):
        n = raw[0]
        out = []
        for i in range(min(n, 5)):
            b = raw[1 + i * 7:8 + i * 7]
            if len(b) < 7:
                break
            out.append({"x": (b[0] << 8) | b[1], "y": (b[2] << 8) | b[3],
                        "area": (b[4] << 8) | b[5], "peak": b[6]})
        return n, out

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

    print("VER=0x%08X  FRAME=0x%08X  RESULT=0x%08X" % (rd(R_VER), rd(R_FADDR), rd(R_RADDR)))

    cases = [
        ([(100, 120)], [(100, 120)]),
        ([(320, 180)], [(320, 180)]),
        ([(60, 300), (500, 60), (580, 340)], [(60, 300), (500, 60), (580, 340)]),
        ([(100, 120), (400, 200)], [(100, 120), (400, 200)]),
    ]
    okc = 0
    for dots, expect in cases:
        m[0:NPIX] = build(dots)
        sysfs("sync_for_device", 1)
        wr(R_CTRL, 1)
        st = wait_done()
        n, cands = decode(cand_bytes())
        got = sorted((c["x"], c["y"]) for c in cands)
        exp = sorted(expect)
        good = (n == len(expect)) and (got == exp)
        okc += 1 if good else 0
        print("\n输入 %s → n=%d（STATUS 报 %d）%s" % (dots, n, (st >> 8) & 0xFF, "✓" if good else "✗"))
        for c in cands:
            print("    (%4d,%4d) area=%d peak=%d" % (c["x"], c["y"], c["area"], c["peak"]))
        print("    期望 %s" % (exp,))
        print("    DBG: thv=%d cfv=%d cclv=%d ocount/fsm=0x%08X" %
              (rd(R_THV), rd(R_CFV), rd(R_VC), rd(R_FSM)))
        time.sleep(0.05)

    print("\nVERDICT", "REG-OK" if okc == len(cases) else "REG-BAD (%d/%d)" % (okc, len(cases)))
    m.close(); os.close(fd); reg.close(); os.close(rfd)


if __name__ == "__main__":
    main()
