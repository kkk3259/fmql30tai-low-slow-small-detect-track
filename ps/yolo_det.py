#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""yolo_det.py —— yolo11n_drone 解码（已由 probe_yolo6 实测确定）。

判定：anchor-free、v5 混合式
    score = sigmoid(out1) * max(sigmoid(out0[4:]))
    cx = (2*sig(x) + gx - 0.5) * stride
    cy = (2*sig(y) + gy - 0.5) * stride
    w  = 4 * sig(w)^2 * stride
    h  = 4 * sig(h)^2 * stride
"""
import glob
import json
import os

import cv2
import numpy as np

NPU = "/root/npu/yolo11n_drone_trunc_ZG"


def sig(x):
    return 1.0 / (1.0 + np.exp(-x))


def read_tensor(o):
    d = json.loads(str(o.dtype()))
    shp = [int(x) for x in d["shape"]]
    n = int(np.prod(shp))
    buf = bytearray(n * 4)
    o.read(buf, 0, n * 4)
    return np.frombuffer(bytes(buf), dtype=np.float32).reshape(shp)


def _merge(boxes, dist=18.0):
    """把中心点相距很近的框并成一个（取并集 + 最高分）——治同一目标多框。"""
    out = []
    for b in boxes:                      # 已按分数降序
        hit = None
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        for o in out:
            ox, oy = (o[0] + o[2]) / 2, (o[1] + o[3]) / 2
            if (cx - ox) ** 2 + (cy - oy) ** 2 <= dist * dist:
                hit = o
                break
        if hit is None:
            out.append(list(b))
        else:
            hit[0] = min(hit[0], b[0]); hit[1] = min(hit[1], b[1])
            hit[2] = max(hit[2], b[2]); hit[3] = max(hit[3], b[3])
    return out


class Yolo:
    def __init__(self):
        import icraft.xrt as xrt
        from icraft.xir import Network
        from icraft.zg330backend import ZG330Backend
        from icraft.host_backend import HostBackend
        self.xrt = xrt
        self.net = Network.CreateFromJsonFile(NPU + ".json")
        self.net.lazyLoadParamsFromFile(NPU + ".raw")
        self.dev = xrt.Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
        self.sess = xrt.Session.Create([ZG330Backend, HostBackend], self.net.view(0),
                                       [self.dev, xrt.HostDevice.Default()])
        self.sess.apply()
        self.tt = self.net.ops[0].outputs[0].tensorType()
        try:
            self.tt.setShape([1, 640, 640, 3])
        except Exception:
            pass

    def detect(self, bgr, conf=None, iou=None):
        conf = float(os.environ.get('CONF', '0.45')) if conf is None else conf
        iou = float(os.environ.get('IOU', '0.30')) if iou is None else iou
        h0, w0 = bgr.shape[:2]
        sx, sy = w0 / 640.0, h0 / 640.0      # 解码在 640x640 空间，必须映回原图
        rgb = cv2.cvtColor(cv2.resize(bgr, (640, 640)), cv2.COLOR_BGR2RGB)[None]
        t = self.xrt.Tensor(np.ascontiguousarray(rgb.astype(np.uint8)), self.tt)
        outs = self.sess.forward([t])
        o0 = read_tensor(outs[0])[0]
        o1 = read_tensor(outs[1])[0, 0]
        sc = sig(o1) * sig(o0[4:]).max(axis=0)
        idx = np.where(sc >= conf)[0]
        boxes = []
        for i in idx:
            i = int(i)
            if i < 6400:
                gx, gy, st = i % 80, i // 80, 8
            elif i < 8000:
                j = i - 6400
                gx, gy, st = j % 40, j // 40, 16
            else:
                j = i - 8000
                gx, gy, st = j % 20, j // 20, 32
            a = sig(o0[:4, i])
            cx = (2 * a[0] + gx - 0.5) * st
            cy = (2 * a[1] + gy - 0.5) * st
            w = 4 * a[2] * a[2] * st
            h = 4 * a[3] * a[3] * st
            boxes.append([(cx - w / 2) * sx, (cy - h / 2) * sy,
                          (cx + w / 2) * sx, (cy + h / 2) * sy, float(sc[i])])
        if not boxes:
            return []
        # NMS
        boxes.sort(key=lambda b: -b[4])
        keep = []
        for b in boxes:
            ok = True
            for k in keep:
                ix = max(0, min(b[2], k[2]) - max(b[0], k[0]))
                iy = max(0, min(b[3], k[3]) - max(b[1], k[1]))
                inter = ix * iy
                u = (b[2] - b[0]) * (b[3] - b[1]) + (k[2] - k[0]) * (k[3] - k[1]) - inter
                if u > 0 and inter / u > iou:
                    ok = False
                    break
            if ok:
                keep.append(b)
        return _merge(keep)


def main():
    import sys
    y = Yolo()
    files = sys.argv[1:] or sorted(glob.glob("/root/ip2/t*.png"))
    for f in files:
        img = cv2.imread(f)
        if img is None:
            print("MISS", f)
            continue
        bs = y.detect(img)
        print("%-22s %4dx%-4d  n=%d" % (os.path.basename(f), img.shape[1], img.shape[0], len(bs)))
        vis = img.copy()
        for b in bs[:12]:
            cv2.rectangle(vis, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), (0, 255, 0), 2)
            cv2.putText(vis, "%.2f" % b[4], (int(b[0]), int(b[1]) - 5), 0, 0.6, (0, 255, 0), 2)
        cv2.imwrite("/root/ip2/yolo_" + os.path.basename(f), cv2.resize(vis, (640, int(640 * img.shape[0] / img.shape[1]))))


if __name__ == "__main__":
    main()
