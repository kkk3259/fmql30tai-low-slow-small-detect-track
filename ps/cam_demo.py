#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# cam_demo.py —— 摄像头 -> PL(IP2) -> 候选框 -> 网页实时预览（板端自包含）
#
# 用法：
#   python3 cam_demo.py                 # 无限跑，网页 http://<板IP>:8080/
#   python3 cam_demo.py --frames 60     # 跑 60 帧就退出（打印统计）
#   python3 cam_demo.py --snap a.jpg    # 只抓一帧存 JPEG
#
# 依赖：cv2 / numpy（板上已有），/dev/video0（UVC 相机），/dev/udmabuf0，/dev/mem
import os, sys, time, json, struct, mmap as MM, threading, argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import numpy as np
import cv2

UDMA, SYS, DEVMEM = "/dev/udmabuf0", "/sys/class/u-dma-buf/udmabuf0", "/dev/mem"
REG = 0x43C00000
W, H = 640, 360
NPIX = W * H
R_CTRL, R_STATUS, R_VER = 0x00, 0x0C, 0x14
CAND_BASE = 0x18
R_FSM = 0x3C

g_lock = threading.Lock()
g_jpeg = None
g_info = {"fps": 0.0, "frames": 0, "cands": []}


def sysfs(name, val=None):
    p = os.path.join(SYS, name)
    if val is None:
        with open(p) as f:
            return f.read().strip()
    with open(p, "w") as f:
        f.write(str(val))


class HW(object):
    def __init__(self):
        self.fd = os.open(UDMA, os.O_RDWR | os.O_SYNC)
        self.buf = MM.mmap(self.fd, int(sysfs("size"), 0), MM.MAP_SHARED,
                           prot=MM.PROT_READ | MM.PROT_WRITE)
        self.rfd = os.open(DEVMEM, os.O_RDWR | os.O_SYNC)
        self.reg = MM.mmap(self.rfd, 0x1000, MM.MAP_SHARED, offset=REG)
        # 只同步真正用到的 640x360 字节，避免每帧清 128 MiB cache（实测可省 ~20 ms）
        try:
            sysfs("sync_offset", 0)
            sysfs("sync_size", NPIX)
        except Exception as e:
            print("WARN: 设置 sync_size 失败: %s" % e)

    def rd(self, o):
        return struct.unpack_from("<I", self.reg, o)[0]

    def wr(self, o, v):
        struct.pack_into("<I", self.reg, o, v & 0xFFFFFFFF)

    def run(self, gray):
        self.buf[0:NPIX] = gray.tobytes()
        sysfs("sync_for_device", 1)
        self.wr(R_CTRL, 1)
        t0 = time.time()
        while (time.time() - t0) < 3.0:
            st = self.rd(R_STATUS)
            if st & 0x06:
                break
            time.sleep(0.0001)
        raw = bytearray()
        for i in range(9):
            raw += struct.pack("<I", self.rd(CAND_BASE + 4 * i))
        n = raw[0]
        cands = []
        for i in range(min(n, 5)):
            b = raw[1 + i * 7: 8 + i * 7]
            if len(b) < 7:
                break
            cands.append({"x": (b[0] << 8) | b[1], "y": (b[2] << 8) | b[3],
                          "area": b[5], "peak": b[6]})
        return st, cands


def draw(color, cands):
    for c in cands:
        x, y = int(c["x"]), int(c["y"])
        cv2.rectangle(color, (x - 4, y - 4), (x + 4, y + 4), (0, 255, 0), 1)
        cv2.putText(color, "%d,%d a%d" % (x, y, c["area"]), (x + 6, max(y - 6, 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 0), 1, cv2.LINE_AA)
    cv2.putText(color, "n=%d" % len(cands), (6, 16), cv2.FONT_HERSHEY_SIMPLEX,
                0.5, (0, 255, 255), 1, cv2.LINE_AA)
    return color


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>IP2 实时检测</title>
<style>
body{margin:0;background:#0d0d0d;color:#7CFC00;font:14px/1.5 Consolas,monospace}
#hud{padding:8px 12px;border-bottom:1px solid #24451f;white-space:pre}
img{width:100%;max-width:1280px;display:block;margin:0 auto}
</style></head><body>
<div id="hud">连接中…</div>
<img id="v" src="/live">
<script>
const v = document.getElementById('v'), hud = document.getElementById('hud');
setInterval(function(){ v.src = '/live?t=' + Date.now(); }, 150);
setInterval(function(){
  fetch('/info').then(r=>r.json()).then(function(j){
    var n = (j.cands||[]).length;
    hud.textContent = 'PL 帧率 ' + j.fps + ' fps   |   PL 耗时 ' + j.PL_ms +
                      ' ms   |   候选 ' + n + (n ? '\n' + JSON.stringify(j.cands) : '');
  }).catch(function(){});
}, 600);
</script></body></html>"""

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
    ap.add_argument("--frames", type=int, default=0)
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--snap", default="")
    ap.add_argument("--cam", type=int, default=0)
    args = ap.parse_args()

    hw = HW()
    print("PL VERSION = 0x%08X" % hw.rd(R_VER))
    cap = cv2.VideoCapture(args.cam, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    # 640x480 采集，上下各裁 60 行得到 640x360（与 PL 链路一一对应，省掉缩放）
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    if not cap.isOpened():
        print("ERROR: 打不开摄像头")
        return 1
    ok, f0 = cap.read()
    if not ok:
        print("ERROR: 读不到帧")
        return 1
    print("摄像头分辨率 = %dx%d" % (f0.shape[1], f0.shape[0]))

    if not args.snap:
        srv = HTTPServer(("0.0.0.0", args.port), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        print("预览: http://<板IP>:%d/" % args.port)

    n = 0
    t_start = time.time()
    t_cap_sum = t_pl_sum = 0.0
    while True:
        t0 = time.time()
        ok, frame = cap.read()
        if not ok:
            time.sleep(0.002)
            continue
        t1 = time.time()
        fh = frame.shape[0]
        if fh >= H:
            top = (fh - H) // 2
            frame = frame[top:top + H, :, :]
        else:
            frame = cv2.resize(frame, (W, H), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        st, cands = hw.run(gray)
        t2 = time.time()
        t_cap_sum += (t1 - t0)
        t_pl_sum += (t2 - t1)
        n += 1
        info = draw(frame, cands)
        cv2.putText(info, "PL %.1f ms | n=%d | %.1f fps" %
                    ((t2 - t1) * 1000, len(cands), n / max(t2 - t_start, 1e-6)),
                    (6, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2, cv2.LINE_AA)
        ok, enc = cv2.imencode(".jpg", info, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if ok:
            with g_lock:
                globals()["g_jpeg"] = enc.tobytes()
            g_info.update({"fps": round(n / max(t2 - t_start, 1e-6), 2), "frames": n,
                           "cands": cands, "PL_ms": round((t2 - t1) * 1000, 2)})
        if args.snap:
            cv2.imwrite(args.snap, info)
            print("已存 %s  n=%d %s" % (args.snap, len(cands), cands))
            break
        if n % 20 == 0:
            print("帧 %d  捕获 %.1f ms  PL %.1f ms  候选 %d  %s" %
                  (n, 1000 * t_cap_sum / n, 1000 * t_pl_sum / n, len(cands),
                   [(c["x"], c["y"]) for c in cands]))
        if args.frames and n >= args.frames:
            break

    dt = time.time() - t_start
    print("=== 共 %d 帧, %.1f 秒, %.2f fps, 平均 PL %.1f ms ===" %
          (n, dt, n / dt, 1000 * t_pl_sum / max(n, 1)))
    cap.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
