#!/usr/bin/env python3
# test_target.py —— 把一张 640x360 的 raw 灰度图喂给 PL，打印检出的候选（用于量检出率）
#
# 用法（板上）：
#   python3 test_target.py /tmp/tgt_a.bin /tmp/tgt_a.json
#
# 原理与 cam_pipe 一致：写 udmabuf0 → 写 FRAME_ADDR → 触发 → 等 done → 读 64 候选窗口
import json
import mmap
import os
import struct
import sys
import time

W, H = 640, 360
NPIX = W * H
UDMABUF = "/dev/udmabuf0"
SYSFS = "/sys/class/u-dma-buf/udmabuf0"

R_CTRL, R_FRAME, R_RES, R_STAT, R_IDX, R_VER = 0x00, 0x04, 0x08, 0x0C, 0x10, 0x14
BASE = 0x43C00000
FRAME_ADDR = 0x30100000
MAX_WORDS = 113


def sysfs_rd(name):
    with open(os.path.join(SYSFS, name)) as f:
        return int(f.read().strip(), 0)


class HW(object):
    def __init__(self):
        self.fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
        self.reg = mmap.mmap(self.fd, 0x1000, mmap.MAP_SHARED,
                             mmap.PROT_READ | mmap.PROT_WRITE, offset=BASE)
        self.phys = sysfs_rd("phys_addr")
        self.size = sysfs_rd("size")
        self.ufd = os.open(UDMABUF, os.O_RDWR | os.O_SYNC)
        self.ubuf = mmap.mmap(self.ufd, self.size, mmap.MAP_SHARED,
                              mmap.PROT_READ | mmap.PROT_WRITE)

    def rd(self, o):
        return struct.unpack("<I", self.reg[o:o + 4])[0]

    def wr(self, o, v):
        self.reg[o:o + 4] = struct.pack("<I", v & 0xFFFFFFFF)

    def sync_dev(self, n):
        for name, val in (("sync_offset", 0), ("sync_size", n), ("sync_for_device", 1)):
            try:
                with open(os.path.join(SYSFS, name), "w") as f:
                    f.write(str(val))
            except Exception:
                pass

    def run(self, gray_bytes):
        self.ubuf[0:NPIX] = gray_bytes
        self.sync_dev(NPIX)
        self.wr(R_FRAME, FRAME_ADDR)
        self.wr(R_CTRL, 1)
        t0 = time.time()
        while True:
            if (self.rd(R_STAT) & 0x2) or (time.time() - t0 > 2.0):
                break
            time.sleep(0.0002)
        dt = (time.time() - t0) * 1000
        st = self.rd(R_STAT)
        raw = bytearray()
        for i in range(MAX_WORDS):
            self.wr(R_IDX, i)
            raw += struct.pack("<I", self.rd(R_IDX))
        n = raw[0]
        cands = []
        for i in range(n):
            b = raw[1 + i * 7: 1 + i * 7 + 7]
            if len(b) < 7:
                break
            cands.append({"x": (b[0] << 8) | b[1], "y": (b[2] << 8) | b[3],
                          "area": b[5], "peak": b[6]})
        return st, cands, dt, n


def main():
    binp = sys.argv[1]
    jsonp = sys.argv[2] if len(sys.argv) > 2 else None
    data = open(binp, "rb").read()
    assert len(data) == NPIX, "图大小应为 %d，实际 %d" % (NPIX, len(data))
    hw = HW()
    print("PL VERSION = 0x%08X   udmabuf phys=0x%08X size=%d" %
          (hw.rd(R_VER), hw.phys, hw.size))
    st, cands, dt, n = hw.run(data)
    print("STATUS=0x%08X done=%d err=%d  n_cand=%d  PL=%.2f ms" %
          (st, (st >> 1) & 1, (st >> 2) & 1, n, dt))
    cands.sort(key=lambda c: -c["peak"])
    print("检出 %d 个（按 peak 排序，前 15）:" % len(cands))
    for c in cands[:15]:
        print("   (%3d,%3d) area=%2d peak=%3d" % (c["x"], c["y"], c["area"], c["peak"]))
    if jsonp:
        gt = json.load(open(jsonp))
        print("真值 %d 个：" % len(gt["gt"]))
        hit = 0
        for g in gt["gt"]:
            best = None
            for c in cands:
                if abs(c["x"] - g["x"]) <= 4 and abs(c["y"] - g["y"]) <= 4:
                    if best is None or c["peak"] > best["peak"]:
                        best = c
            if best:
                hit += 1
                print("    %2dpx @(%3d,%3d) → (%3d,%3d) area=%2d peak=%3d" %
                      (g["size"], g["x"], g["y"], best["x"], best["y"], best["area"], best["peak"]))
            else:
                print("    %2dpx @(%3d,%3d) 未检出" % (g["size"], g["x"], g["y"]))
        print("=== 检出率 %d/%d = %.1f%% ===" % (hit, len(gt["gt"]), 100.0 * hit / len(gt["gt"])))


if __name__ == "__main__":
    main()
