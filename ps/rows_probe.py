#!/usr/bin/env python3
# rows_probe.py —— 找"顶部丢行"的边界 + 小 x 是否同样 +120
# 点：(2,10) (2,20) (2,30) (2,40) (2,60) (2,100) (300,10) (300,30) (300,60)
import sys, time
sys.path.insert(0, '/tmp')
import pl_debug as P

W, H = 640, 360
DOTS = [(2, 10), (2, 20), (2, 30), (2, 40), (2, 60), (2, 100),
        (300, 10), (300, 30), (300, 60)]

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
print("点: %s" % (DOTS,))

rm = P.RegMap()
rm.wr(0x04, 0x30100000)
rm.wr(0x08, 0x30240000)
rm.wr(0x00, 1)
st = 0
t0 = time.time()
while time.time() - t0 < 2.0:
    st = rm.rd(0x0C)
    if st & 0x2:
        break
    time.sleep(0.002)
print("STATUS=0x%08X  n=%d" % (st, (st >> 8) & 0xFF))
raw = bytes(m[0x140000:0x140000 + 36])
n = raw[0]
for k in range(min(n, 5)):
    e = raw[1 + 7 * k: 8 + 7 * k]
    print("  #%d x=%4d y=%3d area=%3d peak=%3d"
          % (k + 1, (e[0] << 8) | e[1], (e[2] << 8) | e[3],
             (e[4] << 8) | e[5], e[6]))
