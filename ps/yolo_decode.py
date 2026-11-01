#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""yolo_decode.py —— yolo11n_drone_trunc 前向 + 解码 + NMS + 画图。

用法：python3 yolo_decode.py <图片> [输出png] [conf阈值]
"""
import json
import sys

import numpy as np
import cv2

from icraft.xir import Network
import icraft.xrt as xrt
from icraft.zg330backend import ZG330Backend
from icraft.host_backend import HostBackend

J = "/root/npu/yolo11n_drone_trunc_ZG.json"
R = "/root/npu/yolo11n_drone_trunc_ZG.raw"

IMG = sys.argv[1] if len(sys.argv) > 1 else "/root/ip2/t2_twodrones.png"
OUT = sys.argv[2] if len(sys.argv) > 2 else "/root/ip2/yolo_out.png"
CONF = float(sys.argv[3]) if len(sys.argv) > 3 else 0.25
IOU = 0.45


def read_tensor(o):
    """按 dtype() 里的 shape 读回 numpy。"""
    meta = json.loads(str(o.dtype()))
    shape = meta["shape"]
    dt = meta.get("element_dtype", "@fp(32)")
    n = int(np.prod(shape))
    if "fp(32)" in dt:
        nbytes, npdt = n * 4, np.float32
    elif "int(8)" in dt:
        nbytes, npdt = n, np.int8
    elif "uint(8)" in dt:
        nbytes, npdt = n, np.uint8
    else:
        nbytes, npdt = n * 4, np.float32
    buf = bytearray(nbytes)
    o.read(buf, 0, nbytes)
    return np.frombuffer(bytes(buf), dtype=npdt).reshape(shape), meta


def nms(boxes, scores, iou_thr=0.45):
    """boxes: [N,4] as x1,y1,x2,y2"""
    if len(boxes) == 0:
        return []
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(int(i))
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-9)
        order = order[1:][iou <= iou_thr]
    return keep


def main():
    img = cv2.imread(IMG)
    if img is None:
        print("IMG_FAIL")
        return
    h0, w0 = img.shape[:2]

    net = Network.CreateFromJsonFile(J)
    net.lazyLoadParamsFromFile(R)
    print("NET_OK ops =", len(net.ops))
    dev = xrt.Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
    sess = xrt.Session.Create([ZG330Backend, HostBackend], net.view(0),
                              [dev, xrt.HostDevice.Default()])
    sess.apply()
    print("SESSION_OK")

    inp = cv2.cvtColor(cv2.resize(img, (640, 640)), cv2.COLOR_BGR2RGB)
    tin = xrt.Tensor(np.ascontiguousarray(inp.reshape(1, 640, 640, 3)),
                     net.ops[0].outputs[0].tensorType())
    import time
    t0 = time.time()
    outs = sess.forward([tin])
    dt = (time.time() - t0) * 1000.0
    print("FORWARD_OK n_out=%d  %.2f ms" % (len(outs), dt))

    tensors = []
    for i, o in enumerate(outs):
        arr, meta = read_tensor(o)
        print("  out[%d] shape=%s dtype=%s  min=%.4f max=%.4f"
              % (i, meta["shape"], meta.get("element_dtype"), float(arr.min()), float(arr.max())))
        tensors.append((arr, meta))

    # ---- 解码：找 [1,4+C,N] 的那一个 ----
    pred = None
    for arr, meta in tensors:
        if arr.ndim == 3 and arr.shape[0] == 1 and arr.shape[2] > 1000:
            pred = arr[0]          # [4+C, N]
            break
    if pred is None:
        print("NO_PRED_TENSOR")
        return
    C = pred.shape[0] - 4
    p = pred.T                      # [N, 4+C]
    boxes_xywh = p[:, :4]
    scores = p[:, 4:]
    conf = scores.max(axis=1)
    cls = scores.argmax(axis=1)

    # 判断坐标是像素还是归一化
    mx = float(np.abs(boxes_xywh).max())
    scale = 1.0 if mx > 2.0 else 640.0
    print("  C=%d  MAXABS=%.2f  -> coords are %s" % (C, mx, "px" if scale == 1.0 else "normalized"))

    m = conf >= CONF
    print("  above %.2f: %d / %d   conf_max=%.3f" % (CONF, int(m.sum()), len(conf), float(conf.max())))

    b = boxes_xywh[m] * scale
    s = conf[m]
    c = cls[m]
    xyxy = np.stack([b[:, 0] - b[:, 2] / 2, b[:, 1] - b[:, 3] / 2,
                     b[:, 0] + b[:, 2] / 2, b[:, 1] + b[:, 3] / 2], axis=1)
    keep = nms(xyxy, s, IOU)
    print("  after NMS: %d" % len(keep))

    vis = img.copy()
    sx, sy = w0 / 640.0, h0 / 640.0
    for k in keep:
        x1, y1, x2, y2 = xyxy[k]
        p1 = (int(x1 * sx), int(y1 * sy))
        p2 = (int(x2 * sx), int(y2 * sy))
        cv2.rectangle(vis, p1, p2, (0, 255, 0), 2)
        cv2.putText(vis, "%.2f c%d" % (s[k], c[k]), (p1[0], max(12, p1[1] - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(vis, "yolo11n_drone  %.1fms  boxes=%d" % (dt, len(keep)), (8, 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2, cv2.LINE_AA)
    cv2.imwrite(OUT, vis)
    print("OUT", OUT)


if __name__ == "__main__":
    main()
