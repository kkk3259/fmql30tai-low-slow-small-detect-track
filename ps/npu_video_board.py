# -*- coding: utf-8 -*-
"""
板端 NPU 视频推理（npu_video_board.py）—— 在 FMQL30TAI 板子上跑的完整流水线

[WARN] 本文件是**板端专用**脚本，依赖：
    · /root/pywork/modelzoo_utils/pyrtutils/     （官方 Python 工具包，需从 PC 传上去）
    · icraft 3.39.0（pip 的 aarch64 whl，必须与系统库 libicraft_*.so 版本一致）
    · OpenCV 4.6（板载镜像自带）、numpy 1.23

    在 PC 上跑请用 ps/npu_video.py（那版用 dry-run 后端，不需要板子）。

实测结果（2026-10-25，/root/bird.mp4，630 帧，零失败）：
    letterbox 11.20 ms | forward 28.30 ms | read 2.38 ms | reset 4.24 ms
    loop 合计 46.12 ms → 21.68 fps（纯计算）
    含采集+写盘         → 6.25 fps（100.9 s 跑完 630 帧）
    检出 1.01 个/帧，30/630 帧无检出；输出视频 5.1 MB / 21 秒
    三帧抽检（f100/f300/f500）框位置全部正确

 三个必须知道的坑（都是实测踩出来的，官方文档没写）：

  ① session.forward() 之后**必须**调 device.reset(1)
     · 不调 → 从第二次起返回第一次的缓存（连全黑图都给 0.9183 的"无人机置信度"）
     · 或直接崩：sync failed in op_id:2018's output_tensor
     · 官方只在 pyrt_main_example.py 里写了一行 device.reset(1)，没说为什么
     · 代价：约 1.3 ms（20 帧）~ 4.2 ms（长跑，可能与 I/O 竞争有关）

  ② 输出 Tensor 不能 np.array()，必须 t.read(memoryview(buf), 0, nbyte)
     · np.array(t) 报：The Tensor's memchunk is of ADDR type, can't be converted to buffer!

  ③ ocm_option 不能传 -1（官方 yaml 写法），只认 0/1/2/3/4
     · 传 -1 抛：ocm_option < -1 > is not supported

  另：cv2.setNumThreads(4) 让 letterbox 从 12.84 ms 降到 9.61 ms（1280×720→640×360）

用法（板上）：
    cd /root/pywork
    python3 npu_video_board.py --src /root/bird.mp4 --out /root/out/npu_bird.mp4
    python3 npu_video_board.py --src /root/bird.mp4 --max-frames 20      # 快速验证
"""

import argparse
import os
import sys
import time

#  板端 pyrtutils 路径（按实际上传位置改）
PYRTUTILS_DIR = "/root/pywork"
if PYRTUTILS_DIR not in sys.path:
    sys.path.insert(0, PYRTUTILS_DIR)

from modelzoo_utils.pyrtutils import Netinfo, initSession, loadNetwork, numpy2Tensor  # noqa: E402
from icraft import xrt  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

# ================================================================ 常量
NET = 640
REG_MAX = 16
STRIDES = (8, 16, 32)
N_ANCHORS = sum((NET // s) ** 2 for s in STRIDES)      # 80²+40²+20² = 8400
BOX_BYTES = 1 * 64 * N_ANCHORS * 4                     # 2,150,400
CLS_BYTES = 1 * 1 * N_ANCHORS * 4                      # 33,600
CONF_TH = 0.25
IOU_TH = 0.45
PAD_VALUE = 114                                        # A 指定的 letterbox 填充值
DEVICE_URL = "axi://zg330aiu?npu=0x40000000&dma=0x80000000"


# ================================================================ 预处理
def letterbox(bgr, dst=NET, pad=PAD_VALUE):
    """
    等比缩放到 dst×dst，上下/左右补边（A 给的规格：1280×720 → 640×360 + 上下各 140 行）。

    返回 (canvas, scale, left, top)；后处理用这三个值反算回原图。
    """
    h, w = bgr.shape[:2]
    sc = min(dst / w, dst / h)
    nw, nh = int(round(w * sc)), int(round(h * sc))
    resized = cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((dst, dst, 3), pad, np.uint8)
    left, top = (dst - nw) // 2, (dst - nh) // 2
    canvas[top:top + nh, left:left + nw] = resized
    return canvas, sc, left, top


# ================================================================ 后处理
def dfl_decode(box_raw, cls_raw, sel, reg_max=REG_MAX, strides=STRIDES, net=NET):
    """DFL 解码：只对候选集（sel）做，避免白算 8000+ 个 anchor。

    移植自 deploy/cpu_decode_demo.py（原版 torch → numpy）。
    返回 (boxes[N,4] 像素 xywh, conf[N])。
    """
    box = np.asarray(box_raw, np.float32).reshape(4, reg_max, -1)[:, :, sel]
    e = np.exp(box - box.max(axis=1, keepdims=True))
    p = e / e.sum(axis=1, keepdims=True)
    dfl = (p * np.arange(reg_max, dtype=np.float32).reshape(1, -1, 1)).sum(axis=1).T

    anchors, stride_rep = [], []
    for s in strides:
        n = net // s
        g = np.arange(n, dtype=np.float32)
        yy, xx = np.meshgrid(g, g, indexing="ij")
        anchors.append(np.stack((xx.reshape(-1) + 0.5, yy.reshape(-1) + 0.5), 1))
        stride_rep.append(np.full((n * n, 1), float(s), np.float32))
    a = np.concatenate(anchors)[sel]
    st = np.concatenate(stride_rep)[sel]

    lt, rb = dfl[:, :2], dfl[:, 2:]
    xy = ((a - lt) + (a + rb)) / 2.0
    wh = (a + rb) - (a - lt)
    conf = 1.0 / (1.0 + np.exp(-np.asarray(cls_raw, np.float32).reshape(-1)[sel]))
    return np.concatenate((xy, wh), 1) * st, conf


def nms(boxes, scores, thr=IOU_TH):
    """标准 NMS（xywh 中心格式），返回保留索引。"""
    if len(boxes) == 0:
        return np.empty(0, np.int64)
    x1, y1 = boxes[:, 0] - boxes[:, 2] / 2, boxes[:, 1] - boxes[:, 3] / 2
    x2, y2 = boxes[:, 0] + boxes[:, 2] / 2, boxes[:, 1] + boxes[:, 3] / 2
    areas = np.maximum(x2 - x1, 0) * np.maximum(y2 - y1, 0)
    order = scores.argsort()[::-1]
    keep = []
    while order.size:
        i = order[0]
        keep.append(i)
        if order.size == 1:
            break
        r = order[1:]
        inter = (np.maximum(np.minimum(x2[i], x2[r]) - np.maximum(x1[i], x1[r]), 0) *
                 np.maximum(np.minimum(y2[i], y2[r]) - np.maximum(y1[i], y1[r]), 0))
        order = r[(inter / (areas[i] + areas[r] - inter + 1e-9)) <= thr]
    return np.array(keep, np.int64)


# ================================================================ 主流程
def main():
    ap = argparse.ArgumentParser(description="板端 ZG330 NPU 视频推理")
    ap.add_argument("--src", default="/root/bird.mp4")
    ap.add_argument("--out", default="/root/out/npu_out.mp4")
    ap.add_argument("--json", default="/root/a_model/yolo11n_drone_trunc_ZG.json")
    ap.add_argument("--raw", default="/root/a_model/yolo11n_drone_trunc_ZG.raw")
    ap.add_argument("--max-frames", type=int, default=0, help="0 = 全部")
    ap.add_argument("--threads", type=int, default=4, help="cv2 线程数（影响 letterbox 速度）")
    a = ap.parse_args()

    cv2.setNumThreads(a.threads)      #  优化：1280×720 resize 从 12.84 → 9.61 ms

    # ---- 初始化 ----
    network = loadNetwork(a.json, a.raw)
    netinfo = Netinfo(network)
    device = xrt.Device.Open(DEVICE_URL)
    session = initSession("zg330", network, device,
                          ocm_option=4,                    #  不能传 -1
                          mmuMode=bool(netinfo.mmu),       # 官方建议 netinfo.mmu or mmuMode
                          open_speedmode=False,
                          open_compressFtmp=False)
    session.enableTimeProfile(True)
    session.apply()
    print("[init] network ops=%d  i_shape=%s  mmu=%s"
          % (len(network.ops), netinfo.i_shape, netinfo.mmu))

    # 预分配读缓冲（每帧复用，避免反复 malloc 2.2 MB）
    buf_box = np.zeros(BOX_BYTES, np.uint8)
    buf_cls = np.zeros(CLS_BYTES, np.uint8)

    cap = cv2.VideoCapture(a.src)
    if not cap.isOpened():
        sys.exit("打不开输入：%s" % a.src)
    W, H = int(cap.get(3)), int(cap.get(4))
    fps_in = cap.get(5) or 30.0
    n_total = int(cap.get(7))
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    vw = cv2.VideoWriter(a.out, cv2.VideoWriter_fourcc(*"mp4v"), fps_in, (W, H))
    print("[src] %s  %dx%d @%.0f  total=%d" % (a.src, W, H, fps_in, n_total))

    # ---- 主循环 ----
    tt = [0.0] * 5          # letterbox / forward / read / reset / total
    okc = fails = 0
    dcount = []
    i = -1
    t_all = time.perf_counter()

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        i += 1
        try:
            t0 = time.perf_counter()
            lb, sc, l, t = letterbox(frame)
            rgb = cv2.cvtColor(lb, cv2.COLOR_BGR2RGB)
            ten = numpy2Tensor(rgb.reshape(1, NET, NET, 3), network)
            t1 = time.perf_counter()

            out = session.forward([ten])
            t2 = time.perf_counter()

            #  坑②：必须 read()，不能 np.array()
            out[0].read(memoryview(buf_box), 0, BOX_BYTES)
            out[1].read(memoryview(buf_cls), 0, CLS_BYTES)
            t3 = time.perf_counter()

            cls = buf_cls.view(np.float32)
            conf = 1.0 / (1.0 + np.exp(-cls))
            sel = np.flatnonzero(conf >= CONF_TH)
            ndet = 0
            if sel.size:
                boxes, scores = dfl_decode(buf_box.view(np.float32), cls, sel)
                keep = nms(boxes, scores)
                ndet = len(keep)
                for b in boxes[keep]:
                    # 反算回原图：先减 padding，再除 scale
                    cx, cy = (b[0] - l) / sc, (b[1] - t) / sc
                    bw, bh = b[2] / sc, b[3] / sc
                    x1 = int(max(0, cx - bw / 2)); y1 = int(max(0, cy - bh / 2))
                    x2 = int(min(W - 1, cx + bw / 2)); y2 = int(min(H - 1, cy + bh / 2))
                    if x2 - x1 < 2 or y2 - y1 < 2:
                        continue
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(frame, "drone", (x1, max(y1 - 5, 12)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA)

            #  坑①：每帧必须 reset，否则输出不刷新 / 崩溃
            device.reset(1)
            t4 = time.perf_counter()

            tt[0] += t1 - t0; tt[1] += t2 - t1
            tt[2] += t3 - t2; tt[3] += t4 - t3; tt[4] += t4 - t0
            okc += 1
            dcount.append(ndet)
        except Exception as exc:  # noqa: BLE001
            fails += 1
            if fails <= 3:
                print("[warn] f%d FAILED: %s" % (i, str(exc).split("\n")[-1][:90]))
            try:
                device.reset(1)
            except Exception:
                pass

        cv2.putText(frame, "f%d det%d" % (i, dcount[-1] if dcount else 0),
                    (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 1, cv2.LINE_AA)
        vw.write(frame)
        if a.max_frames and (i + 1) >= a.max_frames:
            break
        if i and i % 60 == 0:
            print("  ... f%d  %.1f s" % (i, time.perf_counter() - t_all))

    cap.release()
    vw.release()

    # ---- 汇总 ----
    n = max(okc, 1)
    wall = time.perf_counter() - t_all
    print("\n=== RESULT ===")
    print("  frames %d ok / %d failed / %d total, wall %.1f s" % (okc, fails, i + 1, wall))
    print("  letterbox %.2f | forward %.2f | read %.2f | reset %.2f | loop %.2f ms"
          % (tt[0] / n * 1e3, tt[1] / n * 1e3, tt[2] / n * 1e3, tt[3] / n * 1e3, tt[4] / n * 1e3))
    print("  throughput: %.2f fps (loop) | %.2f fps (incl capture+write)"
          % (1e3 / (tt[4] / n * 1e3), okc / wall))
    if dcount:
        print("  det/frame: avg %.2f  max %d  zero %d/%d"
              % (sum(dcount) / len(dcount), max(dcount),
                 sum(1 for x in dcount if x == 0), len(dcount)))
    if os.path.exists(a.out):
        print("  output: %s  %.1f MB" % (a.out, os.path.getsize(a.out) / 1e6))

    try:
        device.reset(1)
    except Exception:
        pass
    xrt.Device.Close(device)
    print("DONE")


if __name__ == "__main__":
    main()
