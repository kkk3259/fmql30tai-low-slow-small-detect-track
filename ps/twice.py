#!/usr/bin/env python3
# twice.py —— 同一张图连触两次，看坐标是否继续平移（判断是不是链上残留）
# 用法：sudo python3 /tmp/twice.py
import sys, time
sys.path.insert(0, '/tmp')
import pl_debug as P

W, H = 640, 360
DOTS = [(40, 40), (40, 180), (40, 320)]

m, phys, size = P.open_udmabuf()
buf = bytearray(W * H)
for y in range(H):
    row = y * W
    for x in range(W):
        buf[row + x] = 8
for (cx, cy) in DOTS:
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            buf[(cy + dy) * W + (cx + dx)] = 240
m[0:len(buf)] = bytes(buf)
print("图案：3 个点 %s" % (DOTS,))

rm = P.RegMap()
rm.wr(0x04, 0x30100000)
rm.wr(0x08, 0x30240000)


def run(tag):
    rm.wr(0x00, 1)
    st = 0
    t0 = time.time()
    while time.time() - t0 < 2.0:
        st = rm.rd(0x0C)
        if st & 0x2:
            break
        time.sleep(0.002)
    d1 = rm.rd(0x1C)
    d2 = rm.rd(0x20)
    print("--- %s: STATUS=0x%08X done=%d err=%d n=%d | fifo_lv=%d fst=%d err_code=%d | ccl_px=%d st=%d"
          % (tag, st, (st >> 1) & 1, (st >> 2) & 1, (st >> 8) & 0xFF,
             (d1 >> 16) & 0xFFFF, (d1 >> 8) & 7, d1 & 0xFF,
             (d2 >> 6) & 0x3FFFF, d2 & 7))
    raw = bytes(m[0x140000:0x140000 + 36])
    n = raw[0]
    for k in range(min(n, 5)):
        e = raw[1 + 7 * k: 8 + 7 * k]
        print("      #%d x=%4d y=%3d area=%3d peak=%3d"
              % (k + 1, (e[0] << 8) | e[1], (e[2] << 8) | e[3],
                 (e[4] << 8) | e[5], e[6]))


run("第1次")
time.sleep(0.05)
run("第2次")
time.sleep(0.05)
run("第3次")
