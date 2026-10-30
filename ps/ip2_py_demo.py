#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IP2 三域平台 Python 测试：读寄存器 + 分配 PL DDR + 写帧 + 触发 + 读候选表"""
import sys
import numpy as np
import icraft.xrt as xrt
import icraft.zg330backend  # noqa: F401  注册后端

URL = "axi://zg330aiu?npu=0x40000000&dma=0x80000000"
REG = 0x400C0000
W, H = 640, 360


def build_frame():
    img = np.zeros((H, W), dtype=np.uint8)
    for (cx, cy, sz) in [(100, 80, 6), (250, 100, 10), (400, 120, 14),
                         (150, 250, 18), (480, 260, 20)]:
        x0, y0 = cx - sz // 2, cy - sz // 2
        img[y0:y0 + sz, x0:x0 + sz] = 255
    return img


def main():
    dev = xrt.Device.Open(URL)
    reg = dev.defaultRegRegion()
    print("[1] VERSION = 0x%08x" % (reg.read(REG + 0x14) & 0xffffffff))
    print("    STATUS  = 0x%08x" % (reg.read(REG + 0x0C) & 0xffffffff))

    mem = dev.defaultMemRegion()
    chunk = None
    for args in ((W * H,), (W * H, False, 64), (W * H, True, 64)):
        try:
            chunk = mem.malloc(*args)
            print("[2] malloc%r ok" % (args,))
            break
        except Exception as e:
            print("[2] malloc%r fail: %s" % (args, str(e)[:80]))
    if chunk is None:
        return 1

    print("    chunk methods: %s" % [n for n in dir(chunk) if not n.startswith("_")][:14])
    img = build_frame()
    chunk.write(0, img.tobytes(), img.size)
    print("[3] frame written %d B" % img.size)

    base = None
    for name in ("begin", "getMemPtr", "memPtr", "ptr"):
        if hasattr(chunk, name):
            p = getattr(chunk, name)
            p = p() if callable(p) else p
            try:
                base = p.addr()
                print("[4] %s -> addr 0x%x" % (name, base))
                break
            except Exception as e:
                print("[4] %s.addr fail: %s" % (name, str(e)[:60]))
    if base is None:
        return 1

    reg.write(REG + 0x04, base & 0xffffffff)
    reg.write(REG + 0x08, base & 0xffffffff)
    reg.write(REG + 0x00, 0)
    reg.write(REG + 0x00, 1)

    import time
    t0 = time.time()
    done = 0
    for _ in range(4000):
        if reg.read(REG + 0x80) & 1:
            done = 1
            break
        time.sleep(0.0002)
    print("[5] done=%d  %.2f ms  STATUS=0x%08x" % (done, (time.time() - t0) * 1000,
                                                  reg.read(REG + 0x0C) & 0xffffffff))
    if not done:
        return 1

    nw = (1 + 16 * 7 + 3) // 4
    data = bytearray()
    for i in range(nw):
        reg.write(REG + 0x10, i)
        data += (reg.read(REG + 0x10) & 0xffffffff).to_bytes(4, "little")
    n = data[0]
    print("[6] n_cand = %d" % n)
    for i in range(min(n, 16)):
        c = data[1 + i * 7: 8 + i * 7]
        x = (c[0] << 8) | c[1]
        y = (c[2] << 8) | c[3]
        a = (c[4] << 8) | c[5]
        print("    #%d (%d,%d) area=%d peak=%d" % (i, x, y, a, c[6]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
