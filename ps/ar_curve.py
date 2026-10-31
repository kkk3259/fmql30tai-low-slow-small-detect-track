#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ar_curve.py —— 量"三域里检测器读一帧的真实耗时"。

启动一帧后每 1 ms 采一次 0x90(AR 计数)/0x94(RV)/0x98(WD)/0x0C(STATUS)，
打印 AR 增长曲线 + 每行平均延迟 + 整帧预计耗时。

判读：
  线性增长、每行 ~7 us   -> 正常，整帧 ~25 ms
  每行几十 us            -> 看门狗 240 ms 必然先叫（这就是 err=1 的根因）
  AR 中途停住            -> 真的断流
"""
import sys
import time
import cv2

REG = 0x400C0000
R_CTRL, R_FADDR, R_RADDR, R_STATUS = 0x00, 0x04, 0x08, 0x0C
R_AR, R_RV, R_WD = 0x90, 0x94, 0x98
NPIX = 640 * 360


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "/root/ip2/small_tgt.png"
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        print("读不到", path)
        return
    if img.shape[:2] != (360, 640):
        img = cv2.resize(img, (640, 360), interpolation=cv2.INTER_AREA)

    from icraft.xrt import Device
    dev = Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
    reg = dev.defaultRegRegion()
    mem = dev.defaultMemRegion()
    print("VERSION = 0x%08X" % (reg.read(REG + 0x14) & 0xFFFFFFFF))

    ch = mem.malloc(NPIX)
    ch.write(0, img.tobytes(), NPIX)
    bp = ch.begin if not callable(ch.begin) else ch.begin()
    ad = getattr(bp, "addr", None)
    base = ad() if callable(ad) else ad
    print("PL-DDR base = 0x%X" % base)

    reg.write(REG + R_FADDR, base)
    reg.write(REG + R_RADDR, base)
    time.sleep(0.02)

    a0 = reg.read(REG + R_AR) & 0xFFFFFFFF
    t0 = time.time()
    reg.write(REG + R_CTRL, 1)
    print("START  ar0 = %d" % a0)
    time.sleep(0.005)

    rows = []
    for _ in range(120):
        ar = reg.read(REG + R_AR) & 0xFFFFFFFF
        rv = reg.read(REG + R_RV) & 0xFFFFFFFF
        wd = reg.read(REG + R_WD) & 0xFFFFFFFF
        st = reg.read(REG + R_STATUS) & 0xFFFFFFFF
        ms = (time.time() - t0) * 1000.0
        rows.append((ms, ar - a0, rv, wd, st))
        if st & 1:
            print("DONE @ %.1f ms   0x%08X" % (ms, st))
            break
        time.sleep(0.001)

    print("\n   ms    AR+      RV      WD  STATUS")
    for ms, ar, rv, wd, st in rows[::max(1, len(rows) // 20)]:
        print(" %5.1f %6d %7d %7d  0x%08X" % (ms, ar, rv, wd, st))

    last_ms, last_ar = rows[-1][0], rows[-1][1]
    first_ms, first_ar = rows[0][0], rows[0][1]
    print("\n摘要: %d 个采样 / %.1f ms，AR 涨了 %d" % (len(rows), last_ms, last_ar))
    if last_ar > first_ar:
        span = max(last_ms - first_ms, 0.001)
        d = last_ar - first_ar
        per_line_us = span * 1000.0 / d
        print("  每行 %.2f us  ⇒ 3609 行整帧约 %.0f ms" % (per_line_us, per_line_us * 3609 / 1000.0))
    else:
        print("  AR 没有增长 —— 帧没启动，或寄存器读的是陈旧值")


if __name__ == "__main__":
    main()
