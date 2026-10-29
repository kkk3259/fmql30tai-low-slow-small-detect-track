# -*- coding: utf-8 -*-
"""size_sweep.py —— 单目标尺寸扫描：一次只放一个方块，量"能检出多大的目标"

背景：Top-Hat 开运算会抹掉"比结构元大"的亮块（SE=S → 只能输出边长 <S 的目标），
CCL 又有面积门限 MIN_AREA/MAX_AREA。本脚本把两者分开：
  · 实心方块：面积 = s²，大的会被 MAX_AREA 或结构元砍掉
  · 空心方框（--hollow）：边框 1 px，面积 ≈ 4s，能通过大门限，用来单独考察结构元

用法（板子）:
  python3 size_sweep.py --sizes 2,3,4,5,6,8,10,12,15,20,24,30,40
  python3 size_sweep.py --hollow --sizes 10,20,30,40,50
  python3 size_sweep.py --view legacy            # 强制老构建（6 位地址）
"""
import argparse
import mmap
import os
import struct
import time

W, H = 640, 360
NPIX = W * H
BASE = 0x43C00000
R_CTRL = 0x00
R_FADDR = 0x04
R_STATUS = 0x0C
R_VER = 0x14
R_CIDX = 0x40
R_CDAT = 0x44
N_CAND, TAB_WORDS, LEG_WORDS, LEG_CAND = 64, 113, 9, 5
UIO = "/dev/udmabuf0"
SYS = "/sys/class/u-dma-buf/udmabuf0"
BG, FG = 8, 240


def sync(name, val):
    try:
        with open(os.path.join(SYS, name), "w") as f:
            f.write(str(val))
    except Exception:
        pass


def pick_view(rd, wr, want):
    """决定用哪个地址视图。

    判据（数据驱动）：帧跑完后 STATUS 的 n_cand 若 >0，而窗口视图读出来的 n 是 0，
    说明这个位流没有 0x40/0x44 窗口（6 位地址的老构建），必须走 legacy。
    没跑到帧时退化为猜 window（调用方随后会用真实帧再校正一次）。
    """
    if want != "auto":
        return want
    st = rd(R_STATUS)
    sn = (st >> 8) & 0xFF
    if sn > 0:
        n_win, _ = read_cands(rd, wr, "window")
        return "window" if n_win > 0 else "legacy"
    return "window"


def read_cands(rd, wr, view):
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
    out = []
    for i in range(min(n, maxn)):
        b = raw[1 + i * 7: 8 + i * 7]
        if len(b) < 7:
            break
        out.append((((b[0] << 8) | b[1]), ((b[2] << 8) | b[3]),
                    ((b[4] << 8) | b[5]), b[6]))
    return n, out


def draw(buf, cx, cy, s, hollow):
    buf[:] = bytes([BG]) * NPIX
    x0, y0 = cx - s // 2, cy - s // 2
    if hollow:
        for k in range(s):
            for (yy, xx) in ((y0, x0 + k), (y0 + s - 1, x0 + k), (y0 + k, x0), (y0 + k, x0 + s - 1)):
                if 0 <= yy < H and 0 <= xx < W:
                    buf[yy * W + xx] = FG
        return
    for yy in range(y0, y0 + s):
        if not (0 <= yy < H):
            continue
        for xx in range(x0, x0 + s):
            if 0 <= xx < W:
                buf[yy * W + xx] = FG


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="2,3,4,5,6,8,10,12,15,20,24,30,40")
    ap.add_argument("--hollow", action="store_true")
    ap.add_argument("--view", default="auto", choices=["auto", "window", "legacy"])
    ap.add_argument("--cx", type=int, default=320)
    ap.add_argument("--cy", type=int, default=180)
    ap.add_argument("--tol", type=int, default=6, help="判定命中的中心容差")
    ap.add_argument("--csv", default="")
    a = ap.parse_args()

    reg = mmap.mmap(os.open("/dev/mem", os.O_RDWR | os.O_SYNC), 4096, offset=BASE)

    def rd(o):
        return struct.unpack_from("<I", reg, o)[0]

    def wr(o, v):
        struct.pack_into("<I", reg, o, v & 0xFFFFFFFF)

    view = a.view                          # "auto" 留给第一帧跑完后再判定
    buf = mmap.mmap(os.open(UIO, os.O_RDWR), NPIX, offset=0)
    sizes = [int(s) for s in a.sizes.split(",") if s.strip()]

    print("VERSION=0x%08X HOLLOW=%d 中心=(%d,%d) 视图=%s"
          % (rd(R_VER), a.hollow, a.cx, a.cy, a.view))
    print("边长  期望area  n_cand  中心命中   实测area peak  耗时ms  ")
    rows = []
    for s in sizes:
        draw(buf, a.cx, a.cy, s, a.hollow)
        sync("sync_offset", 0)
        sync("sync_size", NPIX)
        sync("sync_for_device", 1)
        wr(R_CTRL, 1)
        t0 = time.time()
        st = 0
        while (time.time() - t0) < 3.0:
            st = rd(R_STATUS)
            if (st & 0x06) or ((st >> 1) & 1):
                break
        dt = (time.time() - t0) * 1000.0
        if view == "auto":                      # 用真实帧的结果校正一次视图
            view = pick_view(rd, wr, "auto")
            print("# 视图判定 -> %s（STATUS n_cand=%d）" % (view, (st >> 8) & 0xFF))
        n, cands = read_cands(rd, wr, view)
        near = [(x, y, ar, pk) for (x, y, ar, pk) in cands
                if abs(x - a.cx) <= a.tol and abs(y - a.cy) <= a.tol]
        exp_area = (4 * s - 4) if a.hollow else (s * s)
        if near:
            _, _, ar, pk = near[0]
            print("%4d  %7d  %6d  %-8s  %8d %4d  %7.1f" % (s, exp_area, n, "命中", ar, pk, dt))
        else:
            print("%4d  %7d  %6d  %-8s  %8s %4s  %7.1f" % (s, exp_area, n, "——", "-", "-", dt))
        rows.append((s, exp_area, n, bool(near), (near[0][2] if near else 0), dt))
    buf.close()
    reg.close()

    if a.csv:
        with open(a.csv, "w") as f:
            f.write("size,exp_area,n_cand,hit,area,ms\n")
            for r in rows:
                f.write("%d,%d,%d,%d,%d,%.1f\n" % (r[0], r[1], r[2], int(r[3]), r[4], r[5]))
        print("CSV -> %s" % a.csv)


if __name__ == "__main__":
    main()
