# -*- coding: utf-8 -*-
"""cand_read.py —— 统一读候选表（兼容两种构建的地址视图）

两种视图：
  window  —— 写 0x10 字索引，读 0x10（新构建，最多 64 个候选 / 452 B）
  legacy  —— 读 0x18 起 9 个 32 位字 = 36 字节兼容视图（老构建 6 位地址，只有前 5 个候选）

视图判定：写索引 0 后读回该字，与 legacy[0] 比对；不一致则用 legacy。

用法:
  python3 cand_read.py                 # 自动判视图，打印候选
  python3 cand_read.py --view legacy   # 强制 legacy
  python3 cand_read.py --csv           # 输出一行 CSV: n,x0,y0,area0,peak0,...
"""
import argparse
import mmap
import os
import struct

BASE = 0x43C00000
R_CTRL = 0x00
R_FADDR = 0x04
R_RADDR = 0x08
R_STATUS = 0x0C
R_VER = 0x14
R_CIDX = 0x10
R_CDAT = 0x10
N_CAND = 64
TAB_WORDS = (1 + N_CAND * 7 + 3) // 4
LEG_WORDS = 9
LEG_CAND = 5


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--view", default="auto", choices=["auto", "window", "legacy"])
    ap.add_argument("--csv", action="store_true")
    ap.add_argument("--raw", action="store_true", help="打印原始字节")
    a = ap.parse_args()

    f = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
    m = mmap.mmap(f, 4096, offset=BASE)

    def rd(o):
        return struct.unpack_from("<I", m, o)[0]

    def wr(o, v):
        struct.pack_into("<I", m, o, v & 0xFFFFFFFF)

    view = a.view
    if view == "auto":
        # 判定：窗口的 0 号字应与 legacy_ram[0] 完全相同（都是候选表前 4 字节），
        # 且索引默认 0（复位值）。老构建没窗口，0x10 读回别的寄存器 → 必然不同。
        # 注意：**不发任何写操作**，避免把老构建的 FRAME_ID 写坏。
        view = "window" if rd(R_CDAT) == rd(0x18) else "legacy"

    if view == "window":
        words = []
        for i in range(TAB_WORDS):
            wr(R_CIDX, i)
            words.append(rd(R_CDAT))
        raw = b"".join(struct.pack("<I", w) for w in words)
        maxn = N_CAND
    else:
        raw = b"".join(struct.pack("<I", rd(0x18 + 4 * i)) for i in range(LEG_WORDS))
        maxn = LEG_CAND

    n = raw[0]
    cands = []
    for i in range(min(n, maxn)):
        b = raw[1 + i * 7: 8 + i * 7]
        if len(b) < 7:
            break
        cands.append((((b[0] << 8) | b[1]), ((b[2] << 8) | b[3]),
                      ((b[4] << 8) | b[5]), b[6]))

    if a.csv:
        flat = [str(n)]
        for (x, y, ar, pk) in cands:
            flat += [str(x), str(y), str(ar), str(pk)]
        print(",".join(flat))
        return

    st = rd(R_STATUS)
    print("VIEW=%s VERSION=0x%08X" % (view, rd(R_VER)))
    print("STATUS=0x%08X busy=%d done=%d err=%d n_cand=%d frm_cnt=%d"
          % (st, st & 1, (st >> 1) & 1, (st >> 2) & 1, (st >> 8) & 0xFF, (st >> 16) & 0xFF))
    print("FRAME_ADDR=0x%08X RESULT_ADDR=0x%08X" % (rd(R_FADDR), rd(R_RADDR)))
    print("表内 n = %d（视图上限 %d）" % (n, maxn))
    for i, (x, y, ar, pk) in enumerate(cands):
        print("  #%2d  (x=%3d, y=%3d)  area=%4d  peak=%3d" % (i + 1, x, y, ar, pk))
    if a.raw:
        print("BODY(hex): %s" % raw[:1 + 7 * n].hex())
    m.close()
    os.close(f)


if __name__ == "__main__":
    main()
