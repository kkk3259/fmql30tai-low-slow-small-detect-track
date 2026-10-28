#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# dbg_once.py —— 只触发一帧，慢速打印 STATUS / INFO / DBG，用来判断是 PL 卡住还是软件读错
import os, struct, sys, time, mmap as MM

UDMA = "/dev/udmabuf0"
SYS = "/sys/class/u-dma-buf/udmabuf0"
REG = 0x43C00000
W, H = 640, 360
NPIX = W * H


def sysfs(n, v=None):
    p = os.path.join(SYS, n)
    if v is None:
        return open(p).read().strip()
    open(p, "w").write(str(v))


fd = os.open(UDMA, os.O_RDWR | os.O_SYNC)
buf = MM.mmap(fd, int(sysfs("size"), 0), MM.MAP_SHARED, prot=MM.PROT_READ | MM.PROT_WRITE)
rfd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
reg = MM.mmap(rfd, 0x1000, MM.MAP_SHARED, offset=REG)


def rd(o):
    return struct.unpack_from("<I", reg, o)[0]


def wr(o, v):
    struct.pack_into("<I", reg, o, v & 0xFFFFFFFF)


print("VER=0x%08X STATUS=0x%08X INFO=0x%08X" % (rd(0x14), rd(0x04), rd(0x40)))

img = bytes((8 + ((i // W) % 16)) for i in range(NPIX))
buf[0:NPIX] = img
sysfs("sync_offset", 0)
sysfs("sync_size", NPIX)
print("sync_size =", sysfs("sync_size"))
sysfs("sync_for_device", 1)
wr(0x00, 1)
t0 = time.time()
last = None
for i in range(200):
    st = rd(0x04)
    if st != last:
        print("t=%6.1f ms STATUS=0x%08X INFO=0x%08X DBG2=0x%08X DBG3=0x%08X" %
              ((time.time() - t0) * 1000, st, rd(0x40), rd(0x44), rd(0x48)))
        last = st
    if st & 0x06:
        break
    time.sleep(0.005)
print("结束 %.1f ms STATUS=0x%08X n=%d" % ((time.time() - t0) * 1000, rd(0x04), rd(0x18) & 0xFF))
