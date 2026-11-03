# -*- coding: utf-8 -*-
"""
摄像头 → NPU → 网口看画面（stream_npu.py）

这是 S 负责路线的第一段闭环：
    USB 摄像头（MJPG 720P@30）→ ffmpeg 解码 → letterbox 640×640
    → ZG330 NPU 推理（复用 tensor）→ DFL 解码 + NMS → 坐标反算
    → 画框 + 仪表盘 → MJPEG over HTTP

板上用法（需要 root：要开 /dev/mem 给 NPU 用）：
    sudo python3 stream_npu.py                 # 默认 /dev/video1、端口 8080
    sudo python3 stream_npu.py --cam /dev/video1 --port 8080
    sudo python3 stream_npu.py --src /root/bird.mp4   # 用视频文件代替摄像头（调试）
然后笔记本浏览器打开 http://<板子IP>:8080

 三个关键优化（都经板端实测）：
  ① 用 ffmpeg 管道解码，不用 cv2.VideoCapture
     · OpenCV 解 720P MJPG 要 60.7 ms（仅 16.5 fps）
     · ffmpeg 解同一个流能到 30 fps
  ② 复用 Tensor 对象，不每帧 numpy2Tensor
     · 重建 4.26 ms → 复用后 write 只要 0.68 ms（省 3.58 ms，实测）
  ③ letterbox 开 cv2.setNumThreads(4)
     · 单线程 12.84 ms → 4 线程 9.61 ms

 采集与推理用「双线程 + 单槽交接」做流水线：
   采集线程只管把最新帧放进 slot（永远覆盖，不排队），
   推理线程取最新帧处理 —— 这样解码和推理能重叠，端到端接近 max(解码, 推理) 而非两者之和。

 依赖：icraft 3.39.0 + /root/pywork/modelzoo_utils/pyrtutils
"""

import argparse
import os
import subprocess
import sys
import threading
import time

PYRTUTILS_DIR = "/root/pywork"
if PYRTUTILS_DIR not in sys.path:
    sys.path.insert(0, PYRTUTILS_DIR)

from modelzoo_utils.pyrtutils import Netinfo, initSession, loadNetwork, numpy2Tensor  # noqa: E402
from icraft import xrt  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402

# ================================================================ 常量
NET = 640
REG_MAX = 16
STRIDES = (8, 16, 32)
N_ANCHORS = sum((NET // s) ** 2 for s in STRIDES)
BOX_BYTES = 1 * 64 * N_ANCHORS * 4
CLS_BYTES = 1 * 1 * N_ANCHORS * 4
CONF_TH = 0.25
IOU_TH = 0.45
PAD_VALUE = 114
DEVICE_URL = "axi://zg330aiu?npu=0x40000000&dma=0x80000000"

CAM_W, CAM_H, CAM_FPS = 1280, 720, 30

PAGE = (b"<!doctype html><html><head><meta charset=utf-8><title>NPU Stream</title>"
        b"<style>body{margin:0;background:#111;color:#ddd;font:14px monospace}"
        b"img{width:100%;max-width:1280px;display:block}"
        b"#s{padding:6px 10px;background:#1b1b1b}</style></head>"
        b"<body><div id=s>connecting...</div>"
        b"<img src=/stream.mjpg>"
        b"<script>setInterval(async()=>{try{const r=await fetch('/stat');"
        b"document.getElementById('s').textContent=await r.text()}catch(e){}},1000)</script>"
        b"</body></html>")

# ================================================================ MJPEG 输出槽
_lock = threading.Lock()
_slot = {"jpeg": None, "stamp": 0.0, "stat": {"fps": 0.0, "ms": 0.0, "n": 0, "mode": "-"}}


def publish(jpeg, stat):
    with _lock:
        _slot["jpeg"] = jpeg
        _slot["stamp"] = time.time()
        _slot["stat"] = stat


def latest():
    with _lock:
        return _slot["jpeg"], _slot["stamp"], dict(_slot["stat"])


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(PAGE)))
            self.end_headers()
            self.wfile.write(PAGE)
        elif self.path == "/stat":
            _, _, st = latest()
            body = ("MODE=%s  det=%d  单帧 %.1f ms  推理 %.1f fps"
                    % (st["mode"], st["n"], st["ms"], st["fps"])).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/stream.mjpg":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            last = 0.0
            try:
                while True:
                    buf, stamp, _ = latest()
                    if buf is None or stamp == last:
                        time.sleep(0.005)
                        continue
                    last = stamp
                    self.wfile.write(b"--frame\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(b"Content-Length: " + str(len(buf)).encode() + b"\r\n\r\n")
                    self.wfile.write(buf)
                    self.wfile.write(b"\r\n")
            except (BrokenPipeError, ConnectionResetError):
                pass
        else:
            self.send_error(404)


# ================================================================ 采集线程（ffmpeg 管道）
class Grabber(threading.Thread):
    """ffmpeg 从摄像头/文件解出 bgr24 原始帧，放进单槽（永远只要最新帧）"""

    def __init__(self, src, w, h, fps, is_cam=True):
        super().__init__(daemon=True)
        self.src, self.w, self.h, self.fps = src, w, h, fps
        self.frame_bytes = w * h * 3
        self.slot = None
        self.seq = 0
        self.err = None
        self._stop = False
        self.proc = None

    def _cmd(self):
        if self.src.startswith("/dev/video"):
            return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
                    "-f", "v4l2", "-input_format", "mjpeg",
                    "-video_size", "%dx%d" % (self.w, self.h), "-framerate", str(self.fps),
                    "-i", self.src,
                    "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
        return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
                "-re", "-i", self.src,
                "-vf", "scale=%d:%d" % (self.w, self.h),
                "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]

    def run(self):
        try:
            #  必须关掉 stdin：否则 ffmpeg 会继承父进程的输入，
            #   把 stdin 上的内容当成交互命令解析，然后报 Parse error 退出。
            self.proc = subprocess.Popen(self._cmd(),
                                         stdin=subprocess.DEVNULL,
                                         stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL,
                                         bufsize=self.frame_bytes * 2)
            while not self._stop:
                buf = self.proc.stdout.read(self.frame_bytes)
                if not buf or len(buf) < self.frame_bytes:
                    self.err = "ffmpeg 流结束"
                    break
                self.slot = np.frombuffer(buf, np.uint8).reshape(self.h, self.w, 3)
                self.seq += 1
        except Exception as exc:                       # noqa: BLE001
            self.err = str(exc)
        finally:
            if self.proc and self.proc.poll() is None:
                self.proc.kill()

    def get(self, last_seq):
        """返回 (frame, seq)；没有新帧则 frame=None"""
        if self.slot is None or self.seq == last_seq:
            return None, last_seq
        return self.slot, self.seq

    def stop(self):
        self._stop = True


# ================================================================ 预处理 / 后处理
def letterbox(bgr, dst=NET, pad=PAD_VALUE):
    h, w = bgr.shape[:2]
    sc = min(dst / w, dst / h)
    nw, nh = int(round(w * sc)), int(round(h * sc))
    resized = cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((dst, dst, 3), pad, np.uint8)
    left, top = (dst - nw) // 2, (dst - nh) // 2
    canvas[top:top + nh, left:left + nw] = resized
    return canvas, sc, left, top


def dfl_decode(box_raw, cls_raw, sel, reg_max=REG_MAX, strides=STRIDES, net=NET):
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
    ap = argparse.ArgumentParser(description="摄像头 → NPU → MJPEG 推流")
    ap.add_argument("--src", default="/dev/video1", help="摄像头节点或视频文件")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--json", default="/root/a_model/yolo11n_drone_trunc_ZG.json")
    ap.add_argument("--raw", default="/root/a_model/yolo11n_drone_trunc_ZG.raw")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--disp-w", type=int, default=640, help="推流显示宽度（越小编码越快）")
    ap.add_argument("--jpeg-q", type=int, default=70, help="JPEG 质量")
    a = ap.parse_args()

    cv2.setNumThreads(a.threads)

    is_cam = a.src.startswith("/dev/video")
    if is_cam:
        w, h, fps = CAM_W, CAM_H, CAM_FPS
    else:
        cap = cv2.VideoCapture(a.src)
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or CAM_W
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or CAM_H
        fps = cap.get(cv2.CAP_PROP_FPS) or CAM_FPS
        cap.release()

    # ---- NPU 初始化 ----
    network = loadNetwork(a.json, a.raw)
    netinfo = Netinfo(network)
    device = xrt.Device.Open(DEVICE_URL)
    session = initSession("zg330", network, device,
                          ocm_option=4, mmuMode=bool(netinfo.mmu),
                          open_speedmode=False, open_compressFtmp=False)
    session.enableTimeProfile(True)
    session.apply()
    print("[init] ops=%d  input=%s  mmu=%s"
          % (len(network.ops), netinfo.i_shape, netinfo.mmu))

    buf_box = np.zeros(BOX_BYTES, np.uint8)
    buf_cls = np.zeros(CLS_BYTES, np.uint8)

    #  优化②：tensor 建一次，之后只 write
    ten_in = numpy2Tensor(np.zeros((1, NET, NET, 3), np.uint8), network)

    # ---- 采集线程 ----
    grabber = Grabber(a.src, w, h, fps, is_cam)
    grabber.start()
    time.sleep(0.5)
    if grabber.err:
        sys.exit("采集启动失败：%s" % grabber.err)
    print("[cam] %s  %dx%d @%d  (%s)" % (a.src, w, h, fps, "摄像头" if is_cam else "文件"))

    srv = ThreadingHTTPServer(("0.0.0.0", a.port), Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print("[http] http://<板子IP>:%d" % a.port)
    print("[run] Ctrl+C 退出")

    seq = 0
    n_ok = 0
    t_start = time.time()
    hist = []
    t_pre = t_inf = t_post = t_enc = 0.0

    try:
        while True:
            frame, seq = grabber.get(seq)
            if frame is None:
                if grabber.err:
                    print("[warn] " + grabber.err)
                    break
                time.sleep(0.002)
                continue

            t0 = time.perf_counter()
            lb, sc, l, t = letterbox(frame)
            rgb = cv2.cvtColor(lb, cv2.COLOR_BGR2RGB)
            rgb = np.ascontiguousarray(rgb)
            t1 = time.perf_counter()

            #  优化②：复用 tensor
            ten_in.write(0, memoryview(rgb), rgb.nbytes)
            out = session.forward([ten_in])
            out[0].read(memoryview(buf_box), 0, BOX_BYTES)
            out[1].read(memoryview(buf_cls), 0, CLS_BYTES)
            device.reset(1)                  #  必须
            t2 = time.perf_counter()

            cls = buf_cls.view(np.float32)
            conf = 1.0 / (1.0 + np.exp(-cls))
            sel = np.flatnonzero(conf >= CONF_TH)
            dets = []
            if sel.size:
                boxes, scores = dfl_decode(buf_box.view(np.float32), cls, sel)
                keep = nms(boxes, scores)
                for b in boxes[keep]:
                    cx, cy = (b[0] - l) / sc, (b[1] - t) / sc
                    bw, bh = b[2] / sc, b[3] / sc
                    x1 = int(max(0, cx - bw / 2)); y1 = int(max(0, cy - bh / 2))
                    x2 = int(min(w - 1, cx + bw / 2)); y2 = int(min(h - 1, cy + bh / 2))
                    if x2 - x1 < 2 or y2 - y1 < 2:
                        continue
                    dets.append((x1, y1, x2, y2))
            t3 = time.perf_counter()

            disp = frame
            for (x1, y1, x2, y2) in dets:
                cv2.rectangle(disp, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(disp, "drone", (x1, max(y1 - 5, 12)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA)

            dt_ms = (t3 - t0) * 1e3
            hist.append(dt_ms)
            if len(hist) > 30:
                hist.pop(0)
            avg = sum(hist) / len(hist)
            t_pre += t1 - t0; t_inf += t2 - t1; t_post += t3 - t2
            n_ok += 1

            cv2.putText(disp, "NPU %s  det=%d  %.1f ms  %.1f fps"
                        % ("CAM" if is_cam else "FILE", len(dets), avg, 1000.0 / avg),
                        (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2, cv2.LINE_AA)

            #  推流前缩到 disp_w，大幅降低 JPEG 编码耗时（A53 编 720P 太慢）
            t4 = time.perf_counter()
            if a.disp_w and a.disp_w != w:
                dw = a.disp_w
                dh = int(h * dw / w)
                small = cv2.resize(disp, (dw, dh), interpolation=cv2.INTER_NEAREST)
            else:
                small = disp
            okj, jb = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, a.jpeg_q])
            t5 = time.perf_counter()
            t_enc += t5 - t4
            if okj:
                publish(jb.tobytes(), {"fps": 1000.0 / avg, "ms": avg,
                                       "n": len(dets), "mode": "NPU+CAM" if is_cam else "NPU+FILE"})

            if n_ok % 30 == 0:
                n = n_ok
                print("  f%-5d det=%d  均值 %.1f ms (pre %.1f / inf %.1f / post %.1f / enc %.1f)  %.1f fps"
                      % (n, len(dets), avg, t_pre / n * 1e3, t_inf / n * 1e3,
                         t_post / n * 1e3, t_enc / n * 1e3, 1000.0 / avg))
    except KeyboardInterrupt:
        print("\n[exit] 中断")
    finally:
        grabber.stop()
        n = max(n_ok, 1)
        wall = time.time() - t_start
        print("\n=== 汇总 ===")
        print("  帧数 %d  墙钟 %.1f s  平均 %.2f fps" % (n_ok, wall, n_ok / wall))
        print("  逐环节均值：pre %.2f / inf %.2f / post %.2f / enc %.2f / 合计 %.2f ms"
              % (t_pre / n * 1e3, t_inf / n * 1e3, t_post / n * 1e3, t_enc / n * 1e3,
                 (t_pre + t_inf + t_post + t_enc) / n * 1e3))
        try:
            device.reset(1)
        except Exception:
            pass
        xrt.Device.Close(device)
        print("DONE")


if __name__ == "__main__":
    main()
