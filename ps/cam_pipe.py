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
import subprocess
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
R_LEG = 0x18              # 兼容视图：0x18~0x38 共 9 个字 = 36 字节候选表（S 的 web_console 也这么读）
R_CIDX = 0x10             # 写：窗口字索引（0..112）
R_CDAT = 0x10             # 读：该字（全 452 字节 = 64 个候选）
R_HAND = 0x3C             # 读：状态字镜像
R_STMIRROR = 0x3C
MAX_CAND = 64
TAB_WORDS = (1 + MAX_CAND * 7 + 3) // 4   # 113 个字

g_lock = threading.Lock()
g_jpeg = None
g_info = {}
g_stop = False
MOTION_FRAC = 0.0     # 时域差分：变化像素占比门限（0=关闭），由 --motion-frac 设置
MOTION_THR = 8        # 时域差分：逐像素变化门限
MULTI_SCALE = 0       # 1=开启多尺度
MS_FACTOR = 3         # 第二遍降采样倍数（3 => 覆盖约 4~60px）
MS_FACTOR2 = 4        # 第三遍倍数（4 => 补 20~80px）
MS_EVERY = 1          # 多尺度第二/三遍每 N 帧做一次（2 => 隔帧，省一半 PL 时间）
MS_CNT = 0            # 帧计数
CLUSTER_R = 12        # 候选聚类半径（像素）：相距小于它的候选合并成一个目标
NMS_IOU = 0.30        # 框去重阈值：交叠/较小框面积 超过它就合并（0.45->0.30，压掉同一目标的重合框）
LAG_FRAMES = 0.0      # 速度外推帧数（补偿端到端时延；0=不外推）
STREAM_Q = 88         # 推流 JPEG 质量（彩色呈现要清晰些）
GRAY_STREAM = 0       # 1=推灰度 JPEG（快）；0=推彩色（呈现彩色，处理仍全程灰度）

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
      <h2>参数调节（前端筛选，不改硬件门限）</h2>
      <div class="ctl"><label>最小峰值 <b id="l_pk">0</b></label>
        <input type="range" id="s_pk" min="0" max="255" step="5" value="0"></div>
      <div class="ctl"><label>最多显示 <b id="l_n">64</b></label>
        <input type="range" id="s_n" min="1" max="64" step="1" value="64"></div>
      <div class="ctl"><label>轨迹最短长度 <b id="l_h">0</b></label>
        <input type="range" id="s_h" min="0" max="60" step="1" value="0"></div>
      <label class="sw"><input type="checkbox" id="c_all"> 显示全部候选</label>
      <label class="sw"><input type="checkbox" id="c_tr" checked> 显示轨迹</label>
      <label class="sw"><input type="checkbox" id="c_inv" __INVCHK__> 反相检测（找暗目标：天空/逆光）</label>
      <div class="btnrow"><button id="b_snap">截图保存</button></div>
      <div style="font-size:10.5px;color:#5a6f85;margin-top:8px;line-height:1.5">
        黄色框 = PL 硬件画在流里的原始框；<span style="color:#4ade80">绿色框</span> = 通过筛选的候选。
        滑动条只影响网页叠加层，不改 PL 的 CFAR 门限（RTL 无参数寄存器）。
      </div>
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
function $(i){return document.getElementById(i)}
['s_pk','s_n','s_h'].forEach(function(id){
  $(id).addEventListener('input',function(){
    PK=+$('s_pk').value; MAXN=+$('s_n').value; MINH=+$('s_h').value;
    $('l_pk').textContent=PK; $('l_n').textContent=MAXN; $('l_h').textContent=MINH;
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
    g.strokeStyle='#4ade80'; g.strokeRect(x,y,d,d);
    if(TRAIL && c.hits){
      g.fillStyle='#4ade80';
      g.fillText('#'+c.id+' '+Math.round(d)+'px', x, y-2);
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
        # 新映射：0x18~0x38 是 36 字节兼容视图（9 个字，S 的 web_console 也这么读）；
        # 候选多于 5 个时，再走 0x40/0x44 索引窗口把 64 个全读出来
        words = [self.rd(R_LEG + 4 * i) for i in range(9)]
        raw = b"".join(struct.pack("<I", w) for w in words)
        n0 = raw[0]
        if n0 > 5:
            need = (1 + n0 * 7 + 3) // 4
            if need > TAB_WORDS:
                need = TAB_WORDS
            full = []
            for i in range(need):
                self.wr(R_CIDX, i)
                full.append(self.rd(R_CDAT))
            raw = b"".join(struct.pack("<I", w) for w in full)
        dt = (time.time() - t0) * 1000.0
        n = raw[0]
        cands = []
        for i in range(min(n, MAX_CAND)):
            b = raw[1 + i * 7: 8 + i * 7]
            if len(b) < 7:
                break
            cands.append({"x": (b[0] << 8) | b[1], "y": (b[2] << 8) | b[3],
                          "area": (b[4] << 8) | b[5], "peak": b[6]})
        return st, cands, dt

    def run_ms(self, gray):
        """多尺度：全分辨率跑一遍（2~20px），再依次把 MS_FACTOR / MS_FACTOR2 倍降采样图放进
        左上角各跑一遍（3x≈4~60px，4x≈20~80px），坐标 xN、面积 xN² 映回原尺度后按距离去重合并。"""
        global MS_CNT
        st, c1, dt = self.run(gray)
        out = list(c1)
        total = dt
        MS_CNT += 1
        do_extra = (MS_EVERY <= 1) or (MS_CNT % MS_EVERY == 0)
        for n in ((MS_FACTOR, MS_FACTOR2) if do_extra else ()):
            if n < 2:
                continue
            sw, sh = W // n, H // n
            small = cv2.resize(gray, (sw, sh), interpolation=cv2.INTER_AREA)
            canvas = np.zeros((H, W), np.uint8)
            canvas[0:sh, 0:sw] = small
            stn, cn, dtn = self.run(canvas)
            total += dtn
            for c in cn:
                mx = min(int(c["x"]) * n + 1, W - 1)
                my = min(int(c["y"]) * n + 1, H - 1)
                ma = min(int(c["area"]) * n * n, 60000)
                dup = False
                for o in out:
                    if abs(int(o["x"]) - mx) <= 10 and abs(int(o["y"]) - my) <= 10:
                        dup = True
                        break
                if not dup:
                    out.append({"x": mx, "y": my, "area": ma, "peak": c["peak"], "big": n})
        return st, out, total

def reject_lines(cands, dy=3, dx=30, need=3, band=48):
    """剔除“细长亮线”类误报（显示器上边框、窗框、桌沿）——只对画面上下边带生效。
    教训：若对所有行生效，同一行上的多个真目标（比如靶图一排方块）会被一起删掉。"""
    if len(cands) < need:
        return cands
    rows = {}
    for c in cands:
        y = int(c["y"])
        if y > band and y < H - band // 2:
            continue                      # 画面中部不做线状剔除
        rows.setdefault(y // (dy + 1), []).append(c)
    drop = set()
    for _, g in rows.items():
        if len(g) < need:
            continue
        xs = sorted(int(c["x"]) for c in g)
        if xs[-1] - xs[0] > dx:
            for c in g:
                drop.add(id(c))
    if not drop:
        return cands
    return [c for c in cands if id(c) not in drop]


def cluster_cands(cands, r=12):
    """把相距 < r 的候选合并成一个（按面积加权质心），避免同一目标出多个框。"""
    if len(cands) <= 1:
        return cands
    out = []
    for c in sorted(cands, key=lambda c: -int(c["area"])):
        cx, cy, ar = int(c["x"]), int(c["y"]), max(1, int(c["area"]))
        merged = False
        for o in out:
            if abs(o["x"] - cx) <= r and abs(o["y"] - cy) <= r:
                w = o["_w"]
                o["x"] = int((o["x"] * w + cx * ar) / (w + ar))
                o["y"] = int((o["y"] * w + cy * ar) / (w + ar))
                o["area"] = min(60000, o["area"] + ar)
                o["_w"] = w + ar
                o["peak"] = max(int(o["peak"]), int(c["peak"]))
                o["mv"] = max(float(o.get("mv", 0.0)), float(c.get("mv", 0.0)))
                merged = True
                break
        if not merged:
            d = dict(c)
            d["_w"] = ar
            out.append(d)
    for o in out:
        o.pop("_w", None)
    return out


def nms_tracks(trks, iom=0.45):
    """框去重：交叠/较小框面积 超过 iom 的视为同一个目标，保留命中多的。"""
    keep = []
    for t in sorted(trks, key=lambda t: (-t["hits"], -int(t["area"]))):
        r0 = max(4, int((int(t["area"]) ** 0.5) / 2) + 3)
        x0, y0 = int(t["x"]), int(t["y"])
        drop = False
        for k in keep:
            r1 = max(4, int((int(k["area"]) ** 0.5) / 2) + 3)
            x1, y1 = int(k["x"]), int(k["y"])
            ox = max(0, min(x0 + r0, x1 + r1) - max(x0 - r0, x1 - r1))
            oy = max(0, min(y0 + r0, y1 + r1) - max(y0 - r0, y1 - r1))
            inter = ox * oy
            a0 = (2 * r0 + 1) ** 2
            a1 = (2 * r1 + 1) ** 2
            if inter > 0 and inter / float(min(a0, a1)) > iom:
                drop = True
                break
        if not drop:
            keep.append(t)
    return keep


class Tracker(object):
    """跨帧候选跟踪 + 去抖。

    规则：
      * 同一目标在相邻帧位置差 <= MATCH_R 视为同一条 track（坐标/面积/峰值做到 EMA 平滑）
      * 连续命中 >= MIN_HITS 帧才对外显示
      * 连续丢失 > MAX_MISS 帧才移除
      * 每条 track 维护 vx/vy（像素/帧），用于在画面上标速度
    性能：候选按峰值预剪（MAX_IN），track 池上限 MAX_TRACKS，避免 O(候选×track) 爆炸。
    """

    MATCH_R = 12       # 匹配半径（像素，棋盘距离）
    MIN_HITS = 2       # 命中多少帧才显示
    MAX_MISS = 10      # 连续丢失多少帧才删除
    MAX_SHOW = 64      # 最多显示多少个
    PEAK_MIN = 0       # 候选峰值下限
    MAX_IN = 16        # 每帧最多送进跟踪的候选数（按峰值排序取前 N）
    MAX_TRACKS = 64    # track 池上限

    def __init__(self):
        self.tracks = []
        self.next_id = 1

    def update(self, cands, fps=25.0):
        # 1) 候选预剪：按 (mv, peak) 排序，只保留前 MAX_IN 个
        cs = sorted(cands, key=lambda c: (-float(c.get("mv", 0.0)), -int(c["peak"])))[:self.MAX_IN]
        nt = len(self.tracks)
        used = [False] * nt
        for c in cs:
            if int(c["peak"]) < self.PEAK_MIN:
                continue
            cx, cy = int(c["x"]), int(c["y"])
            best, bestd = -1, 10 ** 9
            for i in range(nt):
                if used[i]:
                    continue
                t = self.tracks[i]
                d = max(abs(t["x"] - cx), abs(t["y"] - cy))
                if d <= self.MATCH_R and d < bestd:
                    best, bestd = i, d
            if best >= 0:
                t = self.tracks[best]
                used[best] = True
                dx, dy = cx - t["x"], cy - t["y"]
                t["x"] = (4 * t["x"] + cx) // 5
                t["y"] = (4 * t["y"] + cy) // 5
                t["area"] = (4 * t["area"] + int(c["area"])) // 5
                t["peak"] = (4 * t["peak"] + int(c["peak"])) // 5
                t["vx"] = 0.6 * t.get("vx", 0.0) + 0.4 * dx
                t["vy"] = 0.6 * t.get("vy", 0.0) + 0.4 * dy
                t["hits"] += 1
                t["miss"] = 0
            else:
                self.tracks.append({"id": self.next_id, "x": cx, "y": cy,
                                    "area": int(c["area"]), "peak": int(c["peak"]),
                                    "vx": 0.0, "vy": 0.0,
                                    "hits": 1, "miss": 0})
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
        self.tracker = Tracker()
        self.prev_gray = None     # 时域差分用：上一帧灰度

    # ---------- 线程 A：采集 ----------
    def thread_capture(self):
        # 关键：关掉"光圈优先"，否则光线不足时驱动会把帧率降到 20fps 换长曝光，
        # 结果既掉帧又运动模糊（这是"画面糊 + 框闪"的一大来源）。强制 30fps 短曝光。
        for dev in ("/dev/video%d" % self.cam,):
            try:
                subprocess.call(["v4l2-ctl", "-d", dev, "-c", "exposure_auto_priority=0"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
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
                self.slot = (f, gray, time.time())
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
            color, gray, t_cap = item
            st, cands, dt = self.hw.run_ms(gray) if MULTI_SCALE else self.hw.run(gray)
            self.pl_ms = 0.8 * self.pl_ms + 0.2 * dt
            self.pl_n += 1
            # ---- 时域差分（借鉴帧差法）：只保留“相对上一帧有变化”的候选，静止背景直接滤掉 ----
            nmv = 0
            if self.prev_gray is not None:
                d_all = cv2.absdiff(gray, self.prev_gray)
                for c in cands:
                    cx, cy = int(c["x"]), int(c["y"])
                    r = 6
                    x0, x1 = max(0, cx - r), min(W, cx + r + 1)
                    y0, y1 = max(0, cy - r), min(H, cy + r + 1)
                    if x1 <= x0 or y1 <= y0:
                        c["mv"] = 0.0
                        continue
                    c["mv"] = round(float((d_all[y0:y1, x0:x1] > MOTION_THR).mean()), 2)
                if MOTION_FRAC > 0.0:
                    kept = [c for c in cands if c.get("mv", 0.0) >= MOTION_FRAC]
                    nmv = len(cands) - len(kept)
                    cands = kept
            self.prev_gray = gray.copy()
            cands = cluster_cands(cands, CLUSTER_R)
            _t0 = time.time()
            cands = reject_lines(cands)
            shown = nms_tracks(self.tracker.update(cands, self.pl_fps()), NMS_IOU)
            self.trk_ms = 0.8 * getattr(self, "trk_ms", 0.0) + 0.2 * (time.time() - _t0) * 1000.0
            npass = sum(1 for c in cands if int(c["peak"]) >= Tracker.PEAK_MIN)
            lat_ms = (time.time() - t_cap) * 1000.0
            self.lat_ms = 0.8 * getattr(self, "lat_ms", lat_ms) + 0.2 * lat_ms
            if GRAY_STREAM:
                disp = gray if gray.ndim == 2 else cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
            else:
                disp = color
            c_box = 255 if GRAY_STREAM else (0, 255, 0)
            c_txt = 255 if GRAY_STREAM else (0, 255, 0)
            c_hud = 255 if GRAY_STREAM else (0, 255, 255)
            for t in shown:
                # 速度外推：往前推 LAG_FRAMES 帧，抵消端到端时延，让框盖在目标身上
                x = int(t["x"] + t.get("vx", 0.0) * LAG_FRAMES)
                y = int(t["y"] + t.get("vy", 0.0) * LAG_FRAMES)
                x = max(0, min(W - 1, x))
                y = max(0, min(H - 1, y))
                r = max(5, min(24, int((t["area"] ** 0.5) / 2) + 3))
                cv2.rectangle(disp, (x - r, y - r), (x + r, y + r), c_box, 2)
                side = max(1, int(round((t["area"]) ** 0.5)))
                spd = t.get("spd", 0)
                lbl = "#%d %dpx" % (t["id"] % 100, side)
                if spd >= 8:
                    lbl += " %d/s" % spd
                if x < W - 60 and y > 10:
                    cv2.putText(disp, lbl, (x + 6, y - 6),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.45, c_txt, 1, cv2.LINE_AA)
            cv2.putText(disp, "PL %.1fms  lat %.0fms  raw %d  stable %d  cap %.1fms %d fps" %
                        (self.pl_ms, self.lat_ms, npass, len(shown), self.cap_ms, self.pl_fps()),
                        (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, c_hud, 2, cv2.LINE_AA)
            with self.paint_lock:
                self.paint = disp
            globals()["g_last_img"] = disp     # 供 /snap 按需出高清单帧
            g_info.update({"cands": shown, "raw": npass, "stable": len(shown),
                           "lat_ms": round(self.lat_ms, 1),
                           "trk_ms": round(getattr(self, "trk_ms", 0.0), 1),
                           "PL_ms": round(self.pl_ms, 2),
                           "pl_fps": round(self.pl_fps(), 1),
                           "cap_ms": round(self.cap_ms, 2), "n": len(shown)})

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
            ok, enc = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), STREAM_Q])
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
        if self.path.startswith("/set"):
            # /set?invert=0|1 —— 反相检测开关（把 255-gray 送 PL = Black-Hat，找暗目标）
            global INVERT
            try:
                if "invert=" in self.path:
                    INVERT = self.path.split("invert=")[1].split("&")[0].strip() in ("1", "true", "on")
                body = json.dumps({"invert": 1 if INVERT else 0}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
            except Exception as e:
                body = json.dumps({"err": str(e)}).encode()
                self.send_response(400)
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
        if self.path.startswith("/snap"):
            # 按需出一张单帧：/snap?q=72|80|95（默认 95），用于画质 A/B 对比
            img = globals().get("g_last_img")
            _q = 95
            try:
                if "q=" in self.path:
                    _q = max(10, min(100, int(self.path.split("q=")[1].split("&")[0])))
            except Exception:
                _q = 95
            if img is not None:
                ok, enc = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), _q])
                if ok:
                    data = enc.tobytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(data)
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
    ap.add_argument("--peak-min", type=int, default=0,
                    help="候选 peak 低于此值直接丢弃（压夜间噪点，0=不过滤）")
    ap.add_argument("--min-hits", type=int, default=Tracker.MIN_HITS,
                    help="连续命中多少帧才显示")
    ap.add_argument("--max-show", type=int, default=8, help="最多显示几个稳定框")
    ap.add_argument("--max-miss", type=int, default=Tracker.MAX_MISS,
                    help="连续丢失多少帧才删除")
    ap.add_argument("--motion-frac", type=float, default=0.0,
                    help="时域差分：候选周围 13x13 内变化像素占比低于此值则丢弃（0=关闭；建议 0.10~0.20）")
    ap.add_argument("--ms-factor", type=int, default=3, help="多尺度第二遍的降采样倍数（3 => 4~60px）")
    ap.add_argument("--ms-factor2", type=int, default=0, help="多尺度第三遍倍数（4 => 补 20~80px；0=关闭）")
    ap.add_argument("--gray", type=int, default=0, help="1=灰度推流(快) 0=彩色(默认)")
    ap.add_argument("--quality", type=int, default=88, help="推流 JPEG 质量")
    ap.add_argument("--lag", type=float, default=3.0, help="速度外推帧数（补偿时延，0=关闭）")
    ap.add_argument("--cluster-r", type=int, default=12, help="候选聚类半径（像素）")
    ap.add_argument("--nms-iou", type=float, default=0.45, help="框去重阈值")
    ap.add_argument("--ms-every", type=int, default=1, help="多尺度第二/三遍每 N 帧做一次（2=隔帧，省一半 PL 时间）")
    ap.add_argument("--multi-scale", type=int, default=0,
                    help="1=开启多尺度：额外把 2x 降采样图跑一遍，覆盖 20~40px 目标（帧率约降一半）")
    ap.add_argument("--motion-thr", type=int, default=8,
                    help="时域差分：逐像素灰度变化门限（默认 8）")
    args = ap.parse_args()

    global MOTION_FRAC, MOTION_THR, MULTI_SCALE, MS_FACTOR, MS_FACTOR2, MS_EVERY
    global LAG_FRAMES, CLUSTER_R, NMS_IOU, GRAY_STREAM
    MULTI_SCALE = args.multi_scale
    MS_FACTOR = args.ms_factor
    MS_FACTOR2 = args.ms_factor2
    MS_EVERY = args.ms_every
    LAG_FRAMES = args.lag
    GRAY_STREAM = 1 if args.gray else 0
    STREAM_Q = int(args.quality)
    CLUSTER_R = args.cluster_r
    NMS_IOU = args.nms_iou
    MOTION_FRAC = args.motion_frac
    MOTION_THR = args.motion_thr

    Tracker.MIN_HITS = args.min_hits
    Tracker.MAX_MISS = args.max_miss
    Tracker.MAX_SHOW = args.max_show
    Tracker.PEAK_MIN = args.peak_min

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
