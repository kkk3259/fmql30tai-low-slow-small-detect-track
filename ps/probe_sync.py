#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# probe_sync.py —— u-dma-buf(sync_mode=1) 的缓存同步试验：找出正确的 ioctl 组合
import os, sys, mmap, time, fcntl, ctypes, struct
sys.path.insert(0, '/tmp')
import pl_debug as P

W, H = 640, 360
NPIX = W * H
RES_OFF = 0x140000
UDMABUF_IOCTL_SYNC = 0x40187500        # _IOW('u', 0, struct{flags,offset,size}) = 24 字节
SYNC_START = 1 << 0
SYNC_END = 1 << 1
SYNC_TO_DEV = 1 << 2
SYNC_FROM_DEV = 1 << 3

fd = os.open("/dev/udmabuf0", os.O_RDWR | os.O_SYNC)
m = mmap.mmap(fd, 0x200000)
print("mmap OK, fd=%d" % fd)


def sync(flags, off, size):
    buf = ctypes.create_string_buffer(struct.pack("<QQQ", flags, off, size), 24)
    try:
        fcntl.ioctl(fd, UDMABUF_IOCTL_SYNC, buf)
        return True
    except OSError as e:
        print("    ioctl 失败 flags=0x%X: %s" % (flags, e))
        return False


rm = P.RegMap()
rm.wr(0x04, 0x30100000)
rm.wr(0x08, 0x30240000)

DOTS = [(40, 40), (300, 100), (600, 200)]


def img():
    b = bytearray([8]) * NPIX
    for (cx, cy) in DOTS:
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                b[(cy + dy) * W + (cx + dx)] = 240
    return bytes(b)


def read_res():
    raw = m[RES_OFF:RES_OFF + 36]
    n = raw[0]
    got = []
    for k in range(min(n, 5)):
        e = raw[1 + 7 * k: 8 + 7 * k]
        got.append(((e[0] << 8) | e[1], (e[2] << 8) | e[3], (e[4] << 8) | e[5], e[6]))
    return got


def frame():
    rm.wr(0x00, 1)
    t0 = time.time()
    st = 0
    while time.time() - t0 < 3.0:
        st = rm.rd(0x0C)
        if st & 0x2:
            break
        time.sleep(0.002)
    return st


def ok(got):
    xs = sorted([g[0] for g in got])
    return len(got) == 3 and xs == [40, 300, 600]


print("")
print("=== 先试一次“不 sync”作为基准 ===")
m[0:NPIX] = img()
st = frame()
print("  STATUS=0x%08X  got=%s" % (st, read_res()))

COMBOS = [
    ("W=TO_DEV  R=FROM_DEV", SYNC_TO_DEV, SYNC_FROM_DEV),
    ("W=START|TO_DEV  R=END|FROM_DEV", SYNC_START | SYNC_TO_DEV, SYNC_END | SYNC_FROM_DEV),
    ("W=TO_DEV|END  R=FROM_DEV|START", SYNC_TO_DEV | SYNC_END, SYNC_FROM_DEV | SYNC_START),
]

for tag, fw, fr in COMBOS:
    m[0:NPIX] = img()
    sync(fw, 0, NPIX)
    st = frame()
    sync(fr, RES_OFF, 36)
    got = read_res()
    print("  %s  n=%d got=%s  %s" % (tag, (st >> 8) & 0xFF, got, "OK" if ok(got) else ""))
