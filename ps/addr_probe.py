#!/usr/bin/env python3
# addr_probe.py —— 判断 +120 偏移是"读地址错位"还是"计数器错位"
# 做法：图案不变（3 个点 x=40），只把 FRAME_ADDR 依次设为 base+0 / base+120 / base-120，
#   看报出来的 x 怎么变：
#     改成 +120 后 x 回到 40  => PL 实际读的地址比编程值低 120（地址问题）
#     改成 +120 后 x 变成 280  => 与地址无关（链上计数器/流水线固定偏移）
#     三次都一样               => 地址没被用上
import sys, time
sys.path.insert(0, '/tmp')
import pl_debug as P

W, H = 640, 360
DOTS = [(40, 40), (40, 180), (40, 320)]
BASE = 0x30100000

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
print("图案：%s（写在 phys 0x%08X 起）" % (DOTS, phys))

rm = P.RegMap()
rm.wr(0x08, 0x30240000)


def run(tag, addr):
    rm.wr(0x04, addr)
    time.sleep(0.01)
    rm.wr(0x00, 1)
    st = 0
    t0 = time.time()
    while time.time() - t0 < 2.0:
        st = rm.rd(0x0C)
        if st & 0x2:
            break
        time.sleep(0.002)
    print("--- %s addr=0x%08X STATUS=0x%08X n=%d" % (tag, addr, st, (st >> 8) & 0xFF))
    raw = bytes(m[0x140000:0x140000 + 36])
    n = raw[0]
    for k in range(min(n, 5)):
        e = raw[1 + 7 * k: 8 + 7 * k]
        print("      #%d x=%4d y=%3d area=%3d peak=%3d"
              % (k + 1, (e[0] << 8) | e[1], (e[2] << 8) | e[3],
                 (e[4] << 8) | e[5], e[6]))


run("A 基准", BASE)
time.sleep(0.05)
run("B +120", BASE + 120)
time.sleep(0.05)
run("C -120", BASE - 120)
