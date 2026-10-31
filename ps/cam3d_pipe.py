#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cam3d_pipe.py —— 三域位流实时链路网页版

链路：USB 相机 -> 640x360 灰度 -> PL-DDR -> 触发 PL 检测器 -> 读候选表
      -> x=(x+125)%640 修正 + 边带过滤 -> （可选）NPU cls128 分类
      -> 画框/HUD -> JPEG -> 网页 MJPEG

端口：8080。页面：“/”单页；数据：“/info”；流：“/live”；单帧：“/snap”。
安全：只读写已验证的寄存器地址；NPU 可用 --npu 0 关掉。

用法：
  python3 -u cam3d_pipe.py --host 0.0.0.0 --port 8080 --npu 1
"""
import argparse
import io
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cam3d_test import PL3D, NPU, unpack, crop  # noqa: E402

W, H = 640, 360
BORDER = 24          # 上/下/左 边带不参与（压掉天花板/墙的亮带）
XOFF = 125           # 实测列偏移：x_true = (x_det + 125) % W

STATE = {
    "frames": 0, "fps": 0.0, "pl_ms": 0.0, "npu_ms": 0.0,
    "ncand": 0, "stable": 0, "err": "",
}
JPEG = {"buf": None, "seq": 0}
INFER = {"npu": 1, "pmin": 0, "running": True}
TMP = {
    "clip": os.path.join(os.path.dirname(os.path.abspath(__file__)), "cls128_drone_ZG.json"),
    "raw": os.path.join(os.path.dirname(os.path.abspath(__file__)), "cls128_drone_ZG.raw"),
}


# ---------------------------------------------------------------- 推理线程
def infer_loop(pl, net):
    """相机 -> PL -> 候选 -> (NPU) -> 画框 -> JPEG 缓冲。"""
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"YUYV"))
    t_last, cnt = time.time(), 0

    while INFER["running"]:
        ok, frame = cap.read()
        if not ok:
            time.sleep(0.01)
            continue
        gray = cv2.cvtColor(frame[60:420, :], cv2.COLOR_BGR2GRAY)   # 裁上下 60 行
        if gray.shape[:2] != (H, W):
            gray = cv2.resize(gray, (W, H), interpolation=cv2.INTER_AREA)

        t0 = time.time()
        try:
            cands, st, dt = pl.run(gray)   # unpack 已应用 X_SHIFT 与 BORDER
        except Exception as e:                                     # noqa: BLE001
            STATE["err"] = "pl:%s" % e
            time.sleep(0.2)
            continue
        STATE["pl_ms"] = dt

        # 坐标修正 + 边带过滤
        keep = []
        for c in cands:
            x = c["x"] % W
            y = c["y"]
            if y < BORDER or y > H - 8 or x < 8 or x > W - 8:
                continue
            if c["peak"] < INFER["pmin"]:
                continue
            keep.append({"x": x, "y": y, "area": c["area"], "peak": c["peak"], "p": None})

        # NPU 复核（只判是不是无人机）
        if INFER["npu"] and net is not None and keep:
            t1 = time.time()
            for c in keep:
                side = max(16, int(round(2.5 * (c["area"] ** 0.5))))
                patch = crop(gray, c["x"], c["y"], side=side, out=128)
                try:
                    pr = net.predict(patch)
                    c["p"] = float(pr[1])
                except Exception:                                  # noqa: BLE001
                    c["p"] = -1.0
            STATE["npu_ms"] = (time.time() - t1) * 1000.0 / max(1, len(keep))

        # 画框
        vis = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        for c in keep:
            s = max(6, int((c["area"] ** 0.5) * 1.6))
            col = (0, 255, 0) if (c["p"] is None or c["p"] >= 0.5) else (0, 165, 255)
            cv2.rectangle(vis, (c["x"] - s, c["y"] - s), (c["x"] + s, c["y"] + s), col, 2)
            tag = "%dpx pk%d" % (c["area"], c["peak"])
            if c["p"] is not None and c["p"] >= 0:
                tag += " d%.2f" % c["p"]
            cv2.putText(vis, tag, (c["x"] + s + 3, c["y"] - s + 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.38, col, 1, cv2.LINE_AA)

        cnt += 1
        el = time.time() - t_last
        if el >= 1.0:
            STATE["fps"] = cnt / el
            cnt, t_last = 0, time.time()
        STATE["frames"] += 1
        STATE["ncand"] = len(keep)
        STATE["stable"] = sum(1 for c in keep if c["p"] is None or c["p"] >= 0.5)
        cv2.putText(vis, "PL %.1fms  npu %.2fms  cand %d  %3d fps" %
                    (STATE["pl_ms"], STATE["npu_ms"], len(keep), int(STATE["fps"])),
                    (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 255), 1, cv2.LINE_AA)

        ok2, jb = cv2.imencode(".jpg", vis, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if ok2:
            JPEG["buf"] = jb.tobytes()
            JPEG["seq"] += 1
    cap.release()


# ---------------------------------------------------------------- HTTP
PAGE = b"""<!doctype html><meta charset=utf-8><title>3D realtime</title>
<style>body{margin:0;background:#111;color:#ddd;font:13px/1.5 monospace}
img{width:100%;max-width:1280px;display:block}#h{padding:6px 10px}</style>
<div id=h>3D realtime &mdash; <span id=s>---</span></div>
<img id=v src="/live"><script>
setInterval(function(){fetch('/info').then(r=>r.json()).then(function(o){
document.getElementById('s').textContent=
'fps '+o.fps.toFixed(1)+' | PL '+o.pl_ms.toFixed(1)+'ms | npu '+o.npu_ms.toFixed(2)+
'ms | cand '+o.ncand+' | frames '+o.frames+(o.err?(' | ERR '+o.err):'');})},1000);
</script>"""


class SrvHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):        # 静音
        pass

    def _send(self, code, ctype, body, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):                 # noqa: N802
        p = self.path.split("?")[0]
        if p == "/":
            self._send(200, "text/html; charset=utf-8", PAGE)
        elif p == "/info":
            self._send(200, "application/json", json.dumps(STATE).encode())
        elif p == "/snap":
            b = JPEG["buf"] or b""
            self._send(200 if b else 503, "image/jpeg", b)
        elif p == "/live":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=f")
            self.end_headers()
            last = -1
            try:
                while True:
                    if JPEG["seq"] != last and JPEG["buf"]:
                        last = JPEG["seq"]
                        self.wfile.write(b"--f\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                         + str(len(JPEG["buf"])).encode() + b"\r\n\r\n")
                        self.wfile.write(JPEG["buf"])
                        self.wfile.write(b"\r\n")
                    time.sleep(0.01)
            except (BrokenPipeError, ConnectionResetError):
                return
        elif p == "/set":
            q = dict(kv.split("=", 1) for kv in self.path.split("?", 1)[1].split("&")) if "?" in self.path else {}
            if "npu" in q:
                INFER["npu"] = 1 if q["npu"] not in ("0", "false") else 0
            if "pmin" in q:
                INFER["pmin"] = int(q["pmin"])
            self._send(200, "application/json", json.dumps({"npu": INFER["npu"], "pmin": INFER["pmin"]}).encode())
        else:
            self._send(404, "text/plain", b"no")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--npu", type=int, default=1)
    ap.add_argument("--pmin", type=int, default=0)
    ap.add_argument("--frames", type=int, default=0, help=">0 则跑这么多帧后退出（自测用）")
    a = ap.parse_args()
    INFER["npu"], INFER["pmin"] = a.npu, a.pmin

    print("打开 PL3D ...", flush=True)
    pl = PL3D()
    try:
        print("VERSION=0x%08X" % (pl.reg.read(0x400C0014) & 0xFFFFFFFF), flush=True)
    except Exception:                                              # noqa: BLE001
        print("VERSION 读取跳过", flush=True)

    net = None
    if a.npu and os.path.exists(TMP["clip"]) and os.path.exists(TMP["raw"]):
        try:
            net = NPU(TMP["clip"], TMP["raw"])
            print("NPU ok", flush=True)
        except Exception as e:                                     # noqa: BLE001
            print("NPU 不可用，降级为纯 PL：%s" % e, flush=True)

    th = threading.Thread(target=infer_loop, args=(pl, net), daemon=True)
    th.start()

    if a.frames > 0:                   # 自测模式：不启服务器
        t0 = time.time()
        while STATE["frames"] < a.frames and time.time() - t0 < 60:
            time.sleep(0.2)
        print(json.dumps(STATE), flush=True)
        INFER["running"] = False
        time.sleep(0.5)
        return

    srv = ThreadingHTTPServer(("0.0.0.0", a.port), SrvHandler)
    print("serving on :%d" % a.port, flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
