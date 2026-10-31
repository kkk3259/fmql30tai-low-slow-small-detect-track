#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""读出适配层里的片上逻辑分析仪（LA），把三域数据通路的事件按时间还原。

寄存器（平台字节地址，基址 0x400C0000）：
    0xA0  写索引 i（0..255）→ 读 0xA0 得到第 i 条记录
    0xA8  状态 {frozen, trig[3:0], 3'd0, wp[7:0]}
    0xAC  写 1 清空

记录编码（每条 32 位，高 4 位是 tag）：
    1 = 平台 AR 握手       低 24 位 = 地址
    2 = 平台 R 返回        {ret_busy, lin_rdy_t}
    3 = 核发出行请求       {pend_wd[11:0], req_pend, ret_busy, plat_arvalid}
    4 = 核收到行数据       同上
    5 = 看门狗超时         （触发冻结）

用法（板上）：
    python3 la_dump.py            # 读状态 + 全部记录
    python3 la_dump.py --clear    # 先清空再读
"""
import argparse
import sys

sys.path.insert(0, "/root/ip2")
from icraft.xrt import Device

REG = 0x400C0000
LA_IDX, LA_STATUS, LA_CLR = 0xA0, 0xA8, 0xAC

TAG = {1: "AR握手", 2: "R返回", 3: "核发请求", 4: "核收数据", 5: "看门狗"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clear", action="store_true")
    ap.add_argument("--limit", type=int, default=64)
    ap.add_argument("--depth", type=int, default=64)
    a = ap.parse_args()

    dev = Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
    reg = dev.defaultRegRegion()

    if a.clear:
        reg.write(REG + LA_CLR, 1)
        print("LA 已清空")

    st = reg.read(REG + LA_STATUS) & 0xffffffff
    frozen = (st >> 31) & 1
    trig = (st >> 28) & 0xf
    wp = st & 0xff
    print("LA 状态: frozen=%d trig=%d wp=%d" % (frozen, trig, wp))
    if frozen:
        print("  ⚠ 已冻结（看门狗触发），下面是崩溃前后现场")

    wp = wp & (a.depth - 1)
    n = min(a.limit, wp if not frozen else a.depth)
    print("共 %d 条记录：" % n)
    counts = {}
    for i in range(n):
        reg.write(REG + LA_IDX, i)
        v = reg.read(REG + LA_IDX) & 0xffffffff
        tag = (v >> 28) & 0xf
        counts[tag] = counts.get(tag, 0) + 1
        name = TAG.get(tag, "?%d" % tag)
        if tag == 1:
            print("  [%3d] %-8s addr=0x%06x" % (i, name, v & 0xffffff))
        elif tag in (2,):
            print("  [%3d] %-8s ret_busy=%d rdy_t=%d"
                  % (i, name, (v >> 22) & 1, (v >> 21) & 1))
        elif tag in (3, 4):
            print("  [%3d] %-8s pend_wd=%d req_pend=%d ret_busy=%d arvalid=%d"
                  % (i, name, (v >> 16) & 0xfff, (v >> 13) & 1, (v >> 12) & 1, (v >> 11) & 1))
        else:
            print("  [%3d] %-8s 0x%08x" % (i, name, v))

    print("\n统计：")
    for t in sorted(counts):
        print("  %-8s %d 次" % (TAG.get(t, "?%d" % t), counts[t]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
