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
    "ncand": 0, "ntrk": 0, "stable": 0, "err": "",
}
JPEG = {"buf": None, "seq": 0}
INFER = {"npu": 1, "pmin": 0, "running": True, "quality": 65, "push_every": 1}
TMP = {
    "clip": "/root/npu/cls128_drone_ZG.json",
    "raw": "/root/npu/cls128_drone_ZG.raw",
}


def find_cam(fallback=0):
    """按 v4l2 名字找 USB Camera，返回设备号；找不到则返回 fallback。

    设备号会漂移：同一台相机插在不同 USB 口上会枚举成 /dev/video0 / video1 / video3，
    而板载 Linlon VPU 固定占一个号。硬编码 VideoCapture(0) 会在换口后打不开，
    表现为 read() 一直失败、/info 的 frames 不涨（服务空转但看不出错）。
    """
    import subprocess
    import re
    try:
        out = subprocess.run(["v4l2-ctl", "--list-devices"],
                             capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return fallback
    lines = out.split("\n")
    for i, ln in enumerate(lines):
        if "USB Camera" in ln:
            for nxt in lines[i + 1:i + 6]:
                m = re.search(r"/dev/video(\d+)", nxt)
                if m:
                    return int(m.group(1))
    return fallback


# ---------------------------------------------------------------- 航迹跟踪


class Tracker(object):
    """跨帧候选跟踪 + 去抖（三域链路用）。

    与 cam_pipe.py 的同名类同源，另加两项：
      · p（NPU 概率）做 EMA 平滑 —— 判别结果不再逐帧跳变
      · trail（最近 40 帧坐标）—— 画面上能画出运动轨迹

    规则：
      * 相邻帧位置差 <= 匹配半径视为同一条 track（坐标/面积/峰值/概率都做 EMA 平滑）
      * 连续命中 >= MIN_HITS 帧才对外显示；连续丢失 > MAX_MISS 帧才移除
      * 匹配半径随速度放大：静止 10 px，20 px/帧 -> 60 px，上限 90 px
    性能：候选按峰值预剪 MAX_IN，track 池上限 MAX_TRACKS，避免 O(候选×track) 爆炸。
    """

    MATCH_R = 10        # 基础匹配半径（像素）
    MIN_HITS = 2        # 连续命中多少帧才显示（2 = 单帧孤立候选不显示，虚警残留 76.6%→0.8%）
    MAX_MISS = 10       # 连续丢失多少帧才删除
    MAX_SHOW = 64       # 最多显示多少条航迹
    PEAK_MIN = 0        # 候选峰值下限
    MAX_IN = 16         # 每帧最多送进跟踪的候选数（按峰值排序取前 N）
    MAX_TRACKS = 64     # track 池上限
    TRAIL_LEN = 40      # 轨迹保留点数

    def __init__(self):
        self.tracks = []
        self.next_id = 1

    def update(self, cands, fps=25.0):
        # 1) 候选预剪：按峰值排序，只保留前 MAX_IN 个
        cs = sorted(cands, key=lambda c: -int(c.get("peak", 0)))[:self.MAX_IN]
        nt = len(self.tracks)
        used = [False] * nt

        for c in cs:
            if int(c.get("peak", 0)) < self.PEAK_MIN:
                continue
            cx, cy = int(c["x"]), int(c["y"])
            best, bestd = -1, 10 ** 9
            for i in range(nt):
                if used[i]:
                    continue
                t = self.tracks[i]
                spd = abs(t.get("vx", 0.0)) + abs(t.get("vy", 0.0))
                pr = min(90, int(self.MATCH_R + 2.5 * spd))
                px = t["x"] + t.get("vx", 0.0)     # 按速度预测再比距离
                py = t["y"] + t.get("vy", 0.0)
                d = max(abs(px - cx), abs(py - cy))
                if d <= pr and d < bestd:
                    best, bestd = i, d

            if best >= 0:
                t = self.tracks[best]
                used[best] = True
                dx, dy = cx - t["x"], cy - t["y"]
                t["x"] = (4 * t["x"] + cx) / 5.0
                t["y"] = (4 * t["y"] + cy) / 5.0
                t["area"] = (4 * t["area"] + int(c.get("area", 1))) / 5.0
                t["peak"] = (4 * t["peak"] + int(c.get("peak", 0))) / 5.0
                cp = c.get("p")                     # 概率做 EMA（负值表示判别失败，不参与）
                if cp is not None and cp >= 0:
                    t["p"] = cp if t.get("p") is None else 0.7 * t["p"] + 0.3 * cp
                t["vx"] = 0.6 * t.get("vx", 0.0) + 0.4 * dx
                t["vy"] = 0.6 * t.get("vy", 0.0) + 0.4 * dy
                t["hits"] += 1
                t["miss"] = 0
                tr = t["trail"]
                tr.append((int(t["x"]), int(t["y"])))
                if len(tr) > self.TRAIL_LEN:
                    tr.pop(0)
            else:
                cp = c.get("p")
                self.tracks.append({
                    "id": self.next_id,
                    "x": float(cx), "y": float(cy),
                    "area": float(c.get("area", 1)), "peak": float(c.get("peak", 0)),
                    "p": cp if (cp is not None and cp >= 0) else None,
                    "vx": 0.0, "vy": 0.0,
                    "hits": 1, "miss": 0,
                    "trail": [(cx, cy)],
                })
                self.next_id += 1

        # 2) 未匹配的 track 衰减
        keep = []
        for i, t in enumerate(self.tracks):
            if i < nt and not used[i]:
                t["miss"] += 1
                t["vx"] *= 0.5
                t["vy"] *= 0.5
                if t["hits"] > 1:
                    t["hits"] -= 1
            if t["miss"] <= self.MAX_MISS:
                keep.append(t)

        # 3) 池上限：优先保留命中多、丢失少的
        if len(keep) > self.MAX_TRACKS:
            keep.sort(key=lambda t: (-t["hits"], t["miss"]))
            keep = keep[:self.MAX_TRACKS]
        self.tracks = keep

        conf = [t for t in self.tracks if t["hits"] >= self.MIN_HITS]
        conf.sort(key=lambda t: (-t["hits"], -t["peak"]))
        out = conf[:self.MAX_SHOW]
        for t in out:
            t["spd"] = int((t.get("vx", 0.0) ** 2 + t.get("vy", 0.0) ** 2) ** 0.5 * fps)
        return out


TRACKER = Tracker()


# ---------------------------------------------------------------- 推理线程
def infer_loop(pl, net):
    """相机 -> PL -> 候选 -> (NPU) -> 画框 -> JPEG 缓冲。"""
    cam_idx = find_cam(0)
    print("[cam] using /dev/video%d" % cam_idx, flush=True)
    cap = cv2.VideoCapture(cam_idx, cv2.CAP_V4L2)
    # 先设 FOURCC 再设分辨率：不少 UVC 相机只有在 MJPG 下才支持 640x480@30
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)
    _fcc = int(cap.get(cv2.CAP_PROP_FOURCC))
    _fcc_s = "".join(chr((_fcc >> (8 * k)) & 0xFF) for k in range(4))
    print("[cam] /dev/video%d  fourcc=%s  %.0fx%.0f  q=%d  push_every=%d"
          % (cam_idx, _fcc_s, cap.get(cv2.CAP_PROP_FRAME_WIDTH),
             cap.get(cv2.CAP_PROP_FRAME_HEIGHT), INFER["quality"], INFER["push_every"]),
          flush=True)
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
                patch = crop(gray, c["x"], c["y"], side=side)
                try:
                    pr = net.predict(patch)
                    c["p"] = float(pr[1])
                except Exception:                                  # noqa: BLE001
                    c["p"] = -1.0
            STATE["npu_ms"] = (time.time() - t1) * 1000.0 / max(1, len(keep))

        # 跟踪：把逐个候选关联成航迹（平滑坐标 + 稳定 ID + 速度 + 轨迹线）
        fps_now = STATE["fps"] if STATE["fps"] > 1.0 else 25.0
        trks = TRACKER.update(keep, fps_now)

        # 画框（走航迹，而不是原始候选）
        vis = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        for t in trks:
            tx, ty = int(t["x"]), int(t["y"])
            s = max(6, int((t["area"] ** 0.5) * 1.6))
            p = t.get("p")
            col = (0, 255, 0) if (p is None or p >= 0.5) else (0, 165, 255)
            # 轨迹线：两帧以上才画
            tr = t.get("trail") or []
            if len(tr) >= 2:
                pts = np.array(tr, dtype=np.int32).reshape(-1, 1, 2)
                cv2.polylines(vis, [pts], False, col, 1, cv2.LINE_AA)
            cv2.rectangle(vis, (tx - s, ty - s), (tx + s, ty + s), col, 2)
            tag = "#%d %dpx pk%d" % (t["id"], int(t["area"]), int(t["peak"]))
            if p is not None and p >= 0:
                tag += " d%.2f" % p
            cv2.putText(vis, tag, (tx + s + 3, ty - s + 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.38, col, 1, cv2.LINE_AA)

        cnt += 1
        el = time.time() - t_last
        if el >= 1.0:
            STATE["fps"] = cnt / el
            cnt, t_last = 0, time.time()
        STATE["frames"] += 1
        STATE["ncand"] = len(keep)
        STATE["ntrk"] = len(trks)
        STATE["stable"] = sum(1 for t in trks if t.get("p") is None or t["p"] >= 0.5)
        cv2.putText(vis, "PL %.1fms  npu %.2fms  cand %d  trk %d  %3d fps" %
                    (STATE["pl_ms"], STATE["npu_ms"], len(keep), len(trks), int(STATE["fps"])),
                    (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 255), 1, cv2.LINE_AA)

        # 隔帧推流：每 push_every 帧才编码一次。
        # 采集与检测仍逐帧进行（STATE["fps"] 始终是采集帧率），只跳过 JPEG 编码这一步。
        if INFER["push_every"] <= 1 or (STATE["frames"] % INFER["push_every"]) == 0:
            ok2, jb = cv2.imencode(".jpg", vis,
                                   [int(cv2.IMWRITE_JPEG_QUALITY), INFER["quality"]])
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
'ms | cand '+o.ncand+' | trk '+o.ntrk+' | frames '+o.frames+(o.err?(' | ERR '+o.err):'');})},1000);
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
    ap.add_argument("--quality", type=int, default=65, help="推流 JPEG 质量（默认 65；80 更清晰但更耗 CPU）")
    ap.add_argument("--push-every", type=int, default=1, help="每 N 帧推一次流（默认 1=每帧；2 可省一半编码开销）")
    a = ap.parse_args()
    INFER["npu"], INFER["pmin"] = a.npu, a.pmin
    INFER["quality"], INFER["push_every"] = a.quality, max(1, a.push_every)

    print("打开 PL3D ...", flush=True)
    pl = PL3D()
    try:
        print("VERSION=0x%08X" % (pl.reg.read(0x400C0014) & 0xFFFFFFFF), flush=True)
    except Exception:                                              # noqa: BLE001
        print("VERSION 读取跳过", flush=True)

    net = None
    if a.npu and os.path.exists(TMP["clip"]) and os.path.exists(TMP["raw"]):
        try:
            net = NPU(TMP["clip"], TMP["raw"], dev=pl.dev)
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
