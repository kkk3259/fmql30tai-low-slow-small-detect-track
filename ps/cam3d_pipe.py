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
    "cap_ms": 0.0, "enc_ms": 0.0,
    "ncand": 0, "ntrk": 0, "stable": 0, "err": "",
    "cands": [], "raw": [],
}
JPEG = {"buf": None, "seq": 0}
INFER = {"npu": 1, "pmin": 0, "running": True, "quality": 65, "push_every": 1}
# 显示与前处理（2026-11-01 新增：三域版之前直接推灰度原图，观感"一片灰"）
COLOR_DISP = 1          # 1=画面用彩色（检测仍在灰度上做）；0=灰度
GAMMA = 1.0             # 送 PL 前的 gamma（0.08 压缩动态范围、弱目标更容易过 CFAR 门限；1.0=不改）
INVERT = 0              # 1=把 255-gray 送 PL（等价 Black-Hat，找暗目标）
_LUT = None


def _make_lut():
    """gamma LUT；参数变了才重建。"""
    global _LUT
    key = ("g", GAMMA)
    if _LUT is None or _LUT[0] != key:
        if GAMMA == 1.0:
            _LUT = (key, None)
        else:
            _LUT = (key, np.array([min(255, int(255.0 * ((i / 255.0) ** GAMMA)))
                                   for i in range(256)], np.uint8))
    return _LUT[1]


def to_pl(gray):
    """显示用的灰度 -> 送 PL 的灰度（gamma + 取反）。坐标不变（单调变换）。"""
    g = gray
    lut = _make_lut()
    if lut is not None:
        g = cv2.LUT(g, lut)
    if INVERT:
        g = (255 - g).astype(np.uint8)
    return g
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
        _t_cap = time.time()
        ok, frame = cap.read()
        STATE["cap_ms"] = 0.85 * STATE["cap_ms"] + 0.15 * (time.time() - _t_cap) * 1000.0
        if not ok:
            time.sleep(0.01)
            continue
        gray = cv2.cvtColor(frame[60:420, :], cv2.COLOR_BGR2GRAY)   # 裁上下 60 行
        if gray.shape[:2] != (H, W):
            gray = cv2.resize(gray, (W, H), interpolation=cv2.INTER_AREA)

        t0 = time.time()
        try:
            cands, st, dt = pl.run(to_pl(gray))   # gamma/取反只影响送 PL 的那份；unpack 已应用 X_SHIFT 与 BORDER
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
        if COLOR_DISP:
            vis = frame[60:420, :].copy()                          # 彩色：观感跟独立版一致
            if vis.shape[:2] != (H, W):
                vis = cv2.resize(vis, (W, H), interpolation=cv2.INTER_AREA)
        else:
            vis = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        # ── 先画 PL 的全部候选（灰细框 + 面积标注）──
        # 用户要求"把 PL 所有候选都显示出来"：这些是 keep 里的原始候选，
        # 未经航迹确认，可能一闪而过。画在下面，被同位置的绿/橙航迹框覆盖。
        for c in keep:
            cx, cy = int(c["x"]), int(c["y"])
            a = int(c["area"])
            s = max(4, int((a ** 0.5) * 1.3))
            cv2.rectangle(vis, (cx - s, cy - s), (cx + s, cy + s), (150, 150, 150), 1)
            if a >= 4:                      # 太小的点不标字，避免糊成一团
                cv2.putText(vis, "%d" % a, (cx + s + 1, cy + s + 2),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.28, (170, 170, 170), 1, cv2.LINE_AA)

        # ── 再画确认航迹（绿=通过 / 橙=未通过）──
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
        # 航迹明细（网页右侧列表 / 资源面板用）
        # 原始候选取前 32 个（全部画框已在图上，列表只列前 32 避免刷屏）
        STATE["raw"] = [{
            "x": int(c["x"]), "y": int(c["y"]),
            "area": int(c["area"]), "peak": int(c["peak"]),
        } for c in keep[:32]]
        STATE["cands"] = [{
            "id": int(t["id"]), "x": int(t["x"]), "y": int(t["y"]),
            "area": int(t["area"]), "peak": int(t["peak"]),
            "p": (None if t.get("p") is None else round(float(t["p"]), 3)),
            "spd": int(t.get("spd", 0)), "hits": int(t.get("hits", 0)),
            "vx": round(float(t.get("vx", 0.0)), 2), "vy": round(float(t.get("vy", 0.0)), 2),
        } for t in trks]
        cv2.putText(vis, "PL %.1fms  npu %.2fms  cand %d  trk %d  %3d fps" %
                    (STATE["pl_ms"], STATE["npu_ms"], len(keep), len(trks), int(STATE["fps"])),
                    (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 255), 1, cv2.LINE_AA)

        # 隔帧推流：每 push_every 帧才编码一次。
        # 采集与检测仍逐帧进行（STATE["fps"] 始终是采集帧率），只跳过 JPEG 编码这一步。
        if INFER["push_every"] <= 1 or (STATE["frames"] % INFER["push_every"]) == 0:
            _t_enc = time.time()
            ok2, jb = cv2.imencode(".jpg", vis,
                                   [int(cv2.IMWRITE_JPEG_QUALITY), INFER["quality"]])
            STATE["enc_ms"] = 0.85 * STATE["enc_ms"] + 0.15 * (time.time() - _t_enc) * 1000.0
            if ok2:
                JPEG["buf"] = jb.tobytes()
                JPEG["seq"] += 1
    cap.release()


# ---------------------------------------------------------------- HTTP
PAGE = """<!doctype html><html><head><meta charset=utf-8>
<title>3D realtime console</title>
<style>
*{box-sizing:border-box}
body{margin:0;background:#111;color:#ddd;font:13px/1.5 "Microsoft YaHei",monospace}
#top{background:#1a1a1a;padding:6px 12px;border-bottom:1px solid #333;white-space:nowrap;overflow-x:auto}
#top b{color:#4caf50}#top .k{color:#888;margin-left:12px}#top .v{color:#4fc3f7;font-weight:bold}
#main{display:flex;height:calc(100vh - 34px)}
#left{flex:1;display:flex;align-items:center;justify-content:center;background:#000;overflow:hidden;position:relative}
#left img{width:100%;height:100%;object-fit:contain;display:block}
#right{width:340px;background:#161616;border-left:1px solid #333;overflow-y:auto;padding:10px}
#fold{position:absolute;top:8px;right:8px;z-index:99;background:rgba(40,40,40,.85);
      border:1px solid #555;color:#ccc;padding:3px 10px;cursor:pointer;border-radius:3px;font-size:12px}
#fold:hover{background:#444;color:#fff}
.sec{margin-bottom:14px}
.sec h3{margin:0 0 6px;font-size:13px;color:#4fc3f7;font-weight:normal;border-bottom:1px solid #2a2a2a;padding-bottom:3px}
.row{display:flex;justify-content:space-between;padding:2px 0;font-size:12px}
.row .l{color:#999}.row .r{color:#e0e0e0;font-family:Consolas,monospace}
.bar{height:8px;background:#222;border-radius:2px;overflow:hidden;margin-top:2px}
.bar i{display:block;height:100%;background:linear-gradient(90deg,#2e7d32,#66bb6a);width:0}
.bar.pl i{background:linear-gradient(90deg,#1565c0,#42a5f5)}
.bar.npu i{background:linear-gradient(90deg,#6a1b9a,#ab47bc)}
.bar.tk i{background:linear-gradient(90deg,#ef6c00,#ffa726)}
.bar.en i{background:linear-gradient(90deg,#c62828,#ef5350)}
.sl{margin:7px 0 12px}
.sl label{display:flex;justify-content:space-between;font-size:12px;color:#999;margin-bottom:2px}
.sl label span{color:#4fc3f7;font-family:Consolas,monospace}
.sl input{width:100%;height:18px}
table{width:100%;border-collapse:collapse;font-size:11.5px;font-family:Consolas,monospace}
th{color:#666;text-align:left;font-weight:normal;border-bottom:1px solid #2a2a2a;padding:2px 3px}
td{padding:2px 3px;border-bottom:1px solid #1e1e1e;color:#ccc}
tr.g td:first-child{color:#4caf50}tr.o td:first-child{color:#ff9800}
#err{color:#ef5350;font-size:12px;padding:4px 0}
</style></head><body>
<div id="top">
  <b>3D realtime</b>
  <span class="k">fps</span><span class="v" id="v_fps">-</span>
  <span class="k">PL</span><span class="v" id="v_pl">-</span>
  <span class="k">NPU</span><span class="v" id="v_npu">-</span>
  <span class="k">候选</span><span class="v" id="v_nc">-</span>
  <span class="k">航迹</span><span class="v" id="v_nt">-</span>
  <span class="k">通过</span><span class="v" id="v_st">-</span>
  <span class="k">帧数</span><span class="v" id="v_fr">-</span>
</div>
<button id="fold" onclick="toggleFold()">隐藏侧栏</button>
<div id="main">
  <div id="left"><img id="v" src="/live"></div>
  <div id="right">

    <div class="sec">
      <h3>资源占用（单帧耗时）</h3>
      <div class="row"><span class="l">采集</span><span class="r" id="r_cap">- ms</span></div>
      <div class="bar"><i id="b_cap"></i></div>
      <div class="row"><span class="l">PL 检测</span><span class="r" id="r_pl">- ms</span></div>
      <div class="bar pl"><i id="b_pl"></i></div>
      <div class="row"><span class="l">NPU 判别</span><span class="r" id="r_npu">- ms</span></div>
      <div class="bar npu"><i id="b_npu"></i></div>
      <div class="row"><span class="l">跟踪</span><span class="r" id="r_tk">- ms</span></div>
      <div class="bar tk"><i id="b_tk"></i></div>
      <div class="row"><span class="l">编码</span><span class="r" id="r_en">- ms</span></div>
      <div class="bar en"><i id="b_en"></i></div>
    </div>

    <div class="sec">
      <h3>可调参数（拖动即时生效）</h3>
      <div class="sl">
        <label>峰值下限 <span id="l_pmin">0</span></label>
        <input type="range" id="s_pmin" min="0" max="255" value="0"
               oninput="document.getElementById('l_pmin').textContent=this.value"
               onchange="setp({pmin:this.value})">
      </div>
      <div class="sl">
        <label>航迹确认帧数 <span id="l_hits">2</span></label>
        <input type="range" id="s_hits" min="1" max="6" value="2"
               oninput="document.getElementById('l_hits').textContent=this.value"
               onchange="setp({min_hits:this.value})">
      </div>
      <div class="sl">
        <label>推流画质 <span id="l_q">65</span></label>
        <input type="range" id="s_q" min="30" max="95" value="65"
               oninput="document.getElementById('l_q').textContent=this.value"
               onchange="setp({quality:this.value})">
      </div>
      <div class="sl">
        <label>Gamma <span id="l_g">1.00</span></label>
        <input type="range" id="s_g" min="2" max="150" value="100"
               oninput="document.getElementById('l_g').textContent=(this.value/100).toFixed(2)"
               onchange="setp({gamma:this.value/100})">
      </div>
      <div class="sl">
        <label>NPU 判别 <input type="checkbox" id="c_npu" checked onchange="setp({npu:this.checked?1:0})"></label>
      </div>
      <div class="sl">
        <label>找暗目标（invert）<input type="checkbox" id="c_inv" onchange="setp({invert:this.checked?1:0})"></label>
      </div>
    </div>

    <div class="sec">
      <h3>PL 原始候选 <span id="v_nraw" style="color:#4fc3f7">0</span> 个</h3>
      <table><thead><tr>
        <th>x</th><th>y</th><th>area</th><th>peak</th>
      </tr></thead><tbody id="tbraw"></tbody></table>
    </div>

    <div class="sec">
      <h3>确认航迹</h3>
      <table><thead><tr>
        <th>#id</th><th>x</th><th>y</th><th>area</th><th>pk</th><th>p</th><th>v</th>
      </tr></thead><tbody id="tb"></tbody></table>
    </div>
    <div id="err"></div>
  </div>
</div>
<script>
function toggleFold(){
  var r=document.getElementById('right'), b=document.getElementById('fold');
  if(r.style.display==='none'){r.style.display='block';b.textContent='隐藏侧栏';}
  else{r.style.display='none';b.textContent='显示侧栏';}
}
function setp(o){
  var q=Object.keys(o).map(function(k){return k+'='+encodeURIComponent(o[k])}).join('&');
  fetch('/set?'+q).then(function(r){return r.json()}).then(function(j){
    if(j.error){document.getElementById('err').textContent='参数错误: '+j.error;}
    else{document.getElementById('err').textContent='';}
  }).catch(function(){});
}
var lastSeq=0;
function tick(){
  fetch('/info').then(function(r){return r.json()}).then(function(o){
    function s(id,v){var e=document.getElementById(id); if(e) e.textContent=v;}
    s('v_fps',(o.fps||0).toFixed(1));
    s('v_pl',(o.pl_ms||0).toFixed(2)+'ms');
    s('v_npu',(o.npu_ms||0).toFixed(2)+'ms');
    s('v_nc',o.ncand||0); s('v_nt',o.ntrk||0); s('v_st',o.stable||0); s('v_fr',o.frames||0);
    // 资源占用条：以 40ms 为满刻度
    var SCALE=40;
    function bar(bid,rid,val){var v=val||0;
      document.getElementById(bid).style.width=Math.min(100,v/SCALE*100)+'%';
      document.getElementById(rid).textContent=v.toFixed(1)+' ms';}
    bar('b_cap','r_cap',o.cap_ms); bar('b_pl','r_pl',o.pl_ms);
    bar('b_npu','r_npu',o.npu_ms); bar('b_tk','r_tk',o.trk_ms||0);
    bar('b_en','r_en',o.enc_ms);
    // 航迹列表
    var tb=document.getElementById('tb'), h='';
    var cs=o.cands||[];
    for(var i=0;i<cs.length;i++){var c=cs[i];
      var cls=(c.p===null||c.p>=0.5)?'g':'o';
      h+='<tr class="'+cls+'"><td>#'+c.id+'</td><td>'+c.x+'</td><td>'+c.y+'</td><td>'+c.area+'</td><td>'+c.peak+'</td><td>'+
         (c.p===null?'-':c.p.toFixed(2))+'</td><td>'+c.spd+'</td></tr>';
    }
    if(!h) h='<tr><td colspan=7 style="color:#666">（无航迹）</td></tr>';
    tb.innerHTML=h;
    // 原始候选列表
    var tr2=document.getElementById('tbraw'), h2='';
    var rc=o.raw||[];
    document.getElementById('v_nraw').textContent=rc.length;
    for(var k=0;k<rc.length;k++){var c=rc[k];
      h2+='<tr><td>'+c.x+'</td><td>'+c.y+'</td><td>'+c.area+'</td><td>'+c.peak+'</td></tr>';
    }
    if(!h2) h2='<tr><td colspan=4 style="color:#666">（无候选）</td></tr>';
    tr2.innerHTML=h2;
    if(o.err){document.getElementById('err').textContent=String(o.err).slice(0,120);}
  }).catch(function(){});
  setTimeout(tick,500);
}
tick();
</script></body></html>"""



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
            self._send(200, "text/html; charset=utf-8", PAGE.encode("utf-8"))
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
            global GAMMA, INVERT, COLOR_DISP
            q = dict(kv.split("=", 1) for kv in self.path.split("?", 1)[1].split("&")) if "?" in self.path else {}
            try:
                if "npu" in q:
                    INFER["npu"] = 1 if q["npu"] not in ("0", "false") else 0
                if "pmin" in q:
                    INFER["pmin"] = max(0, int(q["pmin"]))
                if "min_hits" in q:
                    TRACKER.MIN_HITS = max(1, min(10, int(q["min_hits"])))
                if "quality" in q:
                    INFER["quality"] = max(20, min(95, int(q["quality"])))
                if "gamma" in q:
                    GAMMA = max(0.02, min(2.0, float(q["gamma"])))
                if "invert" in q:
                    INVERT = 1 if q["invert"] not in ("0", "false") else 0
                if "color" in q:
                    COLOR_DISP = 1 if q["color"] not in ("0", "false") else 0
            except (ValueError, TypeError) as e:
                self._send(400, "application/json", json.dumps({"error": str(e)}).encode())
                return
            cur = {"npu": INFER["npu"], "pmin": INFER["pmin"],
                   "min_hits": TRACKER.MIN_HITS, "quality": INFER["quality"],
                   "gamma": GAMMA, "invert": INVERT, "color": COLOR_DISP}
            self._send(200, "application/json", json.dumps(cur).encode())
        else:
            self._send(404, "text/plain", b"no")


def main():
    global GAMMA, INVERT, COLOR_DISP
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--npu", type=int, default=1)
    ap.add_argument("--pmin", type=int, default=0)
    ap.add_argument("--frames", type=int, default=0, help=">0 则跑这么多帧后退出（自测用）")
    ap.add_argument("--gamma", type=float, default=1.0, help="送 PL 前 gamma（0.08 压缩动态范围，弱目标更易过门限；1.0 不改）")
    ap.add_argument("--invert", type=int, default=0, help="1=找暗目标（逆光天空鸟/无人机）")
    ap.add_argument("--color", type=int, default=1, help="1=彩色画面 0=灰度")
    ap.add_argument("--quality", type=int, default=65, help="推流 JPEG 质量（默认 65；80 更清晰但更耗 CPU）")
    ap.add_argument("--push-every", type=int, default=1, help="每 N 帧推一次流（默认 1=每帧；2 可省一半编码开销）")
    a = ap.parse_args()
    INFER["npu"], INFER["pmin"] = a.npu, a.pmin
    INFER["quality"], INFER["push_every"] = a.quality, max(1, a.push_every)
    GAMMA, INVERT, COLOR_DISP = a.gamma, a.invert, a.color

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
