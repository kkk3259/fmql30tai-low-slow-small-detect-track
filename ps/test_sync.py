#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# test_sync.py —— 判定 sync_for_cpu 是否真的让 CPU 看到 PL 写进 DDR 的结果
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
    return val


def main():
    fd = os.open(UDMA, os.O_RDWR | os.O_SYNC)
    size = int(sysfs("size"), 0)
    m = MM.mmap(fd, size, MM.MAP_SHARED, prot=MM.PROT_READ | MM.PROT_WRITE)
    rfd = os.open(DEVMEM, os.O_RDWR | os.O_SYNC)
    reg = MM.mmap(rfd, 0x1000, MM.MAP_SHARED, offset=REG)

    def rd(o):
        return struct.unpack_from("<I", reg, o)[0]

    def wr(o, v):
        struct.pack_into("<I", reg, o, v & 0xFFFFFFFF)

    print("sync_mode=%s size=%s offset=%s" % (sysfs("sync_mode"), sysfs("size"), sysfs("sync_offset")))

    # 一帧：1 个点，期望 RES+0 = 1
    buf = bytearray(NPIX)
    for y in range(H):
        buf[y * W:(y + 1) * W] = bytes([8 + ((y >> 4) & 15)]) * W
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            buf[(120 + dy) * W + (100 + dx)] = 240
    m[0:NPIX] = bytes(buf)
    sysfs("sync_for_device", 1)
    wr(0x00, 1)
    t0 = time.time()
    while (time.time() - t0) < 3:
        st = rd(0x0C)
        if st & 0x06:
            break
        time.sleep(0.002)
    print("帧完成 ST=0x%08X  STATUS 报告 n_cand=%d" % (st, (st >> 8) & 0xFF))

    print("--- 直接读 RES+0（映射仍是缓存属性时会是旧的 0） ---")
    print("  第一次读 = %d" % m[RES_OFF])
    print("  再读     = %d" % m[RES_OFF])

    print("--- CPU 写 0xAA 到 RES+0，再读 ---")
    m[RES_OFF] = 0xAA
    print("  读 = 0x%02X （0xAA 说明写进了 cache）" % m[RES_OFF])

    print("--- sync_for_cpu=1 后再读 ---")
    sysfs("sync_for_cpu", 1)
    print("  读 = 0x%02X" % m[RES_OFF])

    print("--- 再试 sync_for_device=1 后读 ---")
    sysfs("sync_for_device", 1)
    print("  读 = 0x%02X" % m[RES_OFF])

    print("--- 试 sync_direction 组合 ---")
    for d in ("1", "2", "3"):
        sysfs("sync_direction", d)
        sysfs("sync_for_cpu", 1)
        print("  direction=%s → 读 = 0x%02X" % (d, m[RES_OFF]))

    print("--- 结果区前 48 字节 ---")
    print(" ", " ".join("%02X" % b for b in bytes(m[RES_OFF:RES_OFF + 48])))
    print("--- 状态字区 RES+0x40 ---")
    print(" ", " ".join("%02X" % b for b in bytes(m[RES_OFF + 0x40:RES_OFF + 0x48])))

    m.close(); os.close(fd); reg.close(); os.close(rfd)


if __name__ == "__main__":
    main()
