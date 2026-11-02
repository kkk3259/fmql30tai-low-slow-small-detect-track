#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cam3d_test.py —— 三域链路无界面自测：相机 → PL(三域) → NPU 分类 → 打印。

用于在写网页之前先确认整条链在板上跑得通：
  - 帧走 PL-DDR（ICraft 分配），寄存器走平台口 0x400C0000
  - 候选表经 0x10 窗口读回
  - 每个候选裁 128x128 交给 cls128 NPU 判"是不是目标"

用法：
  python3 cam3d_test.py --n 20            # 跑 20 帧
  python3 cam3d_test.py --n 20 --npu 0    # 只跑 PL，不跑 NPU
  python3 cam3d_test.py --img a.png       # 用图片代替相机
"""
import argparse
import os
import sys
import time

import numpy as np

REG = 0x400C0000
R_CTRL, R_FADDR, R_RADDR, R_STATUS = 0x00, 0x04, 0x08, 0x0C
R_WIN, R_AR = 0x10, 0x90
NPIX = 640 * 360
X_SHIFT = 62             # 预热后实测稳定：x_det = x_true - 62，故 +62 还原
BORDER = 24              # 上下边带过滤（pad 伪目标在 y≈359）


def unpack(words):
    flat = []
    for w in words:
        flat += [(w >> s) & 0xFF for s in (0, 8, 16, 24)]
    n = flat[0] if flat else 0
    out = []
    for j in range(n):
        b = flat[1 + j * 7: 8 + j * 7]
        if len(b) < 7:
            break
        out.append({
            "x": (((b[0] << 8) | b[1]) + X_SHIFT) % 640,
            "y": (b[2] << 8) | b[3],
            "area": (b[4] << 8) | b[5],
            "peak": b[6],
        })
    return [c for c in out if BORDER <= c["y"] < 360 - BORDER and c["area"] >= 4]


class PL3D(object):
    def __init__(self):
        from icraft.xrt import Device
        self.dev = Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
        self.reg = self.dev.defaultRegRegion()
        self.mem = self.dev.defaultMemRegion()
        self.ch = self.mem.malloc(NPIX)
        bp = self.ch.begin if not callable(self.ch.begin) else self.ch.begin()
        ad = getattr(bp, "addr", None)
        self.base = ad() if callable(ad) else ad
        self.reg.write(REG + R_FADDR, self.base)
        self.reg.write(REG + R_RADDR, self.base)
        time.sleep(0.02)
        print("PL3D base=0x%X VERSION=0x%08X"
              % (self.base, self.reg.read(REG + 0x14) & 0xFFFFFFFF))

    def run(self, gray):
        self.ch.write(0, gray.tobytes(), NPIX)
        a0 = self.reg.read(REG + R_AR) & 0xFFFFFFFF
        st = 0
        t0 = time.time()
        # 触发可能被吞（实测连续触发时约一半不启动），AR 不长就重发，最多 5 次
        for _try in range(5):
            self.reg.write(REG + R_CTRL, 0)
            time.sleep(0.001)
            self.reg.write(REG + R_CTRL, 1)
            t1 = time.time()
            while time.time() - t1 < 0.15:
                st = self.reg.read(REG + R_STATUS) & 0xFFFFFFFF
                a1 = self.reg.read(REG + R_AR) & 0xFFFFFFFF
                # 必须等 FSM 跑完（busy=0）再读候选表，否则读到写了一半的旧表
                if (a1 - a0) > 3000 and not (st & 1):
                    break
                time.sleep(0.0001)
            a1 = self.reg.read(REG + R_AR) & 0xFFFFFFFF
            st = self.reg.read(REG + R_STATUS) & 0xFFFFFFFF
            if (a1 - a0) > 3000 and not (st & 1):
                break
        dt = (time.time() - t0) * 1000
        # 第一遍窗口读常返回全 0（实测），读两遍取第二遍
        for _pass in range(2):
            words = []
            for i in range(15):   # MAX_CAND=32 -> 1+32*7=225B -> 57 字
                self.reg.write(REG + R_WIN, i)
                self.reg.read(REG + R_WIN)
                words.append(self.reg.read(REG + R_WIN) & 0xFFFFFFFF)
            if _pass == 0:
                time.sleep(0.0001)
        return unpack(words), st, dt


class NPU(object):
    def __init__(self, jsn, raw, dev=None):
        from icraft.xir import Network
        import icraft.xrt as xrt
        from icraft.zg330backend import ZG330Backend
        from icraft.host_backend import HostBackend
        self.net = Network.CreateFromJsonFile(jsn)
        self.net.lazyLoadParamsFromFile(raw)
        if dev is None:
            dev = xrt.Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
        self.sess = xrt.Session.Create(
            [ZG330Backend, HostBackend], self.net.view(0),
            [dev, xrt.HostDevice.Default()])
        self.sess.apply()
        self.xrt = xrt

    def predict(self, img128):
        import cv2 as _cv2
        if img128.ndim == 2:                      # 灰度 -> 3 通道（模型要 NHWC 3 通道）
            img128 = _cv2.cvtColor(img128, _cv2.COLOR_GRAY2BGR)
        if img128.shape[:2] != (128, 128):
            img128 = _cv2.resize(img128, (128, 128), interpolation=_cv2.INTER_AREA)
        op = self.net.ops[0].outputs[0]
        tt = op.tensorType()
        tt.setShape([1, 128, 128, 3])
        t = self.xrt.Tensor(np.ascontiguousarray(img128), tt)
        outs = self.sess.forward([t])
        buf = bytearray(8)
        outs[0].read(buf, 0, 8)
        return np.frombuffer(bytes(buf), np.float32)


def crop(gray, cx, cy, side=40):
    import cv2
    r = max(8, side)
    x0 = max(0, cx - r)
    y0 = max(0, cy - r)
    p = gray[y0:y0 + 2 * r, x0:x0 + 2 * r]
    if p.size == 0:
        p = np.zeros((2 * r, 2 * r), np.uint8)
    return cv2.resize(p, (128, 128), interpolation=cv2.INTER_AREA)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--npu", type=int, default=1)
    ap.add_argument("--img", default="")
    ap.add_argument("--cam", type=int, default=0)
    a = ap.parse_args()

    import cv2
    pl = PL3D()
    npu = None
    if a.npu:
        d = os.environ.get("NPU_DIR", "/root/npu")
        npu = NPU(d + "/cls128_drone_ZG.json", d + "/cls128_drone_ZG.raw")
        print("NPU ok")

    cap = None
    if a.img:
        base = cv2.imread(a.img, cv2.IMREAD_GRAYSCALE)
        assert base is not None, a.img
    else:
        cap = cv2.VideoCapture(a.cam)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    t_sum = 0.0
    n_sum = 0
    for k in range(a.n):
        if a.img:
            gray = base
        else:
            ok, f = cap.read()
            if not ok:
                print("cap fail")
                break
            gray = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)[60:420, :]
        import cv2 as _cv
        gray = _cv.resize(gray, (640, 360))
        if gray.shape[:2] != (360, 640):
            gray = gray[:360, :640]
        res, st, dt = pl.run(gray)
        t_sum += dt
        n_sum += len(res)
        line = "F%02d PL=%.1fms st=0x%08X n=%d" % (k, dt, st, len(res))
        if npu and res:
            v = [npu.predict(crop(gray, c["x"], c["y"],
                                  int(np.sqrt(max(c["area"], 1))) + 12)) for c in res]
            line += " | " + " ".join("%d:(%.2f,%.2f)" % (i, p[0], p[1])
                                     for i, p in enumerate(v))
        print(line)
    if cap:
        cap.release()
    print("AVG PL=%.1fms  cand/frame=%.1f" % (t_sum / max(1, a.n), n_sum / max(1, a.n)))


if __name__ == "__main__":
    main()
