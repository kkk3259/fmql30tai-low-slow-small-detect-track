#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# probe_sync2.py —— 分步打印，定位 SIGBUS 位置，并试 ioctl 同步
import os, sys, mmap, time, fcntl, ctypes, struct
sys.path.insert(0, '/tmp')
import pl_debug as P

W, H = 640, 360
NPIX = W * H
RES_OFF = 0x140000
IOCTL_SYNC = 0x40187500
SYNC_START, SYNC_END, SYNC_TO_DEV, SYNC_FROM_DEV = 1 << 0, 1 << 1, 1 << 2, 1 << 3

print("step1: open")
fd = os.open("/dev/udmabuf0", os.O_RDWR)
print("step2: mmap 2MB")
m = mmap.mmap(fd, 0x200000)
print("step3: build image")
img = bytearray([8]) * NPIX
for (cx, cy) in [(40, 40), (300, 100), (600, 200)]:
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            img[(cy + dy) * W + (cx + dx)] = 240
img = bytes(img)
print("step4: write image")
m[0:NPIX] = img
print("step5: RegMap")
rm = P.RegMap()
print("step6: set addr")
rm.wr(0x04, 0x30100000)
rm.wr(0x08, 0x30240000)


def sync(flags, off, size):
    buf = ctypes.create_string_buffer(struct.pack("<QQQ", flags, off, size), 24)
    fcntl.ioctl(fd, IOCTL_SYNC, buf)


print("step7: sync TO_DEV")
sync(SYNC_START | SYNC_TO_DEV, 0, NPIX)
print("step8: trigger")
rm.wr(0x00, 1)
t0 = time.time()
st = 0
while time.time() - t0 < 3.0:
    st = rm.rd(0x0C)
    if st & 0x2:
        break
    time.sleep(0.002)
print("step9: STATUS=0x%08X n=%d err=%d cnt=%d" % (st, (st >> 8) & 0xFF, (st >> 2) & 1, (st >> 16) & 0xFF))
print("step10: sync FROM_DEV")
sync(SYNC_END | SYNC_FROM_DEV, RES_OFF, 36)
raw = m[RES_OFF:RES_OFF + 36]
print("step11: RES=%s" % raw.hex())
n = raw[0]
for k in range(min(n, 5)):
    e = raw[1 + 7 * k: 8 + 7 * k]
    print("   #%d x=%d y=%d area=%d peak=%d" % (k + 1, (e[0] << 8) | e[1], (e[2] << 8) | e[3],
                                               (e[4] << 8) | e[5], e[6]))
