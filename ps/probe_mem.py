#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# probe_mem.py —— 判断 udmabuf 映射是否有 cache 一致性坑；改用 /dev/mem 直写物理地址再测
import os, sys, mmap, time, glob
sys.path.insert(0, '/tmp')
import pl_debug as P

W, H = 640, 360
FRAME_PHYS = 0x30100000
RESULT_PHYS = 0x30240000
MAP_LEN = 0x200000           # 2 MB 覆盖帧(0x38400)+结果(0x140000+)

print("=== udmabuf 属性 ===")
for p in ["/sys/class/u-dma-buf/udmabuf0/sync_mode",
          "/sys/class/u-dma-buf/udmabuf0/size",
          "/sys/class/u-dma-buf/udmabuf0/phys_addr"]:
    try:
        print("  %s = %s" % (p.split('/')[-1], open(p).read().strip()))
    except OSError as e:
        print("  %s : 打不开 (%s)" % (p, e))
for p in glob.glob("/sys/module/u_dma_buf/parameters/*"):
    print("  module-param %s = %s" % (p.split('/')[-1], open(p).read().strip()))

rm = P.RegMap()
rm.wr(0x04, FRAME_PHYS)
rm.wr(0x08, RESULT_PHYS)


def img_dots(pts):
    b = bytearray([8]) * (W * H)
    for (cx, cy) in pts:
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                b[(cy + dy) * W + (cx + dx)] = 240
    return bytes(b)


def show_res(mem, off, tag):
    raw = mem[off:off + 36]
    n = raw[0]
    items = []
    for k in range(min(n, 5)):
        e = raw[1 + 7 * k: 8 + 7 * k]
        items.append("(%d,%d)a%d p%d" % ((e[0] << 8) | e[1], (e[2] << 8) | e[3],
                                        (e[4] << 8) | e[5], e[6]))
    print("  %s n=%d %s" % (tag, n, " ".join(items)))


print("")
print("=== 用 /dev/mem 直写物理地址 ===")
try:
    fm = open("/dev/mem", "r+b", buffering=0)
    mem = mmap.mmap(fm.fileno(), MAP_LEN, offset=FRAME_PHYS)
    print("  mmap OK: phys=0x%08X len=0x%X" % (FRAME_PHYS, MAP_LEN))
except Exception as e:
    print("  mmap 失败: %s" % e)
    sys.exit(1)

RES_OFF = RESULT_PHYS - FRAME_PHYS

CASES = [
    ("A: 3点(40,40)(300,100)(600,200)", [(40, 40), (300, 100), (600, 200)]),
    ("B: 2点(100,300)(500,50)", [(100, 300), (500, 50)]),
    ("C: 1点(320,180)", [(320, 180)]),
]

for i, (tag, pts) in enumerate(CASES, 1):
    mem[0:W * H] = img_dots(pts)
    rm.wr(0x00, 1)
    t0 = time.time()
    st = 0
    while time.time() - t0 < 3.0:
        st = rm.rd(0x0C)
        if st & 0x2:
            break
        time.sleep(0.002)
    print("第%d帧 %s" % (i, tag))
    print("  STATUS=0x%08X n=%d err=%d cnt=%d" % (st, (st >> 8) & 0xFF, (st >> 2) & 1, (st >> 16) & 0xFF))
    show_res(mem, RES_OFF, "结果(立即读)")
    time.sleep(0.3)
    show_res(mem, RES_OFF, "结果(300ms后)")
