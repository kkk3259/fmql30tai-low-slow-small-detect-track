#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PL 粗筛 + NPU 判定 级联（三域位流下运行）

流程：
  1. 打开 ICraft 设备（三域位流里含 AI_Mate）与 cls128 二分类网络
  2. 候选来源二选一：
       --boxes "x,y;x,y;..."   手工/外部给定的候选框（用于验证 NPU 判定环节）
       --from-pl               调 PL 检测器取候选（要求三域里检测器坐标正确）
  3. 每个候选裁 128×128 灰度 → 复制成 3 通道 → 送 NPU → 得 [p0, p1]
  4. 按阈值保留，打印结果与耗时

用法示例：
  python3 cascade.py --img /root/ip2/card_synth.png --boxes "100,150;300,150"
  python3 cascade.py --img /root/ip2/pl_input.png --from-pl --thr 0.5
"""
import os
import sys
import time
import argparse

import numpy as np
import cv2

sys.path.insert(0, "/root/ip2")

# ---------- NPU ----------
MODEL_DIR = "/root/npu"
RAW = os.path.join(MODEL_DIR, "cls128_drone_ZG.raw")
JSN = os.path.join(MODEL_DIR, "cls128_drone_ZG.json")


class Classifier:
    def __init__(self, raw=RAW, jsn=JSN, url="axi://zg330aiu?npu=0x40000000&dma=0x80000000"):
        import icraft.xrt as xrt
        from icraft.xir import Network
        from icraft.zg330backend import ZG330Backend
        from icraft.host_backend import HostBackend

        self.xrt = xrt
        self.net = Network.CreateFromJsonFile(jsn)
        self.net.lazyLoadParamsFromFile(raw)
        self.dev = xrt.Device.Open(url)
        self.sess = xrt.Session.Create(
            [ZG330Backend, HostBackend], self.net.view(0),
            [self.dev, xrt.HostDevice.Default()])
        self.sess.apply()
        self.tt = self.net.ops[0].outputs[0].tensorType()
        self.n_out = len(self.net.outputs())
        self.t_call = 0.0
        self.t_fwd = 0.0

    def predict(self, img128_bgr):
        """输入 HxWx3 BGR uint8（128×128），返回 softmax 概率数组（float32）"""
        t0 = time.time()
        x = cv2.cvtColor(img128_bgr, cv2.COLOR_BGR2RGB) if img128_bgr.ndim == 3 else img128_bgr
        x = np.ascontiguousarray(x[None].astype(np.uint8))
        tt = self.tt
        tt.setShape([1, 128, 128, 3])
        tin = self.xrt.Tensor(x, tt)
        self.t_call += time.time() - t0

        t1 = time.time()
        outs = self.sess.forward([tin])
        buf = bytearray(8)
        outs[0].read(buf, 0, 8)
        self.t_fwd += time.time() - t1
        return np.frombuffer(bytes(buf), dtype=np.float32)


# ---------- 裁框 ----------
def crop_box(gray, x, y, side=128, out=128):
    """以 (x,y) 为中心裁 side×side（紧贴目标），再缩放成 out×out。越界用边缘像素填充。"""
    h, w = gray.shape[:2]
    half = side // 2
    x0, y0 = int(x) - half, int(y) - half
    x1, y1 = x0 + side, y0 + side
    pad_l, pad_t = max(0, -x0), max(0, -y0)
    pad_r, pad_b = max(0, x1 - w), max(0, y1 - h)
    x0c, y0c = max(0, x0), max(0, y0)
    x1c, y1c = min(w, x1), min(h, y1)
    patch = gray[y0c:y1c, x0c:x1c]
    if pad_l or pad_t or pad_r or pad_b:
        patch = cv2.copyMakeBorder(patch, pad_t, pad_b, pad_l, pad_r, cv2.BORDER_REPLICATE)
    if patch.shape[0] != out or patch.shape[1] != out:
        interp = cv2.INTER_AREA if patch.shape[0] > out else cv2.INTER_LINEAR
        patch = cv2.resize(patch, (out, out), interpolation=interp)
    return cv2.cvtColor(patch, cv2.COLOR_GRAY2BGR)


def parse_boxes(s):
    out = []
    for part in s.split(";"):
        part = part.strip()
        if not part:
            continue
        xy = part.split(",")
        out.append((float(xy[0]), float(xy[1])))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--img", required=True)
    ap.add_argument("--boxes", default="")
    ap.add_argument("--from-pl", action="store_true")
    ap.add_argument("--thr", type=float, default=0.5, help="判为目标的正类概率阈值")
    ap.add_argument("--cls", type=int, default=1, help="目标类的下标（0 或 1）")
    ap.add_argument("--limit", type=int, default=32)
    ap.add_argument("--side", type=int, default=48, help="--boxes 模式下的裁剪边长")
    ap.add_argument("--zoom", type=float, default=3.0, help="按面积定边长时的放大倍数")
    a = ap.parse_args()

    gray = cv2.imread(a.img, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        print("读不到图:", a.img)
        return 2
    print("图像 %dx%d  %s" % (gray.shape[1], gray.shape[0], a.img))

    boxes = []          # [(x, y, side), ...]
    if a.boxes:
        boxes = [(x, y, a.side) for (x, y) in parse_boxes(a.boxes)]
        print("候选来源: 手工 --boxes  数量", len(boxes))
    elif a.from_pl:
        import detect3d as d
        det = d.Detector() if hasattr(d, "Detector") else None
        if det is None:
            print("detect3d 里没有 Detector 类，请检查")
            return 2
        st, cands, dt = det.detect(gray)
        print("候选来源: PL 检测  status=0x%08x  n=%d  %.1f ms" % (st, len(cands), dt))
        boxes = []
        for c in cands[:a.limit]:
            side = int(max(16, min(256, (max(1, c["area"]) ** 0.5) * a.zoom)))
            boxes.append((c["x"], c["y"], side))
    else:
        print("必须给 --boxes 或 --from-pl")
        return 2

    clf = Classifier()
    print("NPU: ops=%d  输出维度=%d  就绪" % (len(list(clf.net.ops)), clf.n_out))

    kept, drop = [], []
    t0 = time.time()
    for (x, y, side) in boxes:
        patch = crop_box(gray, x, y, side=side)
        p = clf.predict(patch)
        score = float(p[a.cls])
        rec = (int(x), int(y), score, [float(v) for v in p])
        (kept if score >= a.thr else drop).append(rec)
    total_ms = (time.time() - t0) * 1000

    print("\n--- 判定结果（阈值 %.2f，正类=%d）---" % (a.thr, a.cls))
    for x, y, s, p in kept:
        print("  [目标] (%4d,%4d)  正类 %.3f   raw %s" % (x, y, s, ",".join("%.3f" % v for v in p)))
    for x, y, s, p in drop:
        print("  [丢弃] (%4d,%4d)  正类 %.3f   raw %s" % (x, y, s, ",".join("%.3f" % v for v in p)))
    print("\n候选 %d → 保留 %d  丢弃 %d" % (len(boxes), len(kept), len(drop)))
    print("耗时 %.1f ms（%.2f ms/个）  前向 %.2f ms" % (total_ms, total_ms / max(1, len(boxes)), clf.t_fwd * 1000))
    return 0


if __name__ == "__main__":
    sys.exit(main())
