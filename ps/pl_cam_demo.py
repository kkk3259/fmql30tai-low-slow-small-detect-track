# -*- coding: utf-8 -*-
"""
相机 → PL 检测 → 画框 → 网口看画面（pl_cam_demo.py）

这是"第一段闭环"的演示脚本：相机取一帧 640×360 灰度 → 送进 PL 的 IP2 检测器
→ 读回候选表 → 在原图上画圈/写数字 → 用 MJPEG 推给浏览器看。

板上用法（需要 root：要开 /dev/mem 和 /dev/udmabuf0）：
    sudo python3 pl_cam_demo.py                    # 默认 USB 相机 0，端口 8080
    sudo python3 pl_cam_demo.py --no-pl            # 不接 PL，只看相机（排查用）
    sudo python3 pl_cam_demo.py --replay ./frames  # 不用相机，循环读目录里的图（离线演示）

然后笔记本浏览器打开：
    http://<板子IP>:8080

依赖：opencv-python（cv2）、numpy；PL 通路依赖同目录的 pl_link.py。

注意：
  * 第一次跑先用 pl_selftest.py 确认 VERSION=0x00010000；
  * 拿不到 /dev/udmabuf0 时会自动退化成 --no-pl 模式，页面会标注 "MODE=camera only"。
"""

import argparse
import glob
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np

W, H = 640, 360                       # PL 检测器的输入尺寸（IP1 2× 降采样后的分辨率）
FRAME_SIZE = W * H
FRAME_BASE = 0x30100000
RESULT_BASE = 0x31000000

# ---------------------------------------------------------------- 共享帧缓存
_latest = {"jpeg": None, "stamp": 0.0, "stat": {"ms": 0.0, "n": 0, "mode": "init", "fps": 0.0}}
_lock = threading.Lock()


def _set_jpeg(buf, stat):
    with _lock:
        _latest["jpeg"] = buf
        _latest["stamp"] = time.time()
        _latest["stat"] = stat


def _get_jpeg():
    with _lock:
        return _latest["jpeg"], _latest["stamp"], dict(_latest["stat"])


# ---------------------------------------------------------------- MJPEG 服务
PAGE = ("""<!doctype html><html><head><meta charset="utf-8"><title>IP2 低慢小检测</title>
<style>body{background:#111;color:#ddd;font-family:monospace;margin:0;text-align:center}
img{max-width:100%;height:auto}div{padding:6px;font-size:15px}</style></head>
<body><div id="s">waiting...</div><img src="/stream.mjpg">
<script>setInterval(()=>{fetch('/stat').then(r=>r.text()).then(t=>document.getElementById('s').textContent=t)},500)</script>
</body></html>""").encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):        # 别刷屏
        pass

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(PAGE)))
            self.end_headers()
            self.wfile.write(PAGE)
        elif self.path == "/stat":
            _, _, st = _get_jpeg()
            body = ("MODE=%s  n_cand=%d  单帧 %.1f ms  采集 %.1f fps"
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
                    buf, stamp, _ = _get_jpeg()
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


def start_server(port):
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# ---------------------------------------------------------------- 相机 / 回放
def open_camera(idx, width, height):
    cap = cv2.VideoCapture(idx)
    if not cap.isOpened():
        cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
    if not cap.isOpened():
        return None
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))   # 多数 UVC 上更省带宽
    return cap


def load_replay(directory):
    pats = ("*.jpg", "*.jpeg", "*.png", "*.bmp")
    files = []
    for p in pats:
        files += glob.glob(os.path.join(directory, p))
    return sorted(files)


# ---------------------------------------------------------------- 主循环
def draw_overlay(bgr, cands, stat, src_size):
    """把候选质点画到 2× 放大的显示图上。"""
    disp = cv2.resize(bgr, (src_size[0], src_size[1]), interpolation=cv2.INTER_NEAREST)
    sx = src_size[0] / float(W)
    sy = src_size[1] / float(H)
    for i, c in enumerate(cands):
        x, y = int(c["x"] * sx), int(c["y"] * sy)
        cv2.circle(disp, (x, y), 26, (0, 255, 0), 2)
        cv2.line(disp, (x - 34, y), (x - 12, y), (0, 255, 0), 1)
        cv2.line(disp, (x + 12, y), (x + 34, y), (0, 255, 0), 1)
        cv2.line(disp, (x, y - 34), (x, y - 12), (0, 255, 0), 1)
        cv2.line(disp, (x, y + 12), (x, y + 34), (0, 255, 0), 1)
        cv2.putText(disp, "#%d a=%d p=%d" % (i + 1, c["area"], c["peak"]),
                    (x + 12, y - 16), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 1, cv2.LINE_AA)
    cv2.putText(disp, "MODE=%s  n=%d  %.1f ms  %.1f fps"
                % (stat["mode"], stat["n"], stat["ms"], stat["fps"]),
                (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2, cv2.LINE_AA)
    return disp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--no-pl", action="store_true", help="不接 PL，只看相机")
    ap.add_argument("--replay", default=None, help="不用相机，循环读这个目录里的图")
    ap.add_argument("--timeout", type=float, default=0.05, help="等 PL 结果的超时（秒）")
    ap.add_argument("--scale", type=int, default=1280, help="推流显示宽度")
    args = ap.parse_args()

    # ---- PL 通路
    pl = None
    mode = "camera only"
    if not args.no_pl:
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from pl_link import PlLink, REG_BASE, REG_VERSION, REG_STATUS
            pl = PlLink(reg_base=REG_BASE)
            pl.open()
            pl.version()
            mode = "PL"
            print("[demo] PL 已连上，寄存器基址 0x%08X，VERSION=0x%08X"
                  % (REG_BASE, pl.version()))
        except Exception as e:
            print("[demo] ⚠ PL 通路不可用（%s）→ 退化为只看相机" % e)
            pl = None
            mode = "camera only"

    # ---- 图像源
    cap = None
    frames = []
    if args.replay:
        frames = load_replay(args.replay)
        if not frames:
            print("[demo] ✗ 目录里没有图片: %s" % args.replay)
            return 2
        print("[demo] 回放 %d 张图: %s" % (len(frames), args.replay))
        mode = mode + "+replay"
    else:
        cap = open_camera(args.camera, args.width, args.height)
        if cap is None:
            print("[demo] ✗ 打不开相机 %d（USB 插好了吗？ls /dev/video*）" % args.camera)
            return 2
        print("[demo] 相机 %d 打开: %dx%d" % (args.camera, args.width, args.height))

    srv = start_server(args.port)
    print("[demo] 服务已起：请在笔记本浏览器打开  http://<板子IP>:%d" % args.port)

    disp_size = (args.scale, int(args.scale * H / float(W)))
    k = 0
    t_fps, n_fps = time.time(), 0
    fps = 0.0
    try:
        while True:
            if args.replay:
                bgr = cv2.imread(frames[k % len(frames)])
                if bgr is None:
                    k += 1
                    continue
                time.sleep(1.0 / 30)
            else:
                ok, bgr = cap.read()
                if not ok:
                    print("[demo] ⚠ 读相机失败，重试")
                    time.sleep(0.05)
                    continue

            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, (W, H), interpolation=cv2.INTER_AREA)
            gray = np.ascontiguousarray(gray, dtype=np.uint8)

            cands, ms = [], 0.0
            if pl is not None:
                t0 = time.time()
                try:
                    pl.put_frame(k, gray.reshape(-1))
                    pl.trigger(frame_id=k, frame_addr=FRAME_BASE, result_addr=RESULT_BASE)
                    res = pl.wait_done(timeout_s=args.timeout)
                    cands = res if res else []
                    ms = (time.time() - t0) * 1000.0
                except Exception as e:
                    print("[demo] ⚠ PL 出帧失败: %s" % e)
                    pl = None
                    mode = "camera only (PL 掉线)"
                k += 1

            n_fps += 1
            if time.time() - t_fps >= 1.0:
                fps = n_fps / (time.time() - t_fps)
                t_fps, n_fps = time.time(), 0

            stat = {"ms": ms, "n": len(cands), "mode": mode, "fps": fps}
            disp = draw_overlay(bgr, cands, stat, disp_size)
            ok, jpg = cv2.imencode(".jpg", disp, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
            if ok:
                _set_jpeg(jpg.tobytes(), stat)
    except KeyboardInterrupt:
        print("\n[demo] 退出")
    finally:
        if cap is not None:
            cap.release()
        if pl is not None:
            pl.close()
        srv.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
