#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# cam_pipe.py —— 三级流水线版实时检测（采集 / PL 推理 / 编码 三线程解耦）
#
# 设计要点：
#   线程 A（采集）：cap.read() → 裁成 640x360 → 灰度；永远只保留"最新一帧"（丢旧帧）
#   线程 B（推理）：取最新灰度 → 写 udmabuf → 触发 PL → 轮询 → 读候选表 → 在原彩图上画框
#   线程 C（编码）：把画好框的彩图编码成 JPEG 给网页（编码慢，放在独立线程不挡推理）
#   主线程：HTTP 服务（/ 网页、/live 当前帧、/info 状态）
#
# 实测背景（板子 Cortex-A53）：cap.read() 27~41 ms、JPEG 编码 640x360 约 26 ms、PL 一帧 5~12 ms，
# 串行做就是 15 fps；拆成流水线后受最慢一级限制。
import argparse
import json
import os
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import mmap as MM

import cv2
import numpy as np

UDMA = "/dev/udmabuf0"
SYS = "/sys/class/u-dma-buf/udmabuf0"
DEVMEM = "/dev/mem"
REG = 0x43C00000
W, H = 640, 360
NPIX = W * H

R_CTRL = 0x00
R_STATUS = 0x0C           # {frm_cnt[15:8], n_cand[7:0], 5'd0, err, done, busy}
R_VER = 0x14
CAND_BASE = 0x18          # 9 个 32 位字（36 字节候选表）
R_STMIRROR = 0x3C

g_lock = threading.Lock()
g_jpeg = None
g_info = {}
g_stop = False

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>IP2 实时检测</title>
<style>
body{margin:0;background:#0d0d0d;color:#7CFC00;font:14px/1.6 Consolas,monospace}
#hud{padding:8px 12px;border-bottom:1px solid #24451f;white-space:pre-wrap}
img{width:100%;max-width:1280px;display:block;margin:0 auto}
</style></head><body>
<div id="hud">实时视频流（MJPEG）…</div>
<img src="/stream">
<script>
setInterval(function(){
  fetch('/info').then(function(r){return r.json()}).then(function(j){
    var n=(j.cands||[]).length;
    document.getElementById('hud').textContent =
      'PL ' + j.pl_fps + ' fps (' + j.PL_ms + ' ms) | 显示 ' + j.fps + ' fps | 采集 ' +
      j.cap_ms + ' ms | 编码 ' + j.enc_ms + ' ms | 候选 ' + n +
      (n ? '  ' + JSON.stringify(j.cands) : '');
  }).catch(function(){});
}, 500);
</script></body></html>"""


def sysfs(name, value=None):
    p = os.path.join(SYS, name)
    if value is None:
        with open(p) as f:
            return f.read().strip()
    with open(p, "w") as f:
        f.write(str(value))


class HW(object):
    def __init__(self):
        self.fd = os.open(UDMA, os.O_RDWR | os.O_SYNC)
        self.buf = MM.mmap(self.fd, int(sysfs("size"), 0), MM.MAP_SHARED,
                           prot=MM.PROT_READ | MM.PROT_WRITE)
        self.rfd = os.open(DEVMEM, os.O_RDWR | os.O_SYNC)
        self.reg = MM.mmap(self.rfd, 0x1000, MM.MAP_SHARED, offset=REG)
        # 只同步真正用到的 NPIX 字节：默认按 128 MiB 整块清 cache，每帧白吃 ~20 ms
        sysfs("sync_offset", 0)
        sysfs("sync_size", NPIX)
        self.pl_ms = 0.0

    def rd(self, o):
        return struct.unpack_from("<I", self.reg, o)[0]

    def wr(self, o, v):
        struct.pack_into("<I", self.reg, o, v & 0xFFFFFFFF)

    def run(self, gray):
        """喂一帧 → 触发 → 等完成 → 读候选表，返回 (status, cands)"""
        self.buf[0:NPIX] = gray.tobytes()
        sysfs("sync_for_device", 1)
        self.wr(R_CTRL, 1)
        t0 = time.time()
        while (time.time() - t0) < 2.0:
            st = self.rd(R_STATUS)
            if st & 0x06:
                break
        raw = b"".join(struct.pack("<I", self.rd(CAND_BASE + 4 * i)) for i in range(9))
        dt = (time.time() - t0) * 1000.0
        n = raw[0]
        cands = []
        for i in range(min(n, 5)):
            b = raw[1 + i * 7: 8 + i * 7]
            if len(b) < 7:
                break
            cands.append({"x": (b[0] << 8) | b[1], "y": (b[2] << 8) | b[3],
                          "area": b[5], "peak": b[6]})
        return st, cands, dt


class Pipeline(object):
    def __init__(self, hw, cam=0):
        self.hw = hw
        self.cam = cam
        self.slot = None          # (color, gray)
        self.slot_lock = threading.Lock()
        self.paint = None         # 画好框的彩图（等编码）
        self.paint_lock = threading.Lock()
        self.cap_ms = 0.0
        self.pl_ms = 0.0
        self.pl_n = 0
        self.pl_t0 = time.time()
        self.enc_ms = 0.0
        self.enc_n = 0

    # ---------- 线程 A：采集 ----------
    def thread_capture(self):
        cap = cv2.VideoCapture(self.cam, cv2.CAP_V4L2)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 4)
        except Exception:
            pass
        if not cap.isOpened():
            print("ERROR: 打不开摄像头")
            global g_stop
            g_stop = True
            return
        while not g_stop:
            t0 = time.time()
            ok, f = cap.read()
            if not ok:
                time.sleep(0.005)
                continue
            fh = f.shape[0]
            if fh >= H:
                top = (fh - H) // 2
                f = f[top:top + H, :, :]
            gray = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
            self.cap_ms = 0.8 * self.cap_ms + 0.2 * (time.time() - t0) * 1000
            with self.slot_lock:
                self.slot = (f, gray)
        cap.release()

    # ---------- 线程 B：PL 推理 + 画框 ----------
    def thread_infer(self):
        while not g_stop:
            with self.slot_lock:
                item = self.slot
                self.slot = None
            if item is None:
                time.sleep(0.002)
                continue
            color, gray = item
            st, cands, dt = self.hw.run(gray)
            self.pl_ms = 0.8 * self.pl_ms + 0.2 * dt
            self.pl_n += 1
            for c in cands:
                x, y = int(c["x"]), int(c["y"])
                cv2.rectangle(color, (x - 5, y - 5), (x + 5, y + 5), (0, 255, 0), 1)
                if x < W - 30 and y > 10:
                    cv2.putText(color, "%d" % c["peak"], (x + 6, y - 6),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 0), 1)
            cv2.putText(color, "PL %.1fms n=%d  cap %.1fms %d fps" %
                        (self.pl_ms, len(cands), self.cap_ms, self.pl_fps()),
                        (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
            with self.paint_lock:
                self.paint = color
            g_info.update({"cands": cands, "PL_ms": round(self.pl_ms, 2),
                           "pl_fps": round(self.pl_fps(), 1),
                           "cap_ms": round(self.cap_ms, 2), "n": len(cands)})

    def pl_fps(self):
        return self.pl_n / max(time.time() - self.pl_t0, 1e-6)

    # ---------- 线程 C：编码 ----------
    def thread_encode(self):
        last = None
        while not g_stop:
            with self.paint_lock:
                img = self.paint
            if img is None or img is last:
                time.sleep(0.002)
                continue
            last = img
            t0 = time.time()
            ok, enc = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
            self.enc_ms = 0.8 * self.enc_ms + 0.2 * (time.time() - t0) * 1000
            if ok:
                self.enc_n += 1
                with g_lock:
                    globals()["g_jpeg"] = enc.tobytes()
                g_info.update({"fps": round(self.enc_n / max(time.time() - self.pl_t0, 1e-6), 1),
                               "enc_ms": round(self.enc_ms, 2)})

    def start(self):
        for fn in (self.thread_capture, self.thread_infer, self.thread_encode):
            t = threading.Thread(target=fn)
            t.daemon = True
            t.start()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/info"):
            body = json.dumps(g_info).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/stream"):
            # MJPEG 连续流：浏览器 <img> 直接播放，不依赖 JS 定时刷新
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            last = None
            try:
                while not g_stop:
                    with g_lock:
                        data = g_jpeg
                    if data and data is not last:
                        last = data
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n")
                        self.wfile.write(b"Content-Length: " + str(len(data)).encode() + b"\r\n\r\n")
                        self.wfile.write(data)
                        self.wfile.write(b"\r\n")
                    else:
                        time.sleep(0.005)
            except Exception:
                return
            return
        with g_lock:
            data = g_jpeg
        if not data:
            self.send_response(503)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--cam", type=int, default=0)
    args = ap.parse_args()

    hw = HW()
    print("PL VERSION = 0x%08X" % hw.rd(R_VER))
    p = Pipeline(hw, args.cam)
    p.start()
    time.sleep(1.0)
    srv = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    print("预览：http://<板子IP>:%d/" % args.port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        global g_stop
        g_stop = True
    return 0


if __name__ == "__main__":
    sys.exit(main())
