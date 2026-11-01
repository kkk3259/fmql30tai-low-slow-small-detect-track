#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""try_probe.py —— 逐次触发，看 AR 增量判断帧到底跑没跑。"""
import time

import cv2

import cam3d_test as ct

REG = 0x400C0000
R_CTRL, R_STATUS, R_AR, R_RV = 0x00, 0x0C, 0x90, 0x94


def main():
    img = cv2.imread("/root/ip2/vs_300.png", cv2.IMREAD_GRAYSCALE)
    img = cv2.resize(img, (640, 360))
    pl = ct.PL3D()
    r = pl.reg
    pl.run(img)                       # 预热
    for k in range(6):
        a0 = r.read(REG + R_AR) & 0xFFFFFFFF
        v0 = r.read(REG + R_RV) & 0xFFFFFFFF
        r.write(REG + R_CTRL, 0)
        time.sleep(0.005)
        r.write(REG + R_CTRL, 1)
        time.sleep(0.10)
        a1 = r.read(REG + R_AR) & 0xFFFFFFFF
        v1 = r.read(REG + R_RV) & 0xFFFFFFFF
        st = r.read(REG + R_STATUS) & 0xFFFFFFFF
        print("TRY%d  dAR=%-6d dRV=%-6d STATUS=0x%08X n=%d"
              % (k, a1 - a0, v1 - v0, st, (st >> 8) & 0xFF))


if __name__ == "__main__":
    main()
