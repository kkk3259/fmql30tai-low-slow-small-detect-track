# -*- coding: utf-8 -*-
"""stream_cascade.py —— 三域级联实时链路

链路（目标形态）：
  摄像头 → ffmpeg 解码 → 640×360 灰度 → 写 udmabuf
        → 【PL】双路形态学(Top-Hat + Black-Hat) + CFAR + CCL → 候选
        → 【PL】按候选裁 64×64 → 拼 8×8 = 512×512 灰度网格
        → 【NPU】一次 forward 判 64 个（真/假）
        → 【PS】阈值筛 + 卡尔曼跟踪 + 按 area 反算框 + 画框
        → VPU 编码 → MJPEG 推流

三种后端（--backend）：

  pl    读 PL 输出的 512×512 网格（需要 P 的新位流）
        期望寄存器（基址 0x43C00000，挂 GP0）：
          0x00 CTRL        bit0=start
          0x04 FRAME_ADDR  帧在 udmabuf 的地址
          0x08 RESULT_ADDR 候选表地址
          0x0C STATUS      bit31=done bit30=error [23:16]=帧计数 [15:8]=n_cand
          0x10 FRAME_ID
          0x14 VERSION     0x00010000
          0x18 ROI_ADDR    网格地址（512×512 灰度）
          0x1C ROI_STATUS  bit31=done

  sim   在 PS 里用 OpenCV 做同样的双路检测 + 裁图拼网格（不依赖 PL）
        —— 用来验证整套逻辑，也是 PL 没通时的演示方案

  yolo  现有方案：PS 裁 448 + YOLO 640 全图（保底，见 ps/stream_npu.py）

关键实测数据（2026-10-27，见 tools/ 三个 bench 脚本）：
  · 双路形态学把召回从 69% 提到 94%（小目标档 28% → 92%）
  · 双路必须「两路各自 CFAR+CCL 再合并」，不能先合并增强图（那样只有 81%）
  · 64×64 ROI 对 15-35px 完整率 100%，35-70px 96%
  · 三帧确认压不掉静止纹理虚警（63.01 → 62.59），NPU 判真假才是主力

用法：
  # PC 上验证逻辑（不需要板子、不需要 ffmpeg）
  python ps/stream_cascade.py --backend sim --src test --port 8080

  # 板上用 PL 输出（需要新位流）
  python3 ps/stream_cascade.py --backend pl --src /dev/video1 --port 8080

  # 板上摄像头 + PS 模拟 PL
  python3 ps/stream_cascade.py --backend sim --src 1 --port 8080
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import cv2

# ============================================================ 常量

W, H = 640, 360            # 送进 PL 的灰度帧尺寸
ROI = 64                   # 每个候选的裁剪边长
GRID = 8                   # 8×8 = 64 个候选
CANVAS = ROI * GRID        # 512
MAX_CAND = GRID * GRID

REG_BASE_DEFAULT = 0x43C00000     # GP0（官方 FSBL 已开）
FRAME_BASE = 0x30100000
RESULT_BASE = 0x31000000
ROI_BASE = 0x32000000

# 寄存器偏移（与 docs/14 对齐，以 P 的 RTL 为准）
R_CTRL, R_FRAME_ADDR, R_RESULT_ADDR, R_STATUS = 0x00, 0x04, 0x08, 0x0C
R_FRAME_ID, R_VERSION, R_ROI_ADDR, R_ROI_STATUS = 0x10, 0x14, 0x18, 0x1C

ST_DONE, ST_ERROR = 1 << 31, 1 << 30

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ============================================================ ① 取流

class FakeGrabber(threading.Thread):
    """合成帧源：PC 上没 ffmpeg 时用来验证逻辑。

    背景用 deploy/eval_roi_448 的真实 1080P 图（有云/地物 → 自然纹理），
    叠加一个亮点（Top-Hat 能看到的）和一个暗点（Black-Hat 能看到的），
    两者都缓慢移动。
    """

    def __init__(self, fps=30.0):
        super().__init__(daemon=True)
        self.fps = fps
        self._lock = threading.Lock()
        self._frame = None
        self._stop = threading.Event()
        self._t = 0

    def _load_bg(self):
        base = os.path.join(REPO, "deploy", "eval_roi_448")
        man = os.path.join(base, "manifest.csv")
        if os.path.exists(man):
            import csv as _csv
            with open(man, encoding="utf-8") as f:
                for r in _csv.DictReader(f):
                    if r["尺寸档"] != "15-35px":
                        continue
                    fp = os.path.join(base, "images", r["文件"])
                    if os.path.exists(fp):
                        im = cv2.imdecode(np.fromfile(fp, dtype=np.uint8),
                                          cv2.IMREAD_COLOR)
                        if im is not None:
                            return cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
        return np.tile(np.linspace(120, 180, 1280, dtype=np.uint8), (720, 1))

    def run(self):
        bg = self._load_bg()
        H0, W0 = bg.shape[:2]
        while not self._stop.is_set():
            fr = bg.copy()
            cx = int(W0 * 0.30 + 60 * np.sin(self._t * 0.05))
            cy = int(H0 * 0.60 + 35 * np.cos(self._t * 0.04))
            cv2.circle(fr, (cx, cy), 3, 240, -1)              # 亮点
            cv2.circle(fr, (cx + 180, cy - 120), 4, 30, -1)   # 暗点
            with self._lock:
                self._frame = fr
            self._t += 1
            time.sleep(1.0 / self.fps)

    def latest(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def stop(self):
        self._stop.set()


class Grabber(threading.Thread):
    """ffmpeg 子进程解码 + 单槽交接（永远拿最新帧）。

    为什么不用 cv2.VideoCapture：OpenCV 解 720P MJPG 要 60.7 ms（16.5 fps），
    ffmpeg 能到 30 fps。
    """

    def __init__(self, src, size=(1280, 720), gray=True):
        super().__init__(daemon=True)
        self.src = src
        self.size = size
        self.gray = gray
        self._lock = threading.Lock()
        self._frame = None
        self._stop = threading.Event()
        self._proc = None
        self.fps = 0.0

    def _cmd(self):
        w, h = self.size
        pix = "gray" if self.gray else "bgr24"
        if self.src.isdigit():
            return ["ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-f", "v4l2", "-input_format", "mjpeg",
                    "-video_size", "%dx%d" % (w, h), "-framerate", "30",
                    "-i", "/dev/video" + self.src,
                    "-f", "rawvideo", "-pix_fmt", pix, "-"]
        # 视频文件：加 -stream_loop -1 让它无限循环（否则 5~21 秒后流就断了）。
        # 注意 -stream_loop 必须放在 -i 之前，顺序错了 ffmpeg 会报错。
        return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-re",
                "-stream_loop", "-1",
                "-i", self.src, "-vf", "scale=%d:%d" % (w, h),
                "-f", "rawvideo", "-pix_fmt", pix, "-"]

    def run(self):
        w, h = self.size
        nbytes = w * h * (1 if self.gray else 3)
        self._proc = subprocess.Popen(
            self._cmd(), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            bufsize=nbytes * 2)
        t0, n = time.time(), 0
        while not self._stop.is_set():
            buf = self._proc.stdout.read(nbytes)
            if len(buf) < nbytes:
                break
            arr = np.frombuffer(buf, np.uint8)
            fr = arr.reshape(h, w) if self.gray else arr.reshape(h, w, 3)
            with self._lock:
                self._frame = fr.copy()
            n += 1
            if n % 30 == 0:
                self.fps = 30.0 / max(time.time() - t0, 1e-6)
                t0, n = time.time(), 0

    def latest(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def stop(self):
        self._stop.set()
        if self._proc and self._proc.poll() is None:
            self._proc.kill()


# ============================================================ ② 双路检测（sim 后端用）

class DualDetector(object):
    """Top-Hat + Black-Hat 双路，各自 CFAR+CCL 再合并去重。

    这是 PL 侧 RTL 的算法等价物 —— 在 PS 上验证逻辑，
    也是 PL 没通时的演示方案。

    实测（tools/bench_cfar_recall.py）：
      Top-Hat only  topk=64 : 69.0%
      Black-Hat     topk=64 : 87.0%
      双路各 topk=64 再合并 : 94.0%  ← 本实现
    """

    def __init__(self, se=5, win=31, k=4.0, floor=3.0,
                 topk=64, min_area=2, max_area=200, merge_r=8):
        self.kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (se, se))
        self.win, self.k, self.floor = win, k, floor
        self.topk, self.min_area, self.max_area = topk, min_area, max_area
        self.merge_r = merge_r

    def _cfar(self, img):
        f = img.astype(np.float32)
        mu = cv2.boxFilter(f, -1, (self.win, self.win), normalize=True,
                           borderType=cv2.BORDER_REFLECT)
        mu2 = cv2.boxFilter(f * f, -1, (self.win, self.win), normalize=True,
                            borderType=cv2.BORDER_REFLECT)
        sd = np.sqrt(np.maximum(mu2 - mu * mu, 0))
        return ((f > mu + self.k * sd + self.floor)).astype(np.uint8) * 255

    def _cands(self, binary, enh):
        n, lab, stats, cents = cv2.connectedComponentsWithStats(binary,
                                                               connectivity=8)
        out = []
        for i in range(1, n):
            a = int(stats[i, cv2.CC_STAT_AREA])
            if a < self.min_area or a > self.max_area:
                continue
            m = (lab == i)
            peak = float(enh[m].max()) if m.any() else 0.0
            out.append({"x": float(cents[i][0]), "y": float(cents[i][1]),
                        "area": a, "peak": peak})
        out.sort(key=lambda c: -c["peak"])
        return out[:self.topk]

    def __call__(self, gray):
        top = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, self.kernel)
        blk = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, self.kernel)
        cs = self._cands(self._cfar(top), top) + self._cands(self._cfar(blk), blk)
        if not cs:
            return []
        cs.sort(key=lambda c: -c["peak"])
        kept = []
        for c in cs:
            if all((c["x"] - o["x"]) ** 2 + (c["y"] - o["y"]) ** 2
                   > self.merge_r ** 2 for o in kept):
                kept.append(c)
        return kept[:MAX_CAND]


# ============================================================ ③ 拼网格

def build_canvas(gray, cands):
    """按候选质心裁 ROI×ROI，拼成 GRID×GRID 的 CANVAS 灰度网格。

    越界补 0。返回 (canvas, 实际填充的候选数)
    """
    canvas = np.zeros((CANVAS, CANVAS), np.uint8)
    half = ROI // 2
    nfill = 0
    for idx, c in enumerate(cands[:MAX_CAND]):
        r = idx // GRID
        cx, cy = int(c["x"]), int(c["y"])
        x0, y0 = cx - half, cy - half
        for dy in range(ROI):
            sy = y0 + dy
            if sy < 0 or sy >= H:
                continue
            sx0 = max(0, x0)
            sx1 = min(W, x0 + ROI)
            if sx1 <= sx0:
                continue
            dx0 = sx0 - x0
            canvas[r * ROI + dy, dx0:dx0 + (sx1 - sx0)] = gray[sy, sx0:sx1]
        nfill += 1
    return canvas, nfill


# ============================================================ ④ PL 后端（待 P 的位流）

class PlBackend(object):
    """通过 /dev/mem 访问 0x43C00000 的寄存器组。

    [WARN] 当前 P 的 RTL 还没做双路检测和 64×64 网格，
       所以 --backend pl 会先检查 VERSION，不通就报错退出。
    """

    def __init__(self, base=REG_BASE_DEFAULT):
        self.base = base
        self.mem = None
        self._fd = None

    def open(self):
        import mmap
        try:
            self._fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
        except (OSError, PermissionError) as e:
            raise RuntimeError("打不开 /dev/mem（需要 root）：%s" % e)
        self.mem = mmap.mmap(self._fd, 0x1000, mmap.MAP_SHARED,
                             mmap.PROT_READ | mmap.PROT_WRITE,
                             offset=self.base)
        try:
            ver = self.rd(R_VERSION)
        except Exception as e:
            self.close()
            raise RuntimeError("读 VERSION 失败（GP0 未接或位流未加载）：%s" % e)
        if ver != 0x00010000:
            self.close()
            raise RuntimeError(
                "VERSION=0x%08X（期望 0x00010000）—— PL 未就绪：\n"
                "  ① 位流没加载？\n"
                "  ② AXI 没接到 GP0？\n"
                "  ③ 基址不是 0x43C00000？\n"
                "先用 python3 ps/probe_addr.py 0x43C00000 确认" % ver)
        return ver

    def rd(self, off):
        return int.from_bytes(self.mem[off:off + 4], "little")

    def wr(self, off, val):
        self.mem[off:off + 4] = int(val).to_bytes(4, "little")

    def close(self):
        if self.mem:
            try:
                self.mem.close()
            except Exception:
                pass
            self.mem = None
        if self._fd:
            try:
                os.close(self._fd)
            except Exception:
                pass
            self._fd = None

    def run(self, frame_id):
        """触发一次处理，等 done，返回 (cands, canvas)

        TODO(等 P 的 RTL)：这里要填实
          - 从 RESULT_BASE 读候选表（1 + 64×7 = 449 B）
          - 从 ROI_BASE 读 512×512 灰度网格
        """
        self.wr(R_FRAME_ADDR, FRAME_BASE)
        self.wr(R_RESULT_ADDR, RESULT_BASE)
        self.wr(R_ROI_ADDR, ROI_BASE)
        self.wr(R_FRAME_ID, frame_id)
        self.wr(R_CTRL, 1)
        t0 = time.time()
        while time.time() - t0 < 0.020:              # 20 ms 超时
            st = self.rd(R_STATUS)
            if st & ST_ERROR:
                self.wr(R_CTRL, 0)
                raise RuntimeError("PL 报错：STATUS=0x%08X" % st)
            if st & ST_DONE:
                break
            time.sleep(0.0002)
        else:
            self.wr(R_CTRL, 0)
            raise RuntimeError("PL 超时（20 ms）—— 检查位流是否真的在跑")
        self.wr(R_CTRL, 0)
        return [], np.zeros((CANVAS, CANVAS), np.uint8)


# ============================================================ ⑤ 跟踪

class Track(object):
    _next = 1

    def __init__(self, x, y, confirm=3):
        self.id = Track._next
        Track._next += 1
        self.kf = cv2.KalmanFilter(4, 2)
        self.kf.transitionMatrix = np.array(
            [[1, 0, 1, 0], [0, 1, 0, 1], [0, 0, 1, 0], [0, 0, 0, 1]], np.float32)
        self.kf.measurementMatrix = np.array([[1, 0, 0, 0], [0, 1, 0, 0]],
                                             np.float32)
        self.kf.processNoiseCov = np.eye(4, dtype=np.float32) * 1e-2
        self.kf.measurementNoiseCov = np.eye(2, dtype=np.float32) * 1e-1
        self.kf.errorCovPost = np.eye(4, dtype=np.float32)
        self.kf.statePost = np.array([[x], [y], [0], [0]], np.float32)
        self.hits = 1
        self.miss = 0
        self.confirm = confirm
        self.confirmed = (confirm <= 1)
        self.trail = [(x, y)]

    def predict(self):
        p = self.kf.predict()
        return float(p[0, 0]), float(p[1, 0])

    def update(self, x, y):
        self.kf.correct(np.array([[np.float32(x)], [np.float32(y)]]))
        self.hits += 1
        self.miss = 0
        self.trail.append((x, y))
        if len(self.trail) > 40:
            self.trail.pop(0)
        if self.hits >= self.confirm:
            self.confirmed = True


class Tracker(object):
    """卡尔曼 + 贪心匹配 + N 帧确认

    [WARN] 实测结论（tools/bench_track_falsealarm.py）：
       三帧确认对【静止纹理虚警】无效（63.01 → 62.59）。
       跟踪只负责航迹关联，去虚警靠 NPU 判别环节。
    """

    def __init__(self, gate=12.0, confirm=3, max_miss=15, max_tracks=64):
        self.tracks = []
        self.gate, self.confirm, self.max_miss = gate, confirm, max_miss
        # 轨迹池总上限。匹配是 O(n×m) 双重循环，若不设上限，
        # 长时间跑会累积到上百条（实测视频输入 trk 从 106 涨到 158，
        # 帧率被拖到 3.5 fps）。按「命中多、丢失少」保留最好的 max_tracks 条。
        self.max_tracks = max_tracks

    def step(self, dets):
        preds = [t.predict() for t in self.tracks]
        cand = []
        for i, p in enumerate(preds):
            for j, d in enumerate(dets):
                dist = float(np.hypot(p[0] - d[0], p[1] - d[1]))
                if dist <= self.gate:
                    cand.append((dist, i, j))
        cand.sort()
        ui, uj, used = set(), set(), set()
        for dist, i, j in cand:
            if i in ui or j in uj:
                continue
            self.tracks[i].update(dets[j][0], dets[j][1])
            ui.add(i)
            uj.add(j)
            used.add(j)
        for j in range(len(dets)):
            if j not in used:
                self.tracks.append(Track(dets[j][0], dets[j][1], self.confirm))
        for t in self.tracks:
            t.miss += 1
        self.tracks = [t for t in self.tracks if t.miss <= self.max_miss]
        # 总上限：按「命中多、丢失少」排序后截断，防止长跑时池子无限膨胀
        if len(self.tracks) > self.max_tracks:
            self.tracks.sort(key=lambda t: (t.hits, -t.miss), reverse=True)
            del self.tracks[self.max_tracks:]
        return [t for t in self.tracks if t.confirmed]


# ============================================================ ⑥ 画框 + 推流

def draw(bgr, cands, confirmed, backend, fps):
    """cands: [(x, y, area)]；confirmed: Track 列表"""
    for t in confirmed:
        x, y = int(t.trail[-1][0]), int(t.trail[-1][1])
        cv2.circle(bgr, (x, y), 10, (0, 255, 0), 1)
        cv2.putText(bgr, "T%d" % t.id, (x + 12, y - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
        for k in range(1, len(t.trail)):
            cv2.line(bgr, tuple(map(int, t.trail[k - 1])),
                     tuple(map(int, t.trail[k])), (0, 180, 0), 1)
    for (x, y, a) in cands:
        d = max(2, int(2 * (max(a, 1) / 3.14159) ** 0.5))
        cv2.rectangle(bgr, (int(x - d), int(y - d)), (int(x + d), int(y + d)),
                      (60, 60, 200), 1)
    hud = "MODE=%s  fps=%.1f  cand=%d  trk=%d" % (backend, fps,
                                                  len(cands), len(confirmed))
    cv2.putText(bgr, hud, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
    return bgr


class MjpegServer(object):
    def __init__(self, port, quality=70):
        self.port = port
        self.quality = quality
        self._jpg = None
        self._lock = threading.Lock()

    def push(self, bgr):
        ok, buf = cv2.imencode(".jpg", bgr,
                               [int(cv2.IMWRITE_JPEG_QUALITY), self.quality])
        if ok:
            with self._lock:
                self._jpg = buf.tobytes()

    def start(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path in ("/", "/index.html"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    self.wfile.write(
                        b"<html><body style='margin:0;background:#111'>"
                        b"<img src='/stream' style='width:100%'></body></html>")
                    return
                if self.path != "/stream":
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type",
                                 "multipart/x-mixed-replace; boundary=frame")
                self.end_headers()
                while True:
                    with outer._lock:
                        jpg = outer._jpg
                    if jpg:
                        try:
                            self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n")
                            self.wfile.write(
                                ("Content-Length: %d\r\n\r\n" % len(jpg)).encode())
                            self.wfile.write(jpg)
                            self.wfile.write(b"\r\n")
                        except (BrokenPipeError, ConnectionResetError):
                            break
                    time.sleep(0.03)

            def log_message(self, *args):
                pass

        srv = ThreadingHTTPServer(("0.0.0.0", self.port), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv


# ============================================================ ⑦ 主循环

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="sim", choices=["pl", "sim", "yolo"])
    ap.add_argument("--src", default="test",
                    help="'test'=合成帧 | '0'/'1'=摄像头编号 | 视频文件路径")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--disp-w", type=int, default=640)
    ap.add_argument("--jpeg-q", type=int, default=70)
    ap.add_argument("--topk", type=int, default=64)
    ap.add_argument("--confirm", type=int, default=3)
    ap.add_argument("--frames", type=int, default=0, help="跑多少帧后停（0=无限）")
    a = ap.parse_args()

    print("  backend = %s   src = %s   port = %d" % (a.backend, a.src, a.port))
    if a.backend == "yolo":
        print("  yolo 后端请用 ps/stream_npu.py")
        return 1

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
        return 1
    print("  首帧到手")

    det = None
    pl = None
    if a.backend == "sim":
        det = DualDetector(topk=a.topk)
        print("  sim 后端：PS 内做双路形态学（PL 的算法等价物）")
    else:
        pl = PlBackend()
        try:
            ver = pl.open()
            print("  PL VERSION = 0x%08X" % ver)
        except RuntimeError as e:
            print("  %s" % e)
            grab.stop()
            return 2

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
            if a.backend == "sim":
                cs = det(gray)
                canvas, nfill = build_canvas(gray, cs)
                pts = [(c["x"], c["y"], c["area"]) for c in cs]
            else:
                pts, canvas = pl.run(done)
                nfill = 0
            t_det = (time.time() - t0) * 1000

            # --- NPU 判别（待 A 的二分类模型）---
            # 有模型后：把 canvas（512×512 灰度）送 NPU，按概率过滤 pts。
            # 当前先全通过，让整条链路能跑起来。
            confirmed = tracker.step(pts)

            bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
            bgr = draw(bgr, pts, confirmed, a.backend, fps)
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
                print("  [%d] det=%.1f ms  cand=%d  fill=%d  trk=%d  fps=%.1f"
                      % (done, t_det, len(pts), nfill, len(confirmed), fps))
    except KeyboardInterrupt:
        print("\n  停止")
    finally:
        grab.stop()
        if pl:
            pl.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
