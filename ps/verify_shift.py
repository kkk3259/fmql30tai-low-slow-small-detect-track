#!/usr/bin/env python3
# verify_shift.py —— 验证“帧缓冲残留 120 字节”修复是否生效（在板上跑）
#   期望：写入 (40,40)/(300,100)/(600,200) 三个 3×3 亮点，
#         修复后候选坐标就应该原样回来（x 不再 +120）。
import sys, time
sys.path.insert(0, '/tmp')
import pl_debug as P

W, H = 640, 360
DOTS = [(40, 40), (300, 100), (600, 200)]

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

rm = P.RegMap()
rm.wr(0x04, 0x30100000)
rm.wr(0x08, 0x30240000)


def frame(tag):
    rm.wr(0x00, 1)
    st = 0
    t0 = time.time()
    while time.time() - t0 < 2.0:
        st = rm.rd(0x0C)
        if st & 0x2:
            break
        time.sleep(0.002)
    raw = bytes(m[0x140000:0x140000 + 36])
    n = raw[0]
    got = []
    for k in range(min(n, 5)):
        e = raw[1 + 7 * k: 8 + 7 * k]
        got.append(((e[0] << 8) | e[1], (e[2] << 8) | e[3],
                    (e[4] << 8) | e[5], e[6]))
    print("%s STATUS=0x%08X err=%d n=%d" % (tag, st, (st >> 2) & 1, n))
    for k, g in enumerate(got):
        print("    #%d x=%4d y=%3d area=%3d peak=%3d" % (k + 1, g[0], g[1], g[2], g[3]))
    return st, got


print("=== 第 1 帧（期望 (40,40)(300,100)(600,200)）===")
st1, got1 = frame("第1帧")
print("=== 第 2 帧（同一图像，验证跨帧不再残留）===")
st2, got2 = frame("第2帧")

xs = sorted([g[0] for g in got1])
ok = (len(got1) == 3 and abs(xs[0] - 40) <= 2 and abs(xs[1] - 300) <= 2 and abs(xs[2] - 600) <= 2)
print("")
print("判定：%s" % ("修复生效（x 不再整体 +120）" if ok else "仍有偏移，需要继续查"))
print("第1帧 x = %s" % xs)
print("第2帧 x = %s" % sorted([g[0] for g in got2]))
