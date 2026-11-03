#!/usr/bin/env python3
# shift_probe.py —— 量"整帧整体平移了多少像素"
# 用法：sudo python3 /tmp/shift_probe.py
# 原理：写 6 个 3x3 亮点（x=40 与 x=600 各三行），看它们被报成什么坐标。
#   若无平移 => 报 (40,*) 与 (600,*)；若整体 +N 像素 => x 都加 N（超过 640 会绕到下一行）。
import sys, time
sys.path.insert(0, '/tmp')
import pl_debug as P

W, H = 640, 360
DOTS = [(40, 40), (40, 180), (40, 320), (600, 40), (600, 180), (600, 320)]

m, phys, size = P.open_udmabuf()
if m is None:
    print("ERROR: 打不开 udmabuf0")
    sys.exit(1)
print("udmabuf0 phys=0x%08X size=%d" % (phys, size))

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
print("已写入 6 个 3x3 亮点：%s" % (DOTS,))

rm = P.RegMap()
rm.wr(0x04, 0x30100000)     # FRAME_ADDR
rm.wr(0x08, 0x30240000)     # RESULT_ADDR
rm.wr(0x10, 0x0003)         # FRAME_ID
rm.wr(0x00, 1)              # CTRL.start
st = 0
t0 = time.time()
while time.time() - t0 < 2.0:
    st = rm.rd(0x0C)
    if st & 0x2:
        break
    time.sleep(0.002)
print("STATUS = 0x%08X  (busy=%d done=%d err=%d n_cand=%d)"
      % (st, st & 1, (st >> 1) & 1, (st >> 2) & 1, (st >> 8) & 0xFF))

raw = bytes(m[0x140000:0x140000 + 36]) if size > 0x140000 + 36 else b""
print("结果区: " + " ".join("%02x" % b for b in raw))
n = raw[0] if raw else 0
for k in range(min(n, 5)):
    e = raw[1 + 7 * k: 8 + 7 * k]
    x = (e[0] << 8) | e[1]
    y = (e[2] << 8) | e[3]
    a = (e[4] << 8) | e[5]
    print("  #%d  x=%4d y=%3d area=%3d peak=%3d" % (k + 1, x, y, a, e[6]))