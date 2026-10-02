# -*- coding: utf-8 -*-
"""逐像素比对 ref.hex（OpenCV 标准答案）与 output.hex（Verilog 输出）。
跳过 1 像素边框（OpenCV 用 reflect 边界，Verilog 用 clamp，边缘语义不同，另做专项）。
容差 2 LSB。
"""


import sys
sys.stdout.reconfigure(encoding='utf-8')


def load(p):
    with open(p) as f:
        return [int(x, 16) for x in f.read().split()]


ref = load("ref.hex")
out = load("output.hex")
assert len(ref) == len(out), "长度不一致: %d vs %d" % (len(ref), len(out))

N = len(ref)
W = H = 16
TOL = 2

interior, border = [], []
for i in range(N):
    row, col = i // W, i % W
    d = abs(ref[i] - out[i])
    (interior if (0 < row < H - 1 and 0 < col < W - 1) else border).append(d)

print("总像素:", N)
print("内部像素(14x14):", len(interior),
      "| 最大误差:", max(interior),
      "| 平均误差: %.2f" % (sum(interior) / len(interior)))
print("  超过 %d LSB 的个数:" % TOL, sum(1 for d in interior if d > TOL))
print("边框像素:", len(border), "| 最大误差:", max(border))

bad = [(i, i // W, i % W, ref[i], out[i], abs(ref[i] - out[i]))
       for i in range(N) if (0 < i // W < H - 1 and 0 < i % W < W - 1)
       and abs(ref[i] - out[i]) > TOL]
if bad:
    print("不通过的像素(前20):", bad[:20])
print("结果:", "PASS ✅" if not bad else "FAIL ❌")
