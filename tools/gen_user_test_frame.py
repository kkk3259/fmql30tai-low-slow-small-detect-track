#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 ip2_user_op 仿真用的 640x360 帧（黑底 + 5 个白方块），输出 hex（1 行 1 字节）

方块位置/边长与 tb_user_op.v 里的期望值一一对应。
"""
import io
import os

W, H = 640, 360
TARGETS = [
    (100, 80, 6),
    (250, 100, 10),
    (400, 120, 14),
    (150, 250, 18),
    (480, 260, 20),
]

buf = bytearray(W * H)
for (cx, cy, s) in TARGETS:
    x0 = cx - s // 2
    y0 = cy - s // 2
    for y in range(y0, y0 + s):
        if 0 <= y < H:
            for x in range(x0, x0 + s):
                if 0 <= x < W:
                    buf[y * W + x] = 255

out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "pl", "sim", "frame_user_test.hex")
out = os.path.normpath(out)
with io.open(out, "w", encoding="ascii", newline="\n") as f:
    for b in buf:
        f.write("%02x\n" % b)

print("wrote", out, W * H, "bytes")
for (cx, cy, s) in TARGETS:
    print("  target center=(%d,%d) size=%d area=%d" % (cx, cy, s, s * s))
