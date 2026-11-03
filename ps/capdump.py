#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 512 位拆包的顺序问题一次定位死。

做法：喂一张"每个像素值都不同"的渐变图（row0 = 10,11,12,...），
触发一次检测，然后把适配层捕获的前 256 个"检测器看到的"像素字节读回来（0xB4/0xB8），
跟期望值逐字节对比，得出真实映射（顺序 / 字节序 / 偏移）。

寄存器：
  0xB4 <- 字节下标（0..255）
  0xB8 -> 该位置的字节
"""
import sys
import time

import numpy as np

sys.path.insert(0, "/root/ip2")
from icraft.xrt import Device

REG = 0x400C0000
W, H = 640, 360


def build_ramp():
    """每个像素值唯一：px(x,y) = 10 + ((x + y*3) % 240)，首行即 10,11,12..."""
    xs = np.arange(W, dtype=np.int32)[None, :]
    ys = np.arange(H, dtype=np.int32)[:, None]
    img = (10 + ((xs + ys * 3) % 240)).astype(np.uint8)
    return img


def main():
    dev = Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
    reg = dev.defaultRegRegion()
    mem = dev.defaultMemRegion()

    ver = reg.read(REG + 0x14) & 0xffffffff
    print("VERSION = 0x%08x" % ver)

    img = build_ramp()
    ch = mem.malloc(W * H + 32768)
    ch.write(0, img.tobytes(), img.size)
    base = ch.begin.addr()
    print("frame @ 0x%x (%d B)" % (base, img.size))

    reg.write(REG + 0x04, base)
    reg.write(REG + 0x08, base)
    reg.write(REG + 0x00, 0)
    reg.write(REG + 0x00, 1)

    for _ in range(60):
        st = reg.read(REG + 0x0C) & 0xffffffff
        if (st & 0x06) == 0x02:
            break
        time.sleep(0.005)
    print("STATUS = 0x%08x" % (reg.read(REG + 0x0C) & 0xffffffff))

    got = bytearray()
    for i in range(256):
        reg.write(REG + 0xB4, i)
        got.append(reg.read(REG + 0xB8) & 0xFF)

    exp = img.reshape(-1)[:256].tobytes()

    print("\nidx : exp  got")
    bad = 0
    for i in range(64):
        mark = "" if exp[i] == got[i] else "  <-- 不一致"
        if exp[i] != got[i]:
            bad += 1
        print("%3d : %3d  %3d%s" % (i, exp[i], got[i], mark))
    print("\n前 64 个里有 %d 个不一致" % bad)

    # 找映射：got[i] 是否等于 exp[(i*k + b) % 256]
    best = None
    for k in (1, 2, 3, 4, 8, 16, 32, 64):
        for b in range(-16, 17):
            ok = sum(1 for i in range(64) if 0 <= i * k + b < len(exp) and got[i] == exp[i * k + b])
            if best is None or ok > best[0]:
                best = (ok, k, b)
    print("最佳线性映射：命中 %d/64, got[i] = exp[%d*i + %d]" % best)

    # 字节序检查：got[0..7] 是否为 exp[0..7] 的逆序
    print("exp[0:8] =", list(exp[0:8]))
    print("got[0:8] =", list(got[0:8]))
    print("got[0:8] 逆序 =", list(got[0:8][::-1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
