# -*- coding: utf-8 -*-
"""
NPU 视频推理流水线（npu_video.py）

作用：把 A 交付的 YOLOv11n（截断头）跑在板上 ZG330 NPU 上，处理视频文件/摄像头，
      输出带检测框的视频。填补赛题要求 3 的「端到端性能测试」缺口。

模型事实（来自 deploy/ 交付与 docs/11 第十章 10.12，均经板上实测核对）：
    输入     (1, 640, 640, 3)  NHWC  UINT8  RGB   （/255 已折入量化，板端不要再除）
    输出     box_raw[1,64,8400] + cls_raw[1,1,8400]   FP32
    截断头   无 DFL softmax / 无 sigmoid / 无 NMS —— 全部在 CPU 侧做
    8400 排列  8 倍层 80×80 → 16 倍层 40×40 → 32 倍层 20×20，层内行优先
    解码      strides [8,16,32]，anchor = grid 中心 (i+0.5, j+0.5)
    阈值      conf ≥ 0.25, NMS IoU ≥ 0.45

后处理算法照 deploy/cpu_decode_demo.py（A 已与 FP32 模型数值对拍验证），
但**从 torch 移植为 numpy** —— 板端没有 torch。

⚠️ 推理后端（infer）尚未接入，见 IcraftBackend 的说明：
    板子上有 zg330backend.cpython-38-aarch64-linux-gnu.so，理论上 Python 可直调，
    但需在板上实测确认。在确认前，用 --dry-run 可以验证除推理外的全部代码。

用法：
    # 板上（真推理，等后端接好后）
    python3 ps/npu_video.py --src /root/bird.mp4 --out /root/out/npu_demo.mp4

    # 任意机器（假推理，验证后处理与画框逻辑）
    python3 ps/npu_video.py --src bird.mp4 --out out_dry.mp4 --dry-run
"""

import argparse
import os
import sys
import time

import cv2
import numpy as np

# ---------------------------------------------------------------- 模型常量
NET_W = 640
NET_H = 640
REG_MAX = 16
STRIDES = (8, 16, 32)
NUM_ANCHORS = sum((NET_W // s) * (NET_H // s) for s in STRIDES)   # 6400+1600+400 = 8400
CONF_THR = 0.25
IOU_THR = 0.45


# ================================================================ 预处理
def letterbox(img_bgr, dst_w=NET_W, dst_h=NET_H):
    """
    保持宽高比缩放到 640×640，多余部分补零（YOLO 标准做法）。

    ⚠️ 不能直接 cv2.resize(img, (640,640))：16:9 → 1:1 会把画面横向压扁，
       框位置全部偏。必须 letterbox，后处理再用 scale/left/top 反算回原图。

    返回：
        canvas : (640,640,3) uint8 RGB
        scale  : 缩放比例
        left,top : 左上角填充像素数
    """
    h, w = img_bgr.shape[:2]
    scale = min(dst_w / w, dst_h / h)
    nw, nh = int(round(w * scale)), int(round(h * scale))
    resized = cv2.resize(img_bgr, (nw, nh), interpolation=cv2.INTER_LINEAR)

    canvas = np.zeros((dst_h, dst_w, 3), dtype=np.uint8)
    left, top = (dst_w - nw) // 2, (dst_h - nh) // 2
    canvas[top:top + nh, left:left + nw] = resized

    # OpenCV 读的是 BGR，模型要 RGB
    canvas = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
    return canvas, scale, left, top


# ================================================================ 后处理
def dfl_decode(box_raw, cls_raw, imgsz=NET_W, reg_max=REG_MAX, strides=STRIDES,
               sel_idx=None):
    """
    DFL 解码：把原始张量解成像素坐标的 xywh + 置信度。

    移植自 deploy/cpu_decode_demo.py:decode（原版用 torch，此处 numpy 等价实现）。

    参数：
        box_raw : (1,64,8400) 或 (64,8400)，FP32 → reshape 成 (4, 16, 8400)
        cls_raw : (1,1,8400) 或 (8400)，FP32
        sel_idx : 只解码这些 anchor 的下标（None = 全量）。
                  ★ 传候选集下标可大幅省时 —— A 的建议是"别全量解"。

    返回：
        boxes : (N, 4) 像素 xywh（xy 为框中心），N = len(sel_idx) 或 8400
        conf  : (N,)   sigmoid 后的置信度
    """
    box = np.asarray(box_raw, dtype=np.float32).reshape(4, reg_max, -1)   # [4,16,8400]
    conf_all = 1.0 / (1.0 + np.exp(-np.asarray(cls_raw, dtype=np.float32).reshape(-1)))

    if sel_idx is None:
        sel_idx = np.arange(box.shape[2])

    # 只对候选集切片：DFL 的 softmax 是主要开销，能省则省
    sub = box[:, :, sel_idx]                                              # [4,16,n]

    m = sub.max(axis=1, keepdims=True)
    e = np.exp(sub - m)
    p = e / e.sum(axis=1, keepdims=True)                                  # [4,16,n]
    dfl = (p * np.arange(reg_max, dtype=np.float32).reshape(1, -1, 1)).sum(axis=1)  # [4,n]
    dfl = dfl.T                                                           # [n,4] = (l,t,r,b)

    # anchor：只取候选集对应的 grid 中心
    anchors, stride_rep = [], []
    base = 0
    for s in strides:
        n = imgsz // s
        g = np.arange(n, dtype=np.float32)
        yy, xx = np.meshgrid(g, g, indexing="ij")
        anchors.append(np.stack((xx.reshape(-1) + 0.5, yy.reshape(-1) + 0.5), axis=1))
        stride_rep.append(np.full((n * n, 1), float(s), dtype=np.float32))
        base += n * n
    a = np.concatenate(anchors, axis=0)[sel_idx]                          # [n,2]
    st = np.concatenate(stride_rep, axis=0)[sel_idx]                      # [n,1]

    lt = dfl[:, :2]                        # (left, top)
    rb = dfl[:, 2:]                        # (right, bottom)
    xy = ((a - lt) + (a + rb)) / 2.0       # 框中心
    wh = (a + rb) - (a - lt)               # 宽高
    boxes = np.concatenate((xy, wh), axis=1) * st                         # 像素 xywh

    return boxes, conf_all[sel_idx]


def nms(boxes_xywh, scores, iou_thr=IOU_THR):
    """标准 NMS。输入 xywh（中心+宽高），返回保留的索引。"""
    if len(boxes_xywh) == 0:
        return np.empty(0, dtype=np.int64)

    b = boxes_xywh
    x1 = b[:, 0] - b[:, 2] / 2.0
    y1 = b[:, 1] - b[:, 3] / 2.0
    x2 = b[:, 0] + b[:, 2] / 2.0
    y2 = b[:, 1] + b[:, 3] / 2.0
    areas = np.maximum(x2 - x1, 0) * np.maximum(y2 - y1, 0)

    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        if order.size == 1:
            break
        rest = order[1:]
        xx1 = np.maximum(x1[i], x1[rest])
        yy1 = np.maximum(y1[i], y1[rest])
        xx2 = np.minimum(x2[i], x2[rest])
        yy2 = np.minimum(y2[i], y2[rest])
        inter = np.maximum(xx2 - xx1, 0) * np.maximum(yy2 - yy1, 0)
        iou = inter / (areas[i] + areas[rest] - inter + 1e-9)
        order = rest[iou <= iou_thr]
    return np.array(keep, dtype=np.int64)


def postprocess(box_raw, cls_raw, scale, left, top,
                conf_thr=CONF_THR, iou_thr=IOU_THR, max_det=30):
    """
    完整后处理：置信度过滤 → 候选集 DFL 解码 → NMS → 坐标反算回原图。

    ★ 顺序很重要（这是 A 在交付清单里的建议）：**先全量 sigmoid 过滤，
      再只对候选集做 DFL**。反过来（先全量 DFL 再过滤）会白算 8000+ 个
      用不上的 anchor —— 实测后处理耗时差 5~7 倍。

    返回：
        [{"x1","y1","x2","y2","conf"}, ...]，坐标为**原图**像素
    """
    # ① 全量 sigmoid（一次向量化，很便宜），筛出候选 anchor
    conf_all = 1.0 / (1.0 + np.exp(-np.asarray(cls_raw, dtype=np.float32).reshape(-1)))
    sel = np.flatnonzero(conf_all >= conf_thr)
    if sel.size == 0:
        return []

    # ② 只对候选集做 DFL 解码
    boxes, conf = dfl_decode(box_raw, cls_raw, sel_idx=sel)

    # ③ NMS
    keep = nms(boxes, conf, iou_thr)
    boxes, conf = boxes[keep], conf[keep]
    if len(boxes) == 0:
        return []

    # ④ 按置信度取前 max_det
    if len(boxes) > max_det:
        ordr = conf.argsort()[::-1][:max_det]
        boxes, conf = boxes[ordr], conf[ordr]

    # ⑤ 从 letterbox 坐标反算回原图：先减 padding，再除 scale
    xy = (boxes[:, :2] - np.array([left, top], dtype=np.float32)) / scale
    wh = boxes[:, 2:] / scale
    x1 = xy[:, 0] - wh[:, 0] / 2.0
    y1 = xy[:, 1] - wh[:, 1] / 2.0
    x2 = xy[:, 0] + wh[:, 0] / 2.0
    y2 = xy[:, 1] + wh[:, 1] / 2.0

    return [{"x1": float(x1[i]), "y1": float(y1[i]),
             "x2": float(x2[i]), "y2": float(y2[i]),
             "conf": float(conf[i])} for i in range(len(conf))]


# ================================================================ 推理后端
class IcraftBackend:
    """
    ZG330 NPU 推理后端（**待接入**）。

    板上已确认的可用信息（docs/11 §10.12）：
        设备      axi://zg330aiu?npu=0x40000000&dma=0x80000000
        JSON/Raw  deploy/yolo11n_drone_trunc_ZG.json / .raw
        裁剪      view_except_op_ids = [0, 275]（op0=Input、op275=Output 在 Host 侧）
        实测      单帧硬件耗时 7.955 ms（6 次，极差 0.1%）

    三条可能的接入路径，按成本排序：
      ① Python 直调：板上存在 zg330backend.cpython-38-aarch64-linux-gnu.so，
         若 `import icraft` / `import zg330backend` 可用，直接把 tensor 喂进去即可。
      ② 编译官方 demo：fpai_demo_package_26040701 的 modelzoo_utils 里有
         yolov5_npu_actor.hpp 可作为模板（C++）。
      ③ icraft-run 子进程：每次启动约 800 ms（模型加载 735 ms + Raw 145 ms），
         不适合逐帧调用，只能用于抽样校验。

    ⚠️ 在确认①之前，请用 --dry-run 验证后处理与画图逻辑。
    """

    def __init__(self, json_path, raw_path, device_url=None,
                 pyrtutils_dir="/root/pywork"):
        self.json_path = json_path
        self.raw_path = raw_path
        self.device_url = device_url or (
            "axi://zg330aiu?npu=0x40000000&dma=0x80000000")
        self._pyrtutils_dir = pyrtutils_dir      # 板端 pyrtutils 所在目录
        self._session = None
        self._network = None
        self._netinfo = None
        self._device = None
        self._numpy2Tensor = None
        self._xrt = None
        self._buf_box = None
        self._buf_cls = None

    def open(self):
        """
        初始化 NPU（2026-10-25 板上实测通过）。

        依赖：/root/pywork 下的 pyrtutils（官方 Python 工具包）+ icraft 3.39.0
        实测全链路见 docs/11 §10.13；视频流水线见 §10.14。
        """
        try:
            if self._pyrtutils_dir not in sys.path:
                sys.path.insert(0, self._pyrtutils_dir)
            from modelzoo_utils.pyrtutils import (          # noqa: PLC0415
                Netinfo, initSession, loadNetwork,
            )
            from icraft import xrt                      # noqa: PLC0415
        except Exception as exc:                        # noqa: BLE001
            raise RuntimeError(
                "无法导入 pyrtutils / icraft（当前环境没有板端依赖）。\n"
                "  依赖目录: %s\n"
                "  原始异常: %s\n"
                "  · 若在 PC 上：请用 --dry-run\n"
                "  · 若在板端：确认 pyrtutils 已上传、icraft 版本与系统库一致（3.39.0）"
                % (self._pyrtutils_dir, exc)) from exc

        self._xrt = xrt

        self._network = loadNetwork(self.json_path, self.raw_path)
        self._netinfo = Netinfo(self._network)
        self._device = xrt.Device.Open(self.device_url)
        # ★ ocm_option 只能 0/1/2/3/4，传 -1（官方 yaml 写法）会抛异常
        self._session = initSession(
            "zg330", self._network, self._device,
            ocm_option=4,
            mmuMode=bool(self._netinfo.mmu),
            open_speedmode=False,
            open_compressFtmp=False,
        )
        # ★ apply() 失败时必须主动释放设备：否则 device 处于半初始化状态，
        #   后续运行会报 "DMA Read time out"，只能重启板子恢复。
        try:
            self._session.enableTimeProfile(True)
            self._session.apply()
        except Exception:
            self.close()
            raise

        # 预分配输出缓冲（每帧复用）
        self._buf_box = np.zeros(1 * 64 * 8400 * 4, np.uint8)
        self._buf_cls = np.zeros(1 * 1 * 8400 * 4, np.uint8)

        # numpy2Tensor 也来自 pyrtutils
        import modelzoo_utils.pyrtutils as _pyrtutils    # noqa: PLC0415
        self._numpy2Tensor = _pyrtutils.numpy2Tensor
        return self

    def infer(self, img_rgb_640):
        """
        参数：img_rgb_640 —— (640,640,3) uint8，RGB，会被当作 (1,640,640,3) NHWC 输入
        返回：(box_raw, cls_raw) —— (1,64,8400) 和 (1,1,8400) 的 float32

        ⚠️ 不要在这里做 /255 归一化：模型已折入量化。
        ⚠️ forward 之后**必须** device.reset(1)，否则从第二次起返回首次缓存，
           或直接崩 sync failed in op_id:2018（详见 docs/11 §10.14.3 坑①）。
        """
        if self._session is None:
            raise RuntimeError("IcraftBackend 未 open()")

        ten = self._numpy2Tensor(
            np.ascontiguousarray(img_rgb_640).reshape(1, 640, 640, 3), self._network)
        out = self._session.forward([ten])

        # ★ 输出 Tensor 不能 np.array()（报 memchunk is of ADDR type），必须 read()
        out[0].read(memoryview(self._buf_box), 0, self._buf_box.size)
        out[1].read(memoryview(self._buf_cls), 0, self._buf_cls.size)

        self._device.reset(1)      # ★ 必须

        return (self._buf_box.view(np.float32).copy(),
                self._buf_cls.view(np.float32).copy())

    def close(self):
        if self._session is not None:
            try:
                self._device.reset(1)
            except Exception:          # noqa: BLE001
                pass
            try:
                self._xrt.Device.Close(self._device)
            except Exception:          # noqa: BLE001
                pass
        self._session = None


class DryRunBackend:
    """假推理：返回随机张量，用于在任意机器上验证后处理/画框/写视频的代码路径。"""

    def __init__(self, seed=0):
        self.rng = np.random.default_rng(seed)

    def open(self):
        return self

    def infer(self, img_rgb_640):
        # 造一批"高置信度"的假框，让画面上能看出东西
        box = self.rng.normal(0, 2.0, (1, 4 * REG_MAX, NUM_ANCHORS)).astype(np.float32)
        cls = self.rng.normal(-6.0, 1.5, (1, 1, NUM_ANCHORS)).astype(np.float32)
        # 随机挑 3 个位置给高置信度
        for i in self.rng.choice(NUM_ANCHORS, size=3, replace=False):
            cls[0, 0, i] = 4.0            # sigmoid ≈ 0.982
        return box, cls

    def close(self):
        pass


# ================================================================ 主流程
def draw(frame, dets):
    """
    画检测框。会把坐标裁剪到画面内，并丢弃完全在画面外的框
    （模型在图像边缘可能给出越界坐标，直接 cv2.rectangle 会画出屏幕或报错）。
    """
    h, w = frame.shape[:2]
    kept = 0
    for d in dets:
        x1 = max(0, min(int(round(d["x1"])), w - 1))
        y1 = max(0, min(int(round(d["y1"])), h - 1))
        x2 = max(0, min(int(round(d["x2"])), w - 1))
        y2 = max(0, min(int(round(d["y2"])), h - 1))
        if x2 - x1 < 2 or y2 - y1 < 2:      # 裁剪后太小或无交集，丢掉
            continue
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(frame, "drone %.2f" % d["conf"],
                    (x1, max(y1 - 6, 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA)
        kept += 1
    return frame, kept


def run(src, out, backend, max_frames=0, show_hud=True):
    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        sys.exit("打不开输入源：%s" % src)

    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1280
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 720
    fps_in = cap.get(cv2.CAP_PROP_FPS) or 30.0

    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    writer = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*"mp4v"), fps_in, (w, h))

    n, t_pre, t_inf, t_post = 0, 0.0, 0.0, 0.0
    t_start = time.time()

    # ★ backend.open() 必须在 try 内：若 session.apply() 中途抛异常（如 DMA 超时），
    #   放在外面会导致 finally 不执行 → 设备句柄泄漏 → 下次运行 DMA 通道卡死（需重启板子）。
    try:
        backend.open()
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            n += 1

            t0 = time.perf_counter()
            img640, scale, left, top = letterbox(frame)
            t1 = time.perf_counter()

            box_raw, cls_raw = backend.infer(img640)
            t2 = time.perf_counter()

            dets = postprocess(box_raw, cls_raw, scale, left, top)
            t3 = time.perf_counter()

            t_pre += t1 - t0
            t_inf += t2 - t1
            t_post += t3 - t2

            frame, n_drawn = draw(frame, dets)
            if show_hud:
                cv2.putText(frame, "frame %d  det %d" % (n, n_drawn),
                            (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                            (0, 255, 255), 1, cv2.LINE_AA)
            writer.write(frame)

            if max_frames and n >= max_frames:
                break
    finally:
        try:
            backend.close()
        except Exception as exc:      # noqa: BLE001
            print("[warn] backend.close() 失败: %s" % exc)
        cap.release()
        writer.release()

    dt = time.time() - t_start
    print("=" * 58)
    print(" 输入   : %s  (%dx%d @ %.1f fps)" % (src, w, h, fps_in))
    print(" 输出   : %s" % out)
    print(" 帧数   : %d   总耗时 %.2f s   端到端 %.2f fps" % (n, dt, n / dt if dt else 0))
    print(" 逐帧均值（毫秒）:")
    print("   预处理 letterbox : %7.2f" % (t_pre / n * 1e3))
    print("   推理             : %7.2f" % (t_inf / n * 1e3))
    print("   后处理 decode+NMS: %7.2f" % (t_post / n * 1e3))
    print("   合计             : %7.2f" % ((t_pre + t_inf + t_post) / n * 1e3))
    print("=" * 58)
    return n / dt if dt else 0.0


def main():
    ap = argparse.ArgumentParser(description="YOLOv11n 截断头 + ZG330 NPU 视频推理")
    ap.add_argument("--src", required=True, help="视频文件路径，或摄像头设备号（如 0）")
    ap.add_argument("--out", default="out_npu.mp4", help="输出视频路径")
    ap.add_argument("--dry-run", action="store_true",
                    help="用随机张量代替 NPU 输出，验证后处理/画框/写视频")
    ap.add_argument("--json", default="deploy/yolo11n_drone_trunc_ZG.json")
    ap.add_argument("--raw", default="deploy/yolo11n_drone_trunc_ZG.raw")
    ap.add_argument("--max-frames", type=int, default=0, help="0 = 全部")
    a = ap.parse_args()

    if a.dry_run:
        print("[dry-run] 使用随机张量代替 NPU 输出，只验证后处理链路")
        backend = DryRunBackend()
    else:
        backend = IcraftBackend(a.json, a.raw)

    run(a.src, a.out, backend, max_frames=a.max_frames)


if __name__ == "__main__":
    main()
