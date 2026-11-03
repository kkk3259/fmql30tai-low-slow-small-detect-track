#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# test_flow.py —— 缓存一致性修复后的闭环验证：两张不同的图，各触发一次，坐标必须跟着变
import os, sys, time, struct, mmap as MM

UDMA   = "/dev/udmabuf0"
SYS    = "/sys/class/u-dma-buf/udmabuf0"
DEVMEM = "/dev/mem"
REG    = 0x43C00000
W, H   = 640, 360
NPIX   = W * H
RES_OFF = 0xF00000

REG_CTRL, REG_FADDR, REG_RADDR, REG_STATUS = 0x00, 0x04, 0x08, 0x0C
REG_FID,  REG_VER   = 0x10, 0x14
REG_DBG0, REG_DBG1, REG_DBG2, REG_DBG3 = 0x18, 0x1C, 0x20, 0x24


def sysfs(name, val=None):
    p = os.path.join(SYS, name)
    if val is None:
        with open(p) as f:
            return f.read().strip()
    with open(p, "w") as f:
        f.write(str(val))


def main():
    fd = os.open(UDMA, os.O_RDWR | os.O_SYNC)
    size = int(sysfs("size"), 0)
    if size <= 0:
        size = os.fstat(fd).st_size
    print("udmabuf 映射长度 = %d 字节" % size)
    m = MM.mmap(fd, size, MM.MAP_SHARED, prot=MM.PROT_READ | MM.PROT_WRITE)

    rfd = os.open(DEVMEM, os.O_RDWR | os.O_SYNC)
    reg = MM.mmap(rfd, 0x1000, MM.MAP_SHARED, offset=REG)

    def rd(o):
        return struct.unpack_from("<I", reg, o)[0]

    def wr(o, v):
        struct.pack_into("<I", reg, o, v & 0xFFFFFFFF)

    print("VER        = 0x%08X" % rd(REG_VER))
    print("sync_mode  = %s" % sysfs("sync_mode"))
    print("FADDR      = 0x%08X  RADDR = 0x%08X" % (rd(REG_FADDR), rd(REG_RADDR)))

    def wait_done(ms):
        t0 = time.time()
        while (time.time() - t0) * 1000 < ms:
            st = rd(REG_STATUS)
            if st & 0x02 or st & 0x04:
                return st
            time.sleep(0.002)
        return rd(REG_STATUS)

    def run(dots, tag):
        # 铺底 + 亮点
        buf = bytearray(NPIX)
        for y in range(H):
            base = y * W
            for x in range(W):
                buf[base + x] = (8 + ((x >> 6) & 15)) & 0xFF
        for (cx, cy) in dots:
            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    xx, yy = cx + dx, cy + dy
                    if 0 <= xx < W and 0 <= yy < H:
                        buf[yy * W + xx] = 240
        m[0:NPIX] = bytes(buf)
        sysfs("sync_for_device", 1)          # 脏行写回 DDR，让 PL 看见
        wr(REG_CTRL, 1)
        st = wait_done(3000)
        n0 = m[RES_OFF]
        time.sleep(0.02)                     # 给写主控/DRAM 一点时间
        sysfs("sync_for_cpu", 1)             # 丢弃 CPU 缓存里的旧行，读 DDR
        n = m[RES_OFF]
        raw = bytes(m[RES_OFF:RES_OFF + 36])
        cands = []
        for i in range(min(n, 5)):
            b = raw[1 + i * 7: 8 + i * 7]
            if len(b) < 7:
                break
            x = (b[0] << 8) | b[1]
            y = (b[2] << 8) | b[3]
            area = b[5] * 256 + b[6]
            cands.append((x, y, area))
        print("[%s] dots=%s ST=0x%08X done=%d err=%d ncand_stat=%d n0=%d n=%d cands=%s  DBG0=0x%08X DBG1=0x%08X DBG2=0x%08X DBG3=0x%08X" %
              (tag, dots, st, (st >> 1) & 1, (st >> 2) & 1, (st >> 8) & 0xFF, n0, n, cands,
               rd(REG_DBG0), rd(REG_DBG1), rd(REG_DBG2), rd(REG_DBG3)))
        return cands

    a = run([(100, 120)], "A")
    b = run([(300, 200)], "B")
    c = run([(100, 120)], "C")
    print("--- 结论 ---")
    okA = any(abs(x - 100) <= 1 and abs(y - 120) <= 1 for x, y, _ in a)
    okB = any(abs(x - 300) <= 1 and abs(y - 200) <= 1 for x, y, _ in b)
    print("A 命中 (100,120): %s   B 命中 (300,200): %s" % (okA, okB))
    print("VERDICT", "COHERENT-OK" if (okA and okB) else "STILL-STALE")

    m.close()
    os.close(fd)
    reg.close()
    os.close(rfd)


if __name__ == "__main__":
    main()
