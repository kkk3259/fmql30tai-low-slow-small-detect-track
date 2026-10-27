# -*- coding: utf-8 -*-
"""stream_cascade_cls.py —— 核心层联调：PS 双路粗筛 + cls128 二分类 + 跟踪

【干什么用】
  验证并演示甲方案的「核心层」闭环：
    摄像头 → PS 双路形态学(Top-Hat + Black-Hat) + CFAR + CCL → 候选
           → 按 peak 取前 N 个 → 逐个裁 128×128 → cls128 判「真目标/虚警」
           → PS 卡尔曼跟踪 → 画框 → MJPEG 推流

  它解决的核心问题：把「<8px 小目标召回」从全图 YOLO 的 48.5% 提到 90%+
  （粗筛双路召回 94%，cls128 识别率 93%）。

【用什么资源】
  · PS（4×A53）：双路形态学 + 跟踪（OpenCV，约 17 ms，不占用 PL）
  · NPU（ZG330）：cls128 二分类器，deploy/cls128/cls128_drone_ZG.json/.raw
  · 不依赖 PL 位流 —— 这是 PL 没通时的主交付形态

【在路线中的地位】
  甲方案分两层：
    核心层（本脚本）= 粗筛 + NPU 二分类 + 跟踪，不依赖 PL
    加速层        = 把粗筛从 PS(17ms) 挪到 PL(5ms)
  PL 通了之后，把 DualDetector 换成 PlBackend 即升级为完整甲方案，
  本脚本的 ClsJudge / Tracker / 推流全部复用，不改。

【依赖的模型输出契约（A 交付，已核验）】
  输入 : [1,128,128,3]  NHWC  UINT8（灰度复制三通道，R=G=B）
  输出 : [1,2]  fp32（已含 softmax），p_pos = out[0][1]，阈值 0.5
  归一化: /255 已折入量化，UINT8 直通不除 255

【用法】
  # 板上真判别（需要 icraft 环境 + cls128 文件）
  python3 ps/stream_cascade_cls.py --src /dev/video1 --json deploy/cls128/cls128_drone_ZG.json --raw deploy/cls128/cls128_drone_ZG.raw

  # PC 上验证链路（假分类器，不需要板子/icraft）
  python ps/stream_cascade_cls.py --src test --judge dummy

  # 板上假分类器（验证除 NPU 外的整条链路）
  python3 ps/stream_cascade_cls.py --src 1 --judge dummy
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import numpy as np
import cv2

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "ps"))

# 复用 stream_cascade.py 的采集/检测/跟踪/推流组件
from stream_cascade import (                       # noqa: E402
    W, H, Grabber, FakeGrabber, DualDetector, Tracker, MjpegServer, draw,
)

CLS_IN = 128          # cls128 输入边长


# ============================================================ 裁剪

def crop_patch(gray, cx, cy, size=CLS_IN):
    """以 (cx, cy) 为中心裁 size×size，越界补 0"""
    half = size // 2
    x0, y0 = int(cx) - half, int(cy) - half
    patch = np.zeros((size, size), np.uint8)
    for dy in range(size):
        sy = y0 + dy
        if sy < 0 or sy >= H:
            continue
        sx0 = max(0, x0)
        sx1 = min(W, x0 + size)
        if sx1 <= sx0:
            continue
        patch[dy, sx0 - x0:sx1 - x0] = gray[sy, sx0:sx1]
    return patch


# ============================================================ 判别器

class DummyJudge(object):
    """假分类器：用 peak 归一化模拟概率，PC 上验证链路用。

    规则：peak 越强越像真目标，> 0.5 通过。仅用于跑通流程，不代表真实精度。
    """

    def __init__(self, thr=0.5):
        self.thr = thr
        self._peak_max = 255.0

    def open(self):
        return None

    def judge(self, gray128):
        # 用 patch 内最大灰度归一化当"置信度"
        peak = float(gray128.max())
        return peak / self._peak_max

    def close(self):
        pass


class ClsJudge(object):
    """cls128 二分类器（NPU 后端），判一个 128×128 ROI 是真目标还是虚警"""

    def __init__(self, json_path, raw_path,
                 device_url="axi://zg330aiu?npu=0x40000000&dma=0x80000000",
                 thr=0.5):
        self.json_path = json_path
        self.raw_path = raw_path
        self.device_url = device_url
        self.thr = thr
        self._network = None
        self._session = None
        self._device = None
        self._ten_in = None
        self._out = np.zeros(2, np.float32)

    def open(self):
        sys.path.insert(0, "/root/pywork")
        from modelzoo_utils.pyrtutils import (        # noqa: E402
            Netinfo, initSession, loadNetwork, numpy2Tensor,
        )
        from icraft import xrt                          # noqa: E402

        self._network = loadNetwork(self.json_path, self.raw_path)
        netinfo = Netinfo(self._network)
        self._device = xrt.Device.Open(self.device_url)
        self._session = initSession(
            "zg330", self._network, self._device,
            ocm_option=4, mmuMode=bool(netinfo.mmu),
            open_speedmode=False, open_compressFtmp=False)
        self._session.apply()
        # 输入 tensor 建一次，之后只 write（复用 tensor 省 4.26 ms）
        self._ten_in = numpy2Tensor(
            np.zeros((1, CLS_IN, CLS_IN, 3), np.uint8), self._network)
        return netinfo

    def judge(self, gray128):
        """返回 p_pos（真目标概率），灰度复制三通道"""
        rgb = np.ascontiguousarray(
            np.stack([gray128, gray128, gray128], axis=-1))
        self._ten_in.write(0, memoryview(rgb), rgb.nbytes)
        out = self._session.forward([self._ten_in])
        self._out.fill(0.0)
        # 主输出 [1,2] fp32 = 8 字节；"第二出口残渣"忽略
        out[0].read(memoryview(self._out.view(np.uint8)), 0, self._out.nbytes)
        self._device.reset(1)
        return float(self._out[1])

    def close(self):
        if self._session is not None:
            try:
                self._device.reset(1)
            except Exception:
                pass
        if self._device is not None:
            try:
                from icraft import xrt
                xrt.Device.Close(self._device)
            except Exception:
                pass
            self._device = None


# ============================================================ 主循环

def main():
    ap = argparse.ArgumentParser(
        description="核心层：PS 双路粗筛 + cls128 二分类 + 跟踪")
    ap.add_argument("--src", default="test",
                    help="'test'=合成帧 | '0'/'1'=摄像头编号 | 视频文件路径")
    ap.add_argument("--judge", default="dummy", choices=["dummy", "real"])
    ap.add_argument("--json", default="deploy/cls128/cls128_drone_ZG.json")
    ap.add_argument("--raw", default="deploy/cls128/cls128_drone_ZG.raw")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--disp-w", type=int, default=640)
    ap.add_argument("--jpeg-q", type=int, default=70)
    ap.add_argument("--topk", type=int, default=64,
                    help="双路粗筛每路的候选上限")
    ap.add_argument("--n", type=int, default=8,
                    help="送入 NPU 判别的候选数（peak 排序取前 N）")
    ap.add_argument("--thr", type=float, default=0.5, help="真/假阈值")
    ap.add_argument("--confirm", type=int, default=3)
    ap.add_argument("--frames", type=int, default=0, help="跑多少帧后停（0=无限）")
    a = ap.parse_args()

    print("  src=%s  judge=%s  topk=%d  n=%d  thr=%.2f"
          % (a.src, a.judge, a.topk, a.n, a.thr))

    # ---- 判别器 ----
    if a.judge == "real":
        judge = ClsJudge(a.json, a.raw, thr=a.thr)
        try:
            info = judge.open()
            print("  ✓ cls128 已加载（ops=%d）" % len(info.ops) if info else "")
        except Exception as e:
            print("  ✗ cls128 加载失败：%s" % e)
            print("    检查 --json/--raw 路径、icraft 环境、NPU 设备是否在位流里")
            return 1
    else:
        judge = DummyJudge(thr=a.thr)
        judge.open()
        print("  dummy 判别器：用 peak 归一化模拟（PC 验证链路用）")

    # ---- 采集 ----
    if a.src == "test":
        grab = FakeGrabber()
        print("  合成帧源：真实 1080P 背景 + 一个亮点一个暗点")
    else:
        grab = Grabber(a.src, gray=True)
    grab.start()

    print("  等待首帧...")
    for _ in range(200):
        if grab.latest() is not None:
            break
        time.sleep(0.05)
    if grab.latest() is None:
        print("  取不到帧，检查 --src")
        grab.stop()
        judge.close()
        return 1

    det = DualDetector(topk=a.topk)
    tracker = Tracker(confirm=a.confirm)
    srv = MjpegServer(a.port, a.jpeg_q)
    srv.start()
    print("  推流： http://<IP>:%d/stream" % a.port)

    fid = 0
    done = 0
    t_prev = time.time()
    fps = 0.0
    try:
        while True:
            gray = grab.latest()
            if gray is None:
                time.sleep(0.005)
                continue
            if gray.ndim != 2:
                gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
            if gray.shape[1] != W or gray.shape[0] != H:
                gray = cv2.resize(gray, (W, H), interpolation=cv2.INTER_AREA)

            t0 = time.time()
            cs = det(gray)                       # 双路粗筛
            cs = cs[:a.n]                        # peak 排序取前 N
            pts = []
            for c in cs:
                patch = crop_patch(gray, c["x"], c["y"])
                p = judge.judge(patch)           # cls128 判真/假
                if p > a.thr:
                    pts.append((c["x"], c["y"], c["area"]))
            t_det = (time.time() - t0) * 1000

            confirmed = tracker.step(pts)        # 航迹关联

            bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
            bgr = draw(bgr, pts, confirmed, "cascade-cls", fps)
            if a.disp_w and bgr.shape[1] != a.disp_w:
                s = a.disp_w / float(bgr.shape[1])
                bgr = cv2.resize(bgr, (a.disp_w, int(bgr.shape[0] * s)))
            srv.push(bgr)

            fid += 1
            done += 1
            if a.frames and done >= a.frames:
                print("  跑完 %d 帧，退出" % done)
                break

            now = time.time()
            if now - t_prev >= 0.5:
                fps = fid / max(now - t_prev, 1e-9)
                t_prev, fid = now, 0
                print("  [%d] det=%.1f ms  cand=%d  judge=%d  trk=%d  fps=%.1f"
                      % (done, t_det, len(cs), len(pts), len(confirmed), fps))
    except KeyboardInterrupt:
        print("\n  停止")
    finally:
        grab.stop()
        judge.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
