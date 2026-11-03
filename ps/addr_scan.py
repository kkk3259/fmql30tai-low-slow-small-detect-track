#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# addr_scan.py —— 扫一组物理地址，判断哪些是真的有 slave 响应
import mmap
import os
import struct
import sys

ADDRS = [0x40000000, 0x40000004, 0x4000001C, 0x40000100, 0x43C00000, 0x43C00014]

fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
for a in ADDRS:
    base = a & 0xFFFFF000
    off = a & 0xFFF
    try:
        m = mmap.mmap(fd, 0x1000, mmap.MAP_SHARED, prot=mmap.PROT_READ | mmap.PROT_WRITE, offset=base)
        v = struct.unpack_from("<I", m, off)[0]
        print("0x%08X = 0x%08X" % (a, v))
        m.close()
    except Exception as e:
        print("0x%08X 读取失败: %s" % (a, e))
os.close(fd)
