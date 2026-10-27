#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pl_debug.py — PL 侧“一帧跑不动”时的现场取证工具（在板子上跑）

用途
----
板上触发一帧后如果拿不到候选表，用这个脚本一次把全部现场取回来：
  - 6 个正常寄存器（CTRL/FRAME_ADDR/RESULT_ADDR/STATUS/FRAME_ID/VERSION）
  - 4 个调试寄存器（0x18 已喂像素 / 0x1C 状态+错误码 / 0x20 CCL 状态 / 0x24 握手）
  - 触发后的状态时间线（busy/done/err 什么时候变）
  - 结果区 36 字节候选表（可选：直接用内置图案，不依赖相机）

用法
----
  sudo python3 pl_debug.py                 # 只读寄存器 + 解码
  sudo python3 pl_debug.py --pattern       # 先写内置测试图到帧缓冲，再读
  sudo python3 pl_debug.py --trigger       # 写地址+触发一帧，打印时间线
  sudo python3 pl_debug.py --pattern --trigger --dump  # 全套

寄存器位域（与 pl/rtl/ip2_axi_top.v 一致，2026-10-27 版）
--------------------------------------------------------
STATUS(0x0C) = {8'h00, frm_cnt[7:0], n_cand[7:0], 5'd0, err_flag, done_flag, busy}
    bit0 busy / bit1 done / bit2 err / [15:8] n_cand / [23:16] 帧计数
DBG0(0x18) = 已喂进链路的像素数（该到 230400）
DBG1(0x1C) = {fifo_level[15:0], 5'd0, fst[2:0], err_code[7:0]}
    fst: 0 IDLE / 1 RST / 2 FILL / 3 FEED / 4 WAIT / 5 WRITE / 6 FIN
    err_code: 1 读 DDR 出错 / 2 读帧超时 / 3 喂数断粮 / 4 候选表超时 / 5 写回超时 / 6 写回出错
DBG2(0x20) = {8'd0, px_cnt[17:0], 3'd0, ccl_state[2:0]}
    ccl_state: 0 RUN / 1 MERGE / 2 POST / 3 SORT / 4 OUT / 5 DONE
DBG3(0x24) = {ocount[5:0], o_valid, rd_done, rd_error, wr_done, wr_error, 21'd0}
"""

import argparse
import mmap
import os
import struct
import sys
import time

REG_BASE = 0x43C00000
REG_LEN = 0x1000

UDMABUF_NAME = "udmabuf0"
FRAME_BASE_DEFAULT = 0x30100000     # 帧缓冲（udmabuf0 物理地址）
RESULT_OFF_DEFAULT = 0x00140000      # 结果区在帧缓冲内的偏移（0x30140000）

W, H = 640, 360

REG = {
    "CTRL": 0x00, "FRAME_ADDR": 0x04, "RESULT_ADDR": 0x08, "STATUS": 0x0C,
    "FRAME_ID": 0x10, "VERSION": 0x14,
    "DBG0": 0x18, "DBG1": 0x1C, "DBG2": 0x20, "DBG3": 0x24,
}

FST_NAME = {0: "F_IDLE", 1: "F_RST", 2: "F_FILL(读DDR填FIFO)", 3: "F_FEED(喂给链路)",
            4: "F_WAIT(等候选表)", 5: "F_WRITE(写回结果)", 6: "F_FIN"}
ERR_NAME = {0: "无", 1: "读 DDR 出错", 2: "读帧超时(F_FILL)", 3: "喂数断粮(F_FEED)",
            4: "候选表超时(F_WAIT)", 5: "写回超时(F_WRITE)", 6: "写回出错"}
CCL_NAME = {0: "S_RUN(扫描)", 1: "S_MERGE(合并标签)", 2: "S_POST(算质心)",
            3: "S_SORT(排序)", 4: "S_OUT(输出)", 5: "S_DONE"}


def die(msg):
    print("ERROR: %s" % msg)
    sys.exit(1)


class RegMap(object):
    def __init__(self):
        if not os.path.exists("/dev/mem"):
            die("没有 /dev/mem")
        try:
            self.f = open("/dev/mem", "r+b", buffering=0)
            self.m = mmap.mmap(self.f.fileno(), REG_LEN, offset=REG_BASE)
        except PermissionError:
            die("打开 /dev/mem 被拒（要 sudo）")
        except OSError as e:
            die("mmap 0x%08X 失败：%s\n"
                "        → 检查 bit 是否已下载、BD 里地址是否为 0x43C00000(GP0)" % (REG_BASE, e))

    def rd(self, off):
        return struct.unpack("<I", self.m[off:off + 4])[0]

    def wr(self, off, val):
        self.m[off:off + 4] = struct.pack("<I", val & 0xFFFFFFFF)

    def all(self):
        return dict((k, self.rd(v)) for k, v in REG.items())


def open_udmabuf():
    """返回 (mmap 对象 或 None, phys, size)"""
    base = "/sys/class/u-dma-buf/%s" % UDMABUF_NAME
    try:
        with open(base + "/phys_addr") as f:
            phys = int(f.read().strip(), 16)
        with open(base + "/size") as f:
            size = int(f.read().strip())
    except OSError:
        return None, None, None
    try:
        f = open("/dev/%s" % UDMABUF_NAME, "r+b", buffering=0)
        m = mmap.mmap(f.fileno(), size)
        return m, phys, size
    except OSError as e:
        print("WARN: 打不开 /dev/%s（%s），跳过帧缓冲读写" % (UDMABUF_NAME, e))
        return None, phys, size


def make_pattern(m, off=0):
    """写内置测试图（与仿真基线 tb_board_pattern640 完全一致）

    背景 = 8 + ((x >> 6) & 15)
    亮点 = 240，3x3，位置 (106,72) (106,216) (320,72) (320,216)   ← 期望检出这 4 个
    大块 = 200，40x40，位置 (440..480, 250..290)                  ← 应被面积上限滤掉
    """
    dots = [(106, 72), (106, 216), (320, 72), (320, 216)]
    big = (440, 250, 40)
    buf = bytearray(W * H)
    for y in range(H):
        row = y * W
        for x in range(W):
            buf[row + x] = 8 + ((x >> 6) & 15)
    for (cx, cy) in dots:
        for dy in (-1, 0, 1):
            yy = cy + dy
            if 0 <= yy < H:
                for dx in (-1, 0, 1):
                    xx = cx + dx
                    if 0 <= xx < W:
                        buf[yy * W + xx] = 240
    bx, by, bs = big
    for y in range(by, min(by + bs, H)):
        row = y * W
        for x in range(bx, min(bx + bs, W)):
            buf[row + x] = 200
    m[off:off + len(buf)] = bytes(buf)
    return len(buf)


def decode_status(v):
    return {
        "busy": v & 1, "done": (v >> 1) & 1, "err": (v >> 2) & 1,
        "n_cand": (v >> 8) & 0xFF, "frame_cnt": (v >> 16) & 0xFF,
    }


def show(rm, label=""):
    v = rm.all()
    st = decode_status(v["STATUS"])
    d1 = v["DBG1"]
    d2 = v["DBG2"]
    d3 = v["DBG3"]
    print("---- %s寄存器现场 ----" % (label + " " if label else ""))
    print("  VERSION     = 0x%08X   %s" % (v["VERSION"],
          "OK (0x00010000)" if v["VERSION"] == 0x00010000 else "!! 不是 0x00010000"))
    print("  CTRL        = 0x%08X   start=%d" % (v["CTRL"], v["CTRL"] & 1))
    print("  FRAME_ADDR  = 0x%08X" % v["FRAME_ADDR"])
    print("  RESULT_ADDR = 0x%08X" % v["RESULT_ADDR"])
    print("  FRAME_ID    = 0x%08X" % v["FRAME_ID"])
    print("  STATUS      = 0x%08X   busy=%d done=%d err=%d n_cand=%d frame_cnt=%d"
          % (v["STATUS"], st["busy"], st["done"], st["err"], st["n_cand"], st["frame_cnt"]))
    print("  DBG0 已喂像素 = %d  (期望 230400)%s" % (v["DBG0"],
          "" if v["DBG0"] == W * H else "   ← 没喂满！"))
    print("  DBG1 FIFO水位 = %d  fst = %d (%s)  err_code = %d (%s)"
          % ((d1 >> 16) & 0xFFFF, (d1 >> 8) & 7, FST_NAME.get((d1 >> 8) & 7, "?"),
             d1 & 0xFF, ERR_NAME.get(d1 & 0xFF, "?")))
    print("  DBG2 CCL 已扫 = %d  (期望 230400)  ccl_state = %d (%s)"
          % ((d2 >> 6) & 0x3FFFF, d2 & 7, CCL_NAME.get(d2 & 7, "?")))
    print("  DBG3 ocount = %d  o_valid=%d  rd_done=%d rd_err=%d wr_done=%d wr_err=%d"
          % ((d3 >> 26) & 0x3F, (d3 >> 25) & 1, (d3 >> 24) & 1, (d3 >> 23) & 1,
             (d3 >> 22) & 1, (d3 >> 21) & 1))
    return v


def decode_candidates(raw):
    n = raw[0]
    print("  候选数 n_cand = %d" % n)
    for i in range(min(n, 5)):
        b = raw[1 + i * 7: 1 + i * 7 + 7]
        if len(b) < 7:
            break
        x = (b[0] << 8) | b[1]
        y = (b[2] << 8) | b[3]
        area = b[5]
        peak = b[6]
        print("    #%d  x=%3d y=%3d area=%3d peak=%3d" % (i + 1, x, y, area, peak))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pattern", action="store_true", help="先写内置测试图到帧缓冲")
    ap.add_argument("--trigger", action="store_true", help="写地址并触发一帧")
    ap.add_argument("--dump", action="store_true", help="打印结果区 36 字节")
    ap.add_argument("--timeout", type=float, default=2.0, help="等 done 的超时（秒）")
    ap.add_argument("--result-off", default=hex(RESULT_OFF_DEFAULT),
                    help="结果区在帧缓冲内的偏移，默认 0x140000")
    args = ap.parse_args()

    result_off = int(args.result_off, 0)
    rm = RegMap()
    print("== 寄存器基址 0x%08X ==" % REG_BASE)
    v = show(rm)

    ubuf, uphys, usize = open_udmabuf()
    if uphys is not None:
        print("  udmabuf0  phys=0x%08X size=%d (%.0f MiB)" % (uphys, usize, usize / 1048576.0))
    if ubuf is not None and args.pattern:
        n = make_pattern(ubuf)
        print("  已写入内置测试图 %d 字节；期望检出 4 个候选 (106,72)(106,216)(320,72)(320,216)"
              % n)

    if args.trigger:
        frame_addr = uphys if uphys is not None else FRAME_BASE_DEFAULT
        result_addr = frame_addr + result_off
        rm.wr(REG["CTRL"], 0)
        rm.wr(REG["FRAME_ADDR"], frame_addr)
        rm.wr(REG["RESULT_ADDR"], result_addr)
        rm.wr(REG["FRAME_ID"], 1)
        print("  触发：FRAME_ADDR=0x%08X RESULT_ADDR=0x%08X" % (frame_addr, result_addr))
        t0 = time.time()
        rm.wr(REG["CTRL"], 1)
        last = None
        seen = []
        while time.time() - t0 < args.timeout:
            st = rm.rd(REG["STATUS"])
            if st != last:
                seen.append((time.time() - t0, st))
                last = st
            s = decode_status(st)
            if s["done"] or s["err"]:
                break
            time.sleep(0.0002)
        print("  时间线（ms, STATUS）：")
        for (t, st) in seen:
            s = decode_status(st)
            print("    %8.2f ms  0x%08X  busy=%d done=%d err=%d n=%d"
                  % (t * 1000, st, s["busy"], s["done"], s["err"], s["n_cand"]))
        show(rm, "触发后")

        if ubuf is not None:
            raw = bytes(ubuf[result_off:result_off + 36])
            print("  结果区 36 字节：" + " ".join("%02X" % c for c in raw))
            decode_candidates(raw)

    if args.dump and ubuf is not None and not args.trigger:
        raw = bytes(ubuf[result_off:result_off + 36])
        print("  结果区 36 字节：" + " ".join("%02X" % c for c in raw))
        decode_candidates(raw)


if __name__ == "__main__":
    main()
