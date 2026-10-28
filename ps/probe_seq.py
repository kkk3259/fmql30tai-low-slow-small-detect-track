#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# probe_seq.py —— 连续 4 张不同图，每张都写→触发→等 done→读结果，看结果是"当帧"还是"前一帧"
import sys, time
sys.path.insert(0, '/tmp')
import pl_debug as P

W, H = 640, 360
m, phys, size = P.open_udmabuf()
rm = P.RegMap()
rm.wr(0x04, 0x30100000)
rm.wr(0x08, 0x30240000)


def img_bg():
    return bytearray([8]) * (W * H)


def img_dots(pts, val=240):
    b = img_bg()
    for (cx, cy) in pts:
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                b[(cy + dy) * W + (cx + dx)] = val
    return b


def img_square(x0, y0, w, h, val=240):
    b = img_bg()
    for y in range(y0, y0 + h):
        for x in range(x0, x0 + w):
            b[y * W + x] = val
    return b


CASES = [
    ("A: 3点(40,40)(300,100)(600,200)", img_dots([(40, 40), (300, 100), (600, 200)])),
    ("B: 纯背景", img_bg()),
    ("C: 方块20x20@(300,180)", img_square(290, 170, 20, 20)),
    ("D: 2点(100,300)(500,50)", img_dots([(100, 300), (500, 50)])),
]


def dump_res(tag):
    raw = bytes(m[0x140000:0x140000 + 36])
    n = raw[0]
    out = []
    for k in range(min(n, 5)):
        e = raw[1 + 7 * k: 8 + 7 * k]
        out.append("(%d,%d)a%d p%d" % ((e[0] << 8) | e[1], (e[2] << 8) | e[3],
                                       (e[4] << 8) | e[5], e[6]))
    print("  %s RES n=%d %s" % (tag, n, " ".join(out)))


for i, (tag, buf) in enumerate(CASES, 1):
    m[0:W * H] = bytes(buf)
    dump_res("写图后/触发前 ")
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
    dump_res("触发后        ")
    time.sleep(0.2)
    print("")
