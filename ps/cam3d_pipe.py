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
    "cands": [],
    # —— 供独立版页面模板读的键（缺一个页面就显示 undefined）——
    "PL_ms": 0.0, "lat_ms": 0.0, "raw": 0, "n": 0,
    "gamma": 1.0, "msk": 1, "stretch": 0, "invert": 0,
}
JPEG = {"buf": None, "seq": 0}
INFER = {"npu": 1, "pmin": 0, "running": True, "quality": 65, "push_every": 1}
# 显示与前处理（2026-11-01 新增：三域版之前直接推灰度原图，观感"一片灰"）
BURN_BOX = 0          # 1=把框烧进 JPEG；0=交给网页 canvas 画
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
        for t in (trks if BURN_BOX else []):
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
        STATE["cands"] = [{
            "id": int(t["id"]), "x": int(t["x"]), "y": int(t["y"]),
            "area": int(t["area"]), "peak": int(t["peak"]),
            "p": (None if t.get("p") is None else round(float(t["p"]), 3)),
            "spd": int(t.get("spd", 0)), "hits": int(t.get("hits", 0)),
            "vx": round(float(t.get("vx", 0.0)), 2), "vy": round(float(t.get("vy", 0.0)), 2),
        } for t in trks]
        STATE["raw"] = len(keep)
        STATE["n"] = len(STATE["cands"])
        STATE["PL_ms"] = round(STATE["pl_ms"], 2)
        STATE["lat_ms"] = round(STATE["pl_ms"] + STATE["cap_ms"] + STATE["enc_ms"], 1)
        STATE["gamma"] = round(GAMMA, 3)
        STATE["invert"] = 1 if INVERT else 0
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
PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>低小慢目标检测 · 实时控制台</title>
<style>
*{box-sizing:border-box}
body{margin:0;background:#0b1119;color:#cfe0f0;font:13px/1.55 -apple-system,"Segoe UI",Consolas,monospace}
.top{display:flex;align-items:center;gap:12px;padding:9px 16px;background:#101a26;border-bottom:1px solid #1e2c3d}
.top h1{font-size:15px;margin:0;font-weight:600;letter-spacing:.3px}
.badge{padding:2px 9px;border-radius:10px;font-size:11px;background:#12352a;color:#4ade80;border:1px solid #1c5c43}
.badge.b2{background:#1a2433;color:#7fb3d5;border-color:#2a3d52}
.wrap{display:flex;height:calc(100vh - 46px)}
.video{flex:1;position:relative;background:#000;display:flex;align-items:center;justify-content:center;overflow:hidden;padding:14px}
.vbox{position:relative;width:100%;max-width:100%;aspect-ratio:16/9;margin:auto}
.vbox img{display:block;width:100%;height:100%;object-fit:fill}
.vbox canvas{position:absolute;left:0;top:0;width:100%;height:100%;pointer-events:none}
.panel{width:360px;flex:none;background:#0e1723;border-left:1px solid #1e2c3d;overflow-y:auto;padding:12px}
.card{background:#111c29;border:1px solid #1e2c3d;border-radius:7px;padding:11px;margin-bottom:11px}
.card h2{font-size:11px;margin:0 0 9px;color:#6d879e;font-weight:600;letter-spacing:.6px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:9px}
.m label{display:block;font-size:10px;color:#6d879e;margin-bottom:2px}
.m b{font-size:17px;font-family:Consolas,monospace;color:#4ade80;font-weight:600}
.m.b b{color:#60a5fa}
.ctl{margin-bottom:11px}
.ctl label{display:flex;justify-content:space-between;font-size:11px;color:#8ea6bd;margin-bottom:5px}
.ctl b{color:#facc15;font-family:Consolas,monospace}
input[type=range]{width:100%;height:4px;-webkit-appearance:none;background:#22303f;border-radius:2px;outline:none}
input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:13px;height:13px;border-radius:50%;background:#38bdf8;cursor:pointer}
.sw{display:flex;align-items:center;gap:6px;font-size:11.5px;color:#8ea6bd;margin-bottom:6px;cursor:pointer}
.btnrow{display:flex;gap:7px;margin-top:9px}
button{flex:1;padding:7px;background:#1a2836;color:#cfe0f0;border:1px solid #2a3d52;border-radius:5px;cursor:pointer;font-size:11.5px}
button:hover{background:#22344a}
button.rec{background:#3a1520;border-color:#6b2130;color:#f87171}
table{width:100%;border-collapse:collapse;font-size:11px;font-family:Consolas,monospace}
th{color:#5f7891;text-align:left;font-weight:500;padding:3px 4px;border-bottom:1px solid #1e2c3d;font-size:10px}
td{padding:2.5px 4px;border-bottom:1px solid #16212e;color:#9fb6cb}
td.hi{color:#4ade80}
canvas.chart{width:100%;height:74px;display:block}
</style></head><body>
<div class="top">
  <h1>低小慢目标智能检测与跟踪系统</h1>
  <span class="badge" id="st">运行中</span>
  <span class="badge b2" id="bk">pl · 0x43C00000</span>
</div>
<div class="wrap">
  <div class="video"><div class="vbox" id="vbox">
    <img id="vs" src="/stream">
    <canvas id="ov" width="640" height="360"></canvas>
  </div></div>
  <div class="panel">
    <div class="card">
      <h2>实时指标</h2>
      <div class="grid2">
        <div class="m"><label>端到端帧率</label><b id="m_fps">--</b></div>
        <div class="m b"><label>PL 单帧</label><b id="m_pl">--</b></div>
        <div class="m"><label>采集耗时</label><b id="m_cap">--</b></div>
        <div class="m b"><label>编码耗时</label><b id="m_enc">--</b></div>
        <div class="m"><label>候选 / 稳定</label><b id="m_cand">--</b></div>
        <div class="m b"><label>端到端时延</label><b id="m_lat">--</b></div>
      </div>
    </div>
    <div class="card">
      <h2>检测参数（三档）</h2>
      <div class="ctl"><label>灵敏度 <b id="l_sens">中</b></label>
        <input type="range" id="s_sens" min="0" max="2" step="1" value="1"></div>
      <div class="ctl"><label>目标大小 <b id="l_size">自动</b></label>
        <input type="range" id="s_size" min="0" max="2" step="1" value="1"></div>
      <div class="ctl"><label>场景 <b id="l_scene">室内亮目标</b></label>
        <input type="range" id="s_scene" min="0" max="2" step="1" value="0"></div>
      <div class="btnrow"><button id="b_snap">截图保存</button></div>
      <div style="font-size:10.5px;color:#5a6f85;margin-top:8px;line-height:1.5">
        <b>绿框</b> = 已确认目标（连续 ≥2 帧都出现，稳定）　<b>红框</b> = 疑似目标（只出现 1 帧，可能是噪声，会自己消失）<br>滑条只影响网页显示，不改变板子里的 CFAR 门限。</div>
    </div>
    <div class="card">
      <h2>耗时曲线（近 60 帧）</h2>
      <canvas class="chart" id="chart" width="660" height="148"></canvas>
    </div>
    <div class="card">
      <h2>目标列表</h2>
      <table><thead><tr><th>ID</th><th>X</th><th>Y</th><th>面积</th><th>峰值</th><th>速度</th></tr></thead>
      <tbody id="tb"><tr><td colspan="6" style="color:#5a6f85">等待数据…</td></tr></tbody></table>
    </div>
  </div>
</div>
<script>
var PK=0, MAXN=64, MINH=0, ALL=false, TRAIL=true;
var hist=[];
function $(id){var e=document.getElementById(id);if(e)return e;return {value:'0',checked:false,textContent:'',innerHTML:'',style:{},addEventListener:function(){},appendChild:function(){}};}
['s_pk','s_n','s_h'].forEach(function(id){
  $(id).addEventListener('input',function(){
    PK=+0; MAXN=+64; MINH=+0;
          draw();
  });
});
$('c_all').addEventListener('change',function(){ALL=this.checked;draw()});
$('c_tr').addEventListener('change',function(){TRAIL=this.checked;draw()});
$('c_inv').addEventListener('change',function(){
  fetch('/set?invert='+(this.checked?1:0)).catch(function(){});
});
$('b_snap').addEventListener('click',function(){
  var a=document.createElement('a'); a.href='/snap?q=95';
  a.download='snap_'+Date.now()+'.jpg'; a.click();
});
var last=[];
function filt(cs){
  var out=cs.filter(function(c){ return ALL || (c.peak||0)>=PK; });
  out=out.filter(function(c){ return (c.hits||0)>=MINH; });
  out.sort(function(a,b){return (b.peak||0)-(a.peak||0)});
  return out.slice(0,MAXN);
}
function draw(){
  var cv=$('ov'), g=cv.getContext('2d');
  g.clearRect(0,0,cv.width,cv.height);
  var sel=filt(last);
  g.lineWidth=2; g.font='11px Consolas'; g.textBaseline='bottom';
  sel.forEach(function(c){
    var a=Math.max(c.area||4,1), d=Math.max(3,Math.round(2*Math.sqrt(a/Math.PI))*2);
    var x=c.x-d/2, y=c.y-d/2;
    var isTrk=(c.hits||0)>=2;                       // 连续 >=2 帧 = 已确认轨迹
    g.strokeStyle=isTrk?'#22e06a':'#ff5a4d';        // 绿=确认目标，红=疑似
    g.strokeRect(x,y,d,d);
    if(isTrk){
      g.fillStyle='#22e06a';
      g.fillText(Math.round(d)+'px', x, y-2);       // 只标尺寸，不标 ID（避免数字刷屏）
    }
  });
  return sel;
}
function chart(){
  var cv=$('chart'), g=cv.getContext('2d');
  var w=cv.width,h=cv.height; g.clearRect(0,0,w,h);
  if(hist.length<2) return;
  var mx=Math.max.apply(null,hist)*1.15||1;
  g.strokeStyle='#38bdf8'; g.lineWidth=1.5; g.beginPath();
  hist.forEach(function(v,i){
    var x=i/(hist.length-1)*w, y=h-4-(v/mx)*(h-12);
    i?g.lineTo(x,y):g.moveTo(x,y);
  });
  g.stroke();
  g.fillStyle='#5f7891'; g.font='10px Consolas';
  g.fillText(mx.toFixed(1)+' ms', 4, 11);
}
setInterval(function(){
  fetch('/info').then(function(r){return r.json()}).then(function(j){
    var cs=j.cands||[];
    last=cs;
    $('m_fps').textContent=(j.fps||0).toFixed(1);
    $('m_pl').textContent=(j.PL_ms||0).toFixed(2)+' ms';
    $('m_cap').textContent=(j.cap_ms||0).toFixed(1)+' ms';
    $('m_enc').textContent=(j.enc_ms||0).toFixed(1)+' ms';
    $('m_cand').textContent=(j.raw||cs.length)+' / '+(j.stable||cs.length);
    $('m_lat').textContent=(j.lat_ms||0).toFixed(0)+' ms';
    var sel=draw();
    hist.push(j.PL_ms||0); if(hist.length>60) hist.shift();
    chart();
    var tb=$('tb');
    if(!sel.length){ tb.innerHTML='<tr><td colspan="6" style="color:#5a6f85">无候选通过当前筛选</td></tr>'; return; }
    tb.innerHTML=sel.map(function(c){
      var d=Math.max(3,Math.round(2*Math.sqrt(Math.max(c.area||4,1)/Math.PI))*2);
      return '<tr><td class="hi">'+c.id+'</td><td>'+c.x+'</td><td>'+c.y+'</td><td>'
        +d+'px</td><td>'+(c.peak||0)+'</td><td>'+(c.spd||0).toFixed(0)+'</td></tr>';
    }).join('');
  }).catch(function(){ $('st').textContent='连接中断'; });
}, 400);
</script>

<script>
(function(){
  var N1=["保守","中","激进"], N2=["只看小目标","自动","兼顾大目标"], N3=["室内亮目标","逆光暗目标","混合(拉伸)"];
  var a=document.getElementById('s_sens'), b=document.getElementById('s_size'), c=document.getElementById('s_scene');
  function lab(){ document.getElementById('l_sens').textContent=N1[+a.value];
                   document.getElementById('l_size').textContent=N2[+b.value];
                   document.getElementById('l_scene').textContent=N3[+c.value]; }
  function push(){ lab(); fetch('/set?sens='+a.value+'&size='+b.value+'&scene='+c.value).catch(function(){}); }
  [a,b,c].forEach(function(e){ e.addEventListener('input',lab); e.addEventListener('change',push); });
  lab();
})();
</script>
</body></html>"""



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
                # 三档滑条（与独立版同语义）：灵敏度 / 目标大小 / 场景
                if "sens" in q:
                    GAMMA = (0.12, 0.08, 0.05)[max(0, min(2, int(q["sens"])))]
                if "size" in q:
                    INFER["size"] = max(0, min(2, int(q["size"])))   # 三域无双尺度，仅记录
                if "scene" in q:
                    _sc = max(0, min(2, int(q["scene"])))
                    INVERT = 1 if _sc in (1, 2) else 0                # 1=逆光 2=混合 → 找暗目标
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
