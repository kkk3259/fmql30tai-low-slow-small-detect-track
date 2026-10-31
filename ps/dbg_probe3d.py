#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三域位流数据通路探针（0xA0/0x90/0x98 + 原始返回快照 0xC0/0xC4）。

用途：一次跑完，回答三个问题——
  1. 核到底有没有发出行请求？   （0xA0 = dbg_req）
  2. 平台有没有收下这些请求？   （0x90 = dbg_ar）
  3. 平台返回的原始 512 位是什么？（0xC0 写索引 / 0xC4 读字节）
"""
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import detect3d as d3  # noqa: E402

REG = 0x400C0000


def rd_u32(dev, off):
    return dev.defaultRegRegion().read(REG + off, 4)[0] & 0xFFFFFFFF


def main():
    img_path = sys.argv[1] if len(sys.argv) > 1 else "/root/ip2/sw.png"
    import cv2
    g = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
    if g is None:
        print("读不到", img_path)
        return 1
    if g.shape[:2] != (360, 640):
        g = cv2.resize(g, (640, 360), interpolation=cv2.INTER_AREA)

    det = d3.Det3D()
    dev = det.dev
    print("VERSION = 0x%08X" % rd_u32(dev, 0x14))

    before = {
        "req": rd_u32(dev, 0xA0),   # 核心发出的行请求数
        "ar":  rd_u32(dev, 0x90),   # 平台收下的 AR 数
        "rv":  rd_u32(dev, 0x94),   # 平台返回的 rvalid 拍数
        "wd":  rd_u32(dev, 0x9C),   # 看门狗超时次数
        "st":  rd_u32(dev, 0x98),   # {line_idx[15:0], lf_cnt[4:0], inflight[3:0], adq_cnt[2:0], feed_on, lf_empty, arv, 0}
    }
    print("BEFORE  req=%d ar=%d rv=%d wd=%d st=0x%08X" % (
        before["req"], before["ar"], before["rv"], before["wd"], before["st"]))

    st, cands, ms = det.detect(g, 40000)
    print("AFTER   STATUS=0x%08X  n=%d  %.1f ms" % (st, len(cands), ms))
    for c in cands[:8]:
        print("   (%d,%d) area=%d peak=%d" % (c["x"], c["y"], c["area"], c["peak"]))

    after = {
        "req": rd_u32(dev, 0xA0),
        "ar":  rd_u32(dev, 0x90),
        "rv":  rd_u32(dev, 0x94),
        "wd":  rd_u32(dev, 0x9C),
        "st":  rd_u32(dev, 0x98),
    }
    print("DELTA   req=+%d ar=+%d rv=+%d wd=+%d" % (
        after["req"] - before["req"], after["ar"] - before["ar"],
        after["rv"] - before["rv"], after["wd"] - before["wd"]))
    lo = after["st"]
    print("STAT    line_idx=%d lf_cnt=%d inflight=%d adq_cnt=%d feed_on=%d lf_empty=%d arv=%d" % (
        lo >> 16, (lo >> 11) & 0x1F, (lo >> 7) & 0xF, (lo >> 4) & 0x7,
        (lo >> 3) & 1, (lo >> 2) & 1, (lo >> 1) & 1))

    # ---- 平台第一笔原始返回（512 位 = 64 字节）----
    dev.defaultRegRegion().write(REG + 0xC0, int(0).to_bytes(4, "little"))
    raw = []
    for i in range(64):
        dev.defaultRegRegion().write(REG + 0xC0, int(i).to_bytes(4, "little"))
        raw.append(rd_u32(dev, 0xC4) & 0xFF)
    print("平台原始返回前 64 字节：")
    print("   " + " ".join("%3d" % b for b in raw[:32]))
    print("   " + " ".join("%3d" % b for b in raw[32:]))
    nz = sum(1 for b in raw if b != 0)
    print("   非零字节数 = %d / 64" % nz)
    if nz == 0:
        print("   => 平台返回全 0：AR 根本没发出去，或读的是错的地址")
    return 0


if __name__ == "__main__":
    sys.exit(main())
