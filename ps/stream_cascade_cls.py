# -*- coding: utf-8 -*-
"""stream_cascade_cls.py —— 核心层联调：粗筛 + NPU 二分类（网格版/逐个版）+ 跟踪

【干什么用】
  验证并演示甲方案的「核心层」闭环：
    摄像头 → PS 双路形态学(Top-Hat + Black-Hat) + CFAR + CCL → 候选
           → 按 peak 取前 N 个 → 裁 cell×cell 拼成网格 → NPU 判真/假
           → PS 卡尔曼跟踪 → 画框 → MJPEG 推流

  它解决的核心问题：把「<8px 小目标召回」从全图 YOLO 的 48.5% 提到 85%+

【为什么用网格版而不是逐个判】
  cls128 一次判 1 个 128×128，64 个候选要 64 次 forward。
  每次 forward 的 host 固定开销（DMA/同步）不随输入尺寸缩小，
  所以网格版（一次判 N 个）才是正解。

  实测粗筛"按 peak 截 top-N"的召回曲线（100 张真实图）：
    截断   15-35   35-70   70-150  150-400  合计
    16     36%     40%     80%     100%     64%     ← 16 格不够
    32     64%     48%     88%     100%     75%
    64     80%     68%     92%     100%     85%     ← 64 格（8×8@64）最佳
    82(不截断) 92%  88%     96%     100%     94%     ← 但 64 格装不下

  ⇒ 选 64 格：几何约束（512×512 放 8×8 个 64×64）与召回的最佳交点

【两种网格配置】
  --grid 8 --cell 64   → 8×8=64 格，每格 64×64（grid64，首选）
                          514 覆盖 15~70px（完整率 100%/96%）
  --grid 4 --cell 128  → 4×4=16 格，每格 128×128（grid16，A 已交付）
                          召回只到 64%，仅作对比

【模型输出契约（A 交付，已核验）】
  cls128 : 输入 [1,128,128,3] → 输出 [1,2]      p_pos = out[0][1]
  grid16 : 输入 [1,512,512,3] → 输出 [1,16,2]   p_pos = out[0][k][1]
  grid64 : 输入 [1,512,512,3] → 输出 [1,64,2]   格序 k = 行×grid + 列
  全部 NHWC UINT8，/255 已折入量化（UINT8 直通），阈值 0.5

【资源】
  PS  ：双路形态学 + 拼网格 + 跟踪（约 17.5 ms，OpenCV，不占 PL）
  NPU ：grid/cls 二分类器
  不依赖 PL 位流 —— PL 没通时的主交付形态

【用法】
  # PC 验证链路（不需要板子/icraft）
  python ps/stream_cascade_cls.py --src test --judge dummy

  # 板上：grid64（首选）
  python3 ps/stream_cascade_cls.py --src /dev/video1 --judge grid --grid 8 --cell 64 \
      --json deploy/grid64/grid64_drone_ZG.json --raw deploy/grid64/grid64_drone_ZG.raw

  # 板上：grid16（A 已交付，召回只 64%）
  python3 ps/stream_cascade_cls.py --src /dev/video1 --judge grid --grid 4 --cell 128 \
      --json deploy/grid16/grid16_drone_ZG.json --raw deploy/grid16/grid16_drone_ZG.raw

  # 板上：cls128 逐个判（小批量精判，N 个候选 N 次 forward）
  python3 ps/stream_cascade_cls.py --src /dev/video1 --judge cls128 --cands 8 \
      --json deploy/cls128/cls128_drone_ZG.json --raw deploy/cls128/cls128_drone_ZG.raw
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

CANVAS = 512          # 网格画布边长（grid16 和 grid64 都是 512）


# ============================================================ 裁剪 + 拼网格

def build_canvas(gray, cands, grid, cell):
    """按候选质心裁 cell×cell，行优先拼成 (grid*cell)² 灰度网格。

    越界补 0。返回 (canvas, 实际填充格数)。
    实测拼接耗时：16 格 0.03 ms、64 格 0.09 ms（预分配 + 切片赋值）。
    """
    side = grid * cell
    canvas = np.zeros((side, side), np.uint8)
    half = cell // 2
    nfill = 0
    for idx, c in enumerate(cands[:grid * grid]):
        r, col = divmod(idx, grid)          # 行优先：k = 行×grid + 列
        cx, cy = int(c["x"]), int(c["y"])
        x0, y0 = cx - half, cy - half
        x1, y1 = x0 + cell, y0 + cell
        sx0, sy0 = max(0, x0), max(0, y0)
        sx1, sy1 = min(W, x1), min(H, y1)
        if sx1 <= sx0 or sy1 <= sy0:
            continue
        canvas[r * cell + (sy0 - y0):r * cell + (sy1 - y0),
               col * cell + (sx0 - x0):col * cell + (sx1 - x0)] = gray[sy0:sy1, sx0:sx1]
        nfill += 1
    return canvas, nfill


def crop_patch(gray, cx, cy, size):
    """以 (cx, cy) 为中心裁 size×size，越界补 0（cls128 逐个判用）"""
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
    """假分类器：用 patch 峰值归一化模拟概率，PC 上验证链路用。

    仅用于跑通流程，不代表真实精度。
    """

    def __init__(self, grid=8, cell=64):
        self.grid, self.cell = grid, cell

    def open(self):
        return None

    def judge_grid(self, canvas):
        """返回 grid² 个 p_pos（用每格的峰值归一化模拟）"""
        out = []
        for i in range(self.grid * self.grid):
            r, c = divmod(i, self.grid)
            cellimg = canvas[r * self.cell:(r + 1) * self.cell,
                             c * self.cell:(c + 1) * self.cell]
            out.append(float(cellimg.max()) / 255.0 if cellimg.size else 0.0)
        return out

    def judge_one(self, patch):
        return float(patch.max()) / 255.0

    def close(self):
        pass


class _NpuJudge(object):
    """NPU 判别器公共部分：加载模型、建 session、复用输入 tensor"""

    DEVICE_URL = "axi://zg330aiu?npu=0x40000000&dma=0x80000000"

    def __init__(self, json_path, raw_path, in_side, thr=0.5):
        self.json_path = json_path
        self.raw_path = raw_path
        self.in_side = in_side          # 网络输入边长（128 或 512）
        self.thr = thr
        self._session = None
        self._device = None
        self._ten_in = None

    def _open_common(self):
        sys.path.insert(0, "/root/pywork")
        from modelzoo_utils.pyrtutils import (        # noqa: E402
            Netinfo, initSession, loadNetwork, numpy2Tensor,
        )
        from icraft import xrt                          # noqa: E402

        network = loadNetwork(self.json_path, self.raw_path)
        netinfo = Netinfo(network)
        self._device = xrt.Device.Open(self.DEVICE_URL)
        self._session = initSession(
            "zg330", network, self._device,
            ocm_option=4, mmuMode=bool(netinfo.mmu),
            open_speedmode=False, open_compressFtmp=False)
        self._session.apply()
        # 输入 tensor 建一次，之后只 write（复用省 4.26 ms）
        self._ten_in = numpy2Tensor(
            np.zeros((1, self.in_side, self.in_side, 3), np.uint8), network)
        return netinfo

    def _forward_gray(self, gray_img):
        """灰度 → 复制三通道 → 写 tensor → forward → 返回输出张量字节"""
        rgb = np.ascontiguousarray(np.stack([gray_img, gray_img, gray_img], axis=-1))
        self._ten_in.write(0, memoryview(rgb), rgb.nbytes)
        out = self._session.forward([self._ten_in])
        self._device.reset(1)
        return out[0]

    def close(self):
        if self._device is not None:
            try:
                from icraft import xrt
                xrt.Device.Close(self._device)
            except Exception:
                pass
            self._device = None


class GridJudge(_NpuJudge):
    """网格版：一次 forward 判 grid² 个格子"""

    def __init__(self, json_path, raw_path, grid=8, cell=64, thr=0.5):
        super().__init__(json_path, raw_path, in_side=grid * cell, thr=thr)
        self.grid, self.cell = grid, cell
        self._buf = np.zeros(grid * grid * 2, np.float32)

    def open(self):
        return self._open_common()

    def judge_grid(self, canvas):
        out = self._forward_gray(canvas)
        self._buf.fill(0.0)
        out.read(memoryview(self._buf.view(np.uint8)), 0, self._buf.nbytes)
        # [1, grid², 2] → 每格取 p_pos = [..., 1]
        arr = self._buf.reshape(self.grid * self.grid, 2)
        return arr[:, 1].tolist()


class Cls128Judge(_NpuJudge):
    """逐个判版：一次 forward 判 1 个 128×128"""

    def __init__(self, json_path, raw_path, side=128, thr=0.5):
        super().__init__(json_path, raw_path, in_side=side, thr=thr)
        self.side = side
        self._buf = np.zeros(2, np.float32)

    def open(self):
        return self._open_common()

    def judge_one(self, patch):
        out = self._forward_gray(patch)
        self._buf.fill(0.0)
        out.read(memoryview(self._buf.view(np.uint8)), 0, self._buf.nbytes)
        return float(self._buf[1])


# ============================================================ 主循环

def main():
    ap = argparse.ArgumentParser(
        description="核心层：粗筛 + NPU 二分类（网格/逐个）+ 跟踪")
    ap.add_argument("--src", default="test",
                    help="'test'=合成帧 | '0'/'1'=摄像头编号 | 视频文件路径")
    ap.add_argument("--judge", default="dummy", choices=["dummy", "grid", "cls128"])
    ap.add_argument("--grid", type=int, default=8, choices=[4, 8],
                    help="网格边长：8→8×8=64 格（grid64，首选）；4→4×4=16 格（grid16）")
    ap.add_argument("--cell", type=int, default=64, choices=[64, 128],
                    help="每格边长：64 配 grid=8；128 配 grid=4")
    ap.add_argument("--cands", type=int, default=0,
                    help="送判候选数（0=用 grid²，cls128 模式建议 8）")
    ap.add_argument("--json", default="deploy/grid64/grid64_drone_ZG.json")
    ap.add_argument("--raw", default="deploy/grid64/grid64_drone_ZG.raw")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--disp-w", type=int, default=640)
    ap.add_argument("--jpeg-q", type=int, default=70)
    ap.add_argument("--topk", type=int, default=64, help="双路粗筛每路候选上限")
    ap.add_argument("--thr", type=float, default=0.5)
    ap.add_argument("--confirm", type=int, default=3)
    ap.add_argument("--frames", type=int, default=0, help="跑多少帧后停（0=无限）")
    a = ap.parse_args()

    n_cand = a.cands or (a.grid * a.grid if a.judge in ("grid", "dummy") else 8)
    print("  src=%s  judge=%s  grid=%d  cell=%d  cands=%d  thr=%.2f"
          % (a.src, a.judge, a.grid, a.cell, n_cand, a.thr))

    # ---- 判别器 ----
    if a.judge == "dummy":
        judge = DummyJudge(a.grid, a.cell)
        judge.open()
        print("  dummy 判别器：用峰值归一化模拟（PC 验证链路用）")
    elif a.judge == "grid":
        judge = GridJudge(a.json, a.raw, a.grid, a.cell, a.thr)
        try:
            info = judge.open()
            print("  ✓ 网格模型已加载（%d×%d 格，输入 %d）"
                  % (a.grid, a.grid, a.grid * a.cell))
        except Exception as e:
            print("  ✗ 模型加载失败：%s" % e)
            print("    检查 --json/--raw 路径、icraft 环境、NPU 是否在位流里")
            print("    PC 上请用 --judge dummy")
            return 1
    else:
        judge = Cls128Judge(a.json, a.raw, a.cell, a.thr)
        try:
            judge.open()
            print("  ✓ cls128 已加载（逐个判，%d 次 forward/帧）" % n_cand)
        except Exception as e:
            print("  ✗ 模型加载失败：%s" % e)
            return 1

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

    fid = done = 0
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
            cs = det(gray)[:n_cand]              # 双路粗筛 + 按 peak 截前 N

            if a.judge == "cls128":
                # 逐个判：N 个候选 N 次 forward
                pts = []
                for c in cs:
                    patch = crop_patch(gray, c["x"], c["y"], a.cell)
                    if judge.judge_one(patch) > a.thr:
                        pts.append((c["x"], c["y"], c["area"]))
                nfill = len(pts)
            else:
                # 网格判：拼一张 512×512，一次 forward 判 N 个
                canvas, nfill = build_canvas(gray, cs, a.grid, a.cell)
                probs = judge.judge_grid(canvas)
                pts = [(cs[i]["x"], cs[i]["y"], cs[i]["area"])
                       for i in range(min(len(cs), len(probs)))
                       if probs[i] > a.thr]
            t_det = (time.time() - t0) * 1000

            confirmed = tracker.step(pts)

            bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
            bgr = draw(bgr, pts, confirmed, "cascade-%s" % a.judge, fps)
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
                print("  [%d] det=%.1f ms  cand=%d  fill=%d  pass=%d  trk=%d  fps=%.1f"
                      % (done, t_det, len(cs), nfill, len(pts), len(confirmed), fps))
    except KeyboardInterrupt:
        print("\n  停止")
    finally:
        grab.stop()
        judge.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
