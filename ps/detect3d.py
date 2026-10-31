#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三域平台（PS7 + AI_Mate + 我们的检测器）上的检测器驱动。

与 cam_pipe.py 的区别：
  * cam_pipe 走 PS DDR（/dev/udmabuf0 + 我们的独立位流）；
  * 本脚本走 **PL DDR + ICraft 运行时**（`mem.malloc` 拿到的就是 PL DDR 物理地址），
    对应三域位流（ours3d）——寄存器从平台寄存器口进、帧数据从平台 512 位数据口出。

用法（板上）：
    python3 detect3d.py --img /root/frame.png          # 单图
    python3 detect3d.py --video /root/bird.mp4 --out /root/out3d.mp4
    python3 detect3d.py --bench                        # 只测一帧耗时

寄存器（平台字节地址，基址 0x400C0000）：
    0x00 CTRL(start)   0x04 FRAME_ADDR   0x08 RESULT_ADDR   0x0C STATUS
    0x14 VERSION       0x10 候选窗口（写索引 / 读数据）
    0x80 COMPUTE_DONE  0x90/0x94/0x98/0x9C 调试寄存器
"""
import argparse
import os
import sys
import time

import numpy as np

try:
    import cv2
except Exception:
    cv2 = None

sys.path.insert(0, "/root/ip2")
from icraft.xrt import Device

REG = 0x400C0000
W, H = 640, 360
DEV_URL = "axi://zg330aiu?npu=0x40000000&dma=0x80000000"

MAX_CAND = 16
N_WORD = (1 + MAX_CAND * 7 + 3) // 4


class Det3D(object):
    def __init__(self, w=W, h=H):
        self.w, self.h = w, h
        self.dev = Device.Open(DEV_URL)
        self.reg = self.dev.defaultRegRegion()
        self.mem = self.dev.defaultMemRegion()
        # 一帧 + 尾部余量（RTL 会多读 512 + 32*W 字节把流水线冲干净）
        self.buf = self.mem.malloc(w * h + 65536)
        self.base = self.buf.begin.addr()
        self.ver = self.reg.read(REG + 0x14) & 0xffffffff
        self.reg.write(REG + 0x04, self.base)
        self.reg.write(REG + 0x08, self.base)

    def detect(self, gray, timeout_ms=50):
        """送一帧 640×360 灰度，返回 (state, cands, dt_ms)。"""
        g = np.ascontiguousarray(gray, dtype=np.uint8)
        self.buf.write(0, g.tobytes(), g.size)
        t0 = time.time()
        self.reg.write(REG + 0x00, 0)
        self.reg.write(REG + 0x00, 1)
        dt = 0.0
        st = 0
        n = int(timeout_ms / 2)
        for _ in range(n):
            st = self.reg.read(REG + 0x0C) & 0xffffffff
            if (st >> 1) & 1:
                dt = (time.time() - t0) * 1000.0
                break
            if (st >> 2) & 1:
                dt = (time.time() - t0) * 1000.0
                break
            time.sleep(0.002)
        else:
            dt = (time.time() - t0) * 1000.0
        return st, self.read_cands(), dt

    def read_cands(self):
        data = bytearray()
        for i in range(N_WORD):
            self.reg.write(REG + 0x10, i)
            data += (self.reg.read(REG + 0x10) & 0xffffffff).to_bytes(4, "little")
        n = data[0]
        out = []
        for i in range(min(n, MAX_CAND)):
            c = data[1 + i * 7: 8 + i * 7]
            if len(c) < 7:
                break
            out.append({"x": (c[0] << 8) | c[1], "y": (c[2] << 8) | c[3],
                        "area": (c[4] << 8) | c[5], "peak": c[6]})
        return out

    def dbg(self):
        return dict(ar=self.reg.read(REG + 0x90), rv=self.reg.read(REG + 0x94),
                    wd=self.reg.read(REG + 0x98),
                    st=self.reg.read(REG + 0x9C) & 0xffffffff)


def cap_dump(reg):
    """读前 256 个"检测器看到的"像素字节（0xB4 写索引 / 0xB8 读数据）。"""
    out = bytearray()
    for i in range(256):
        reg.write(REG + 0xB4, i)
        out.append(reg.read(REG + 0xB8) & 0xFF)
    return bytes(out)


def draw(gray, cands, hud=""):
    img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR) if cv2 is not None else None
    if img is None:
        return None
    for c in cands:
        r = max(5, min(28, int(c["area"] ** 0.5 / 2) + 3))
        x, y = int(c["x"]), int(c["y"])
        cv2.rectangle(img, (x - r, y - r), (x + r, y + r), (0, 255, 0), 2)
        cv2.putText(img, "%dpx pk%d" % (int(c["area"] ** 0.5), c["peak"]),
                    (x + 6, y - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 0), 1, cv2.LINE_AA)
    if hud:
        cv2.putText(img, hud, (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2, cv2.LINE_AA)
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--img")
    ap.add_argument("--video")
    ap.add_argument("--out")
    ap.add_argument("--inv", type=int, default=0, help="1=取反（等价 Black-Hat，找暗目标）")
    ap.add_argument("--bench", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="视频只跑前 N 帧")
    a = ap.parse_args()

    det = Det3D()
    print("VERSION = 0x%08x   PL-DDR base = 0x%x" % (det.ver, det.base))
    print("DBG     = %s" % det.dbg())

    if a.img:
        gray = cv2.imread(a.img, cv2.IMREAD_GRAYSCALE)
        if gray is None:
            raise SystemExit("读不到 %s" % a.img)
        if gray.shape != (H, W):
            gray = cv2.resize(gray, (W, H))
        if a.inv:
            gray = 255 - gray
        st, cands, dt = det.detect(gray)
        print("STATUS = 0x%08x  done=%d err=%d  %.1f ms  n=%d"
              % (st, (st >> 1) & 1, (st >> 2) & 1, dt, len(cands)))
        for c in cands:
            print("   (%d,%d) area=%d peak=%d" % (c["x"], c["y"], c["area"], c["peak"]))
        print("DBG after = %s" % det.dbg())
        if a.out:
            img = draw(gray, cands, "STATUS 0x%08x %.1fms n=%d" % (st, dt, len(cands)))
            cv2.imwrite(a.out, img)
            print("saved %s" % a.out)
        return 0

    if a.bench:
        gray = (np.random.rand(H, W) * 255).astype(np.uint8)
        for i in range(5):
            st, c, dt = det.detect(gray)
            print("  run %d: ST=0x%08x %.1f ms n=%d" % (i, st, dt, len(c)))
        return 0

    if a.video:
        cap = cv2.VideoCapture(a.video)
        n_out = 0
        writer = None
        n = 0
        while True:
            ok, f = cap.read()
            if not ok:
                break
            n += 1
            if a.limit and n > a.limit:
                break
            g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
            g = cv2.resize(g, (W, H))
            gp = (255 - g) if a.inv else g
            st, cands, dt = det.detect(gp)
            img = draw(g, cands, "frame %d  %.1fms  n=%d" % (n, dt, len(cands)))
            img = cv2.resize(img, (f.shape[1], f.shape[0]))
            if a.out:
                if writer is None:
                    writer = cv2.VideoWriter(a.out, cv2.VideoWriter_fourcc(*"mp4v"), 30.0,
                                             (f.shape[1], f.shape[0]))
                writer.write(img)
            n_out += 1
            if n_out % 50 == 0:
                print("  %d 帧  %.1f ms  %d 候选" % (n_out, dt, len(cands)))
        cap.release()
        if writer is not None:
            writer.release()
            print("输出 %s" % a.out)
        return 0

    print("请给 --img / --video / --bench 之一")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
