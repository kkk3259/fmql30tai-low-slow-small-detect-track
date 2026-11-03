#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三域平台上读检测器内部调试寄存器（适配层加的 0x90/0x94/0x98/0x9C）。

- 0x90 = 平台 AR 握手次数（发出去的行读请求）
- 0x94 = 平台 R 返回拍数
- 0x98 = 看门狗触发次数
- 0x9C = 状态快照 {bus_addr[15:0], pend_wd[5:0], line_valid, req_pend, ret_busy, plat_arvalid}
"""
import sys
import time

import numpy as np

sys.path.insert(0, "/root/ip2")
from icraft.xrt import Device

REG = 0x400C0000
W, H = 640, 360

D_AR, D_RV, D_WD, D_ST = 0x90, 0x94, 0x98, 0x9C


def build_frame(kind="blocks"):
    img = np.zeros((H, W), np.uint8)
    if kind == "blocks":
        for cy, cx, s in ((80, 100, 6), (100, 250, 10), (120, 400, 14),
                          (250, 150, 18), (260, 480, 20)):
            img[cy - s // 2:cy + s // 2, cx - s // 2:cx + s // 2] = 255
    return img


def main():
    dev = Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
    reg = dev.defaultRegRegion()
    mem = dev.defaultMemRegion()

    print("VER     = 0x%08x" % (reg.read(REG + 0x14) & 0xffffffff))
    print("DBG pre = ar=%d rv=%d wd=%d st=0x%08x"
          % (reg.read(REG + D_AR), reg.read(REG + D_RV), reg.read(REG + D_WD),
             reg.read(REG + D_ST) & 0xffffffff))

    ch = mem.malloc(W * H + 32768)
    img = build_frame()
    ch.write(0, img.tobytes(), img.size)
    base = ch.begin.addr()
    print("frame written %d B @ 0x%x" % (img.size, base))

    reg.write(REG + 0x04, base)
    reg.write(REG + 0x08, base)
    reg.write(REG + 0x00, 0)
    reg.write(REG + 0x00, 1)

    for i in range(30):
        st = reg.read(REG + 0x0C) & 0xffffffff
        d = reg.read(REG + 0x80) & 0xffffffff
        ar = reg.read(REG + D_AR)
        rv = reg.read(REG + D_RV)
        wd = reg.read(REG + D_WD)
        ds = reg.read(REG + D_ST) & 0xffffffff
        print("t=%3dms ST=0x%08x done=%d | ar=%d rv=%d wd=%d | dstat=0x%08x"
              % (i * 5, st, d & 1, ar, rv, wd, ds))
        if (st & 0x06) == 0x02:
            break
        time.sleep(0.005)

    nw = (1 + 16 * 7 + 3) // 4
    data = bytearray()
    for i in range(nw):
        reg.write(REG + 0x10, i)
        data += (reg.read(REG + 0x10) & 0xffffffff).to_bytes(4, "little")
    n = data[0]
    print("n_cand = %d" % n)
    for i in range(min(n, 16)):
        c = data[1 + i * 7: 8 + i * 7]
        print("    #%d (%d,%d) area=%d peak=%d"
              % (i, (c[0] << 8) | c[1], (c[2] << 8) | c[3], (c[4] << 8) | c[5], c[6]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
