# -*- coding: utf-8 -*-
"""web_console.py —— 检测系统可视化控制台（Web 界面，零外部依赖）

【用途】
  给作品报告提供"软件成果（界面照片）"素材，同时让演示与答辩更直观。

【界面包含】
  左：实时视频流（MJPEG）+ 检测框/航迹叠加
  右上：实时统计（fps、候选数、判别通过数、航迹数、各环节耗时）
  右中：参数在线调节（真/假阈值、候选上限、显示开关）—— 拖动即生效
  右下：目标列表（ID、位置、面积、轨迹长度）
  底：耗时曲线（Canvas 绘制，最近 60 帧）

【技术要点】
  · 纯标准库：http.server + threading，不依赖 Flask/FastAPI
  · HTML/CSS/JS 内嵌，不引用 CDN，断网也能用
  · MJPEG 推流 + JSON API 轮询，浏览器只需开一个页面
  · 截图按钮直接存 JPEG；录像按钮存 MP4（cv2.VideoWriter）

【接口】
  GET  /                 控制台页面
  GET  /stream           MJPEG 视频流
  GET  /api/stats        JSON：fps / 候选数 / 耗时 / 航迹
  GET  /api/config       读取当前参数
  POST /api/config       修改参数（JSON body）
  GET  /snapshot         当前帧 JPEG（下载）
  POST /api/record       开始/停止录像

【用法】
  # PC 验证（合成帧 + 假判别器，不需要板子和模型）
  python ps/web_console.py --src test --judge dummy

  # 板上：真判别 + 摄像头
  python3 ps/web_console.py --src /dev/video1 --judge grid --grid 8 --cell 64 \
      --json deploy/grid64/grid64_drone_ZG.json --raw deploy/grid64/grid64_drone_ZG.raw

  浏览器打开 http://<板子IP>:8080
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import cv2

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "ps"))

from stream_cascade import (                       # noqa: E402
    W, H, Grabber, FakeGrabber, DualDetector, Tracker,
)
from stream_cascade_cls import (                   # noqa: E402
    DummyJudge, GridJudge, Cls128Judge, build_canvas, crop_patch,
)

PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>低小慢目标检测与跟踪系统 · 控制台</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
    background: #0e1116; color: #d7dde5; height: 100vh; overflow: hidden;
  }
  .topbar {
    height: 52px; display: flex; align-items: center; padding: 0 18px;
    background: linear-gradient(90deg, #141a22 0%, #1a2230 100%);
    border-bottom: 1px solid #26303d;
  }
  .topbar h1 { font-size: 16px; font-weight: 600; letter-spacing: .5px; }
  .topbar h1 span { color: #4ea1ff; }
  .badge {
    margin-left: 14px; font-size: 12px; padding: 3px 9px; border-radius: 10px;
    background: #1b2a3a; color: #6fb3ff; border: 1px solid #2a4a6a;
  }
  .badge.live { background: #12301c; color: #4ade80; border-color: #1e5c34; }
  .layout { display: flex; height: calc(100vh - 52px); }
  .left { flex: 1; position: relative; background: #000; }
  .left img { width: 100%; height: 100%; object-fit: contain; display: block; }
  .left .overlay {
    position: absolute; left: 12px; bottom: 12px; font-size: 12px;
    color: #8fa3b8; background: rgba(0,0,0,.5); padding: 5px 10px; border-radius: 4px;
  }
  .right {
    width: 340px; display: flex; flex-direction: column;
    border-left: 1px solid #26303d; background: #121821;
  }
  .panel { padding: 14px 16px; border-bottom: 1px solid #1e2b3d; }
  .panel:last-child { border-bottom: none; }
  .panel h2 {
    font-size: 12px; font-weight: 600; color: #6b8299; letter-spacing: 1px;
    text-transform: uppercase; margin-bottom: 10px;
  }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 12px; }
  .stat { }
  .stat .k { font-size: 11px; color: #62788f; }
  .stat .v { font-size: 19px; font-weight: 600; color: #e6edf5; font-variant-numeric: tabular-nums; }
  .stat .v small { font-size: 11px; color: #62788f; font-weight: 400; }
  .stat .v.good { color: #4ade80; }
  .stat .v.warn { color: #fbbf24; }
  .ctl { margin-bottom: 12px; }
  .ctl label { display: flex; justify-content: space-between; font-size: 12px; color: #a8b8c8; margin-bottom: 4px; }
  .ctl label b { color: #4ea1ff; font-variant-numeric: tabular-nums; }
  input[type=range] { width: 100%; accent-color: #4ea1ff; }
  .sw { display: flex; align-items: center; gap: 8px; font-size: 12px; color: #a8b8c8; margin-bottom: 8px; cursor: pointer; }
  .sw input { accent-color: #4ea1ff; }
  .btnrow { display: flex; gap: 8px; margin-top: 10px; }
  button {
    flex: 1; padding: 8px 10px; font-size: 12px; cursor: pointer;
    background: #1b2836; color: #cfe0f0; border: 1px solid #2a3d52; border-radius: 5px;
    transition: .15s;
  }
  button:hover { background: #223449; border-color: #3a5a7e; }
  button.rec { background: #3a1414; border-color: #6a2020; color: #ff8a8a; }
  button.rec.on { background: #7a1d1d; color: #fff; }
  #targets { overflow-y: auto; flex: 1; font-size: 12px; }
  #targets table { width: 100%; border-collapse: collapse; }
  #targets th {
    text-align: left; font-weight: 500; color: #62788f; font-size: 11px;
    padding: 4px 6px; border-bottom: 1px solid #1e2b3d; position: sticky; top: 0;
    background: #121821;
  }
  #targets td { padding: 4px 6px; border-bottom: 1px solid #172030; color: #b8c8d8; font-variant-numeric: tabular-nums; }
  #targets tr:hover td { background: #172030; }
  .dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: #4ade80; margin-right: 5px; }
  canvas { width: 100%; height: 64px; display: block; }
</style>
</head>
<body>
<div class="topbar">
  <h1>低小慢目标智能检测与跟踪系统 <span>·</span> 实时控制台</h1>
  <span class="badge live" id="modeBadge">运行中</span>
  <span class="badge" id="backendBadge">--</span>
</div>

<div class="layout">
  <div class="left">
    <img id="video" src="/stream" alt="视频流">
    <div class="overlay" id="overlay">等待首帧…</div>
  </div>

  <div class="right">
    <div class="panel">
      <h2>实时指标</h2>
      <div class="grid2">
        <div class="stat"><div class="k">端到端帧率</div><div class="v" id="s_fps">-- <small>fps</small></div></div>
        <div class="stat"><div class="k">单帧总耗时</div><div class="v" id="s_total">-- <small>ms</small></div></div>
        <div class="stat"><div class="k">候选数</div><div class="v" id="s_cand">--</div></div>
        <div class="stat"><div class="k">判别通过</div><div class="v" id="s_pass">--</div></div>
        <div class="stat"><div class="k">确认航迹</div><div class="v good" id="s_trk">--</div></div>
        <div class="stat"><div class="k">处理耗时</div><div class="v" id="s_det">-- <small>ms</small></div></div>
      </div>
    </div>

    <div class="panel">
      <h2>参数调节</h2>
      <div class="ctl">
        <label>视图模式</label>
        <select id="view" style="width:100%;padding:6px;background:#1b2836;color:#cfe0f0;border:1px solid #2a3d52;border-radius:4px;font-size:12px">
          <option value="raw">原始灰度（PL 候选叠加）</option>
        </select>
        <div style="font-size:11px;color:#5a6f85;margin-top:6px;line-height:1.45">
          增强图 / CFAR 二值图需要 PL 直接输出（当前 RTL 未提供），<br>
          用软件复现会与硬件结果不一致，故不提供。
        </div>
      </div>
      <div class="ctl">
        <label>真/假阈值 <b id="l_thr">0.50</b></label>
        <input type="range" id="thr" min="0.1" max="0.95" step="0.05" value="0.5">
      </div>
      <div class="ctl">
        <label>候选上限 <b id="l_cands">64</b></label>
        <input type="range" id="cands" min="4" max="64" step="4" value="64">
      </div>
      <label class="sw"><input type="checkbox" id="show_cand" checked> 显示全部候选</label>
      <label class="sw"><input type="checkbox" id="show_trail" checked> 显示运动轨迹</label>
      <div class="btnrow">
        <button id="btn_snap">截图保存</button>
        <button id="btn_rec" class="rec">开始录像</button>
      </div>
      <div class="btnrow">
        <button id="btn_csv">导出 CSV</button>
        <button id="btn_clear">清空记录</button>
      </div>
      <div style="font-size:11px;color:#5a6f85;margin-top:8px;line-height:1.5">
        所有数字均来自 PL 硬件寄存器（候选表 / STATUS / 计时），<br>
        未经软件复现，可逐项追溯。
      </div>
    </div>

    <div class="panel" style="padding-bottom:6px">
      <h2>耗时曲线（近 60 帧）</h2>
      <canvas id="chart" width="620" height="128"></canvas>
    </div>

    <div class="panel" id="targets" style="flex:1">
      <h2>目标列表</h2>
      <table>
        <thead><tr><th>ID</th><th>X</th><th>Y</th><th>面积</th><th>轨迹</th></tr></thead>
        <tbody id="tbody"><tr><td colspan="5" style="color:#4a5a6a">暂无目标</td></tr></tbody>
      </table>
    </div>
  </div>
</div>

<script>
const $ = id => document.getElementById(id);
let showCand = true, showTrail = true, recording = false;
const hist = [];

// ---- 参数联动 ----
$('thr').oninput = e => { $('l_thr').textContent = (+e.target.value).toFixed(2); pushCfg(); };
$('cands').oninput = e => { $('l_cands').textContent = e.target.value; pushCfg(); };
$('show_cand').onchange = e => { showCand = e.target.checked; pushCfg(); };
$('show_trail').onchange = e => { showTrail = e.target.checked; pushCfg(); };

function pushCfg() {
  fetch('/api/config', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      thr: +$('thr').value,
      cands: +$('cands').value,
      show_cand: showCand,
      show_trail: showTrail
    })
  }).catch(()=>{});
}

// ---- 统计轮询 ----
async function poll() {
  try {
    const r = await fetch('/api/stats');
    const s = await r.json();
    $('s_fps').innerHTML = s.fps.toFixed(1) + ' <small>fps</small>';
    $('s_total').innerHTML = s.total_ms.toFixed(1) + ' <small>ms</small>';
    $('s_cand').textContent = s.cand;
    $('s_pass').textContent = s.pass;
    $('s_trk').textContent = s.trk;
    $('s_det').innerHTML = s.det_ms.toFixed(1) + ' <small>ms</small>';
    $('backendBadge').textContent = s.backend + ' · ' + s.grid_info;
    $('overlay').textContent = s.frame_w + '×' + s.frame_h + '  ' + s.fps.toFixed(1) + ' fps';

    hist.push(s.total_ms);
    if (hist.length > 60) hist.shift();
    drawChart();

    const tb = $('tbody');
    if (s.targets && s.targets.length) {
      tb.innerHTML = s.targets.map(t =>
        `<tr><td><span class="dot"></span>${t.id}</td><td>${t.x}</td><td>${t.y}</td><td>${t.area}</td><td>${t.trail}</td></tr>`
      ).join('');
    } else {
      tb.innerHTML = '<tr><td colspan="5" style="color:#4a5a6a">暂无目标</td></tr>';
    }
  } catch(e) {}
  setTimeout(poll, 400);
}

// ---- 耗时曲线 ----
function drawChart() {
  const c = $('chart'), ctx = c.getContext('2d');
  const w = c.width, h = c.height;
  ctx.clearRect(0, 0, w, h);
  if (hist.length < 2) return;
  const mx = Math.max(...hist, 20);
  // 网格
  ctx.strokeStyle = '#1e2b3d'; ctx.lineWidth = 1;
  for (let i = 0; i <= 3; i++) {
    const y = h * i / 3;
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
  }
  // 曲线
  const step = w / (hist.length - 1);
  ctx.beginPath();
  hist.forEach((v, i) => {
    const x = i * step, y = h - (v / mx) * (h - 6) - 3;
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  });
  ctx.strokeStyle = '#4ea1ff'; ctx.lineWidth = 1.6; ctx.stroke();
  // 填充
  ctx.lineTo(w, h); ctx.lineTo(0, h); ctx.closePath();
  ctx.fillStyle = 'rgba(78,161,255,.10)'; ctx.fill();
  // 标注
  ctx.fillStyle = '#62788f'; ctx.font = '10px sans-serif';
  ctx.fillText('峰值 ' + mx.toFixed(1) + ' ms', 4, 12);
}

// ---- 截图 ----
$('btn_snap').onclick = () => {
  const a = document.createElement('a');
  a.href = '/snapshot?t=' + Date.now();
  a.download = 'snapshot_' + new Date().toISOString().replace(/[:.]/g,'-') + '.jpg';
  a.click();
};

// ---- 录像 ----
$('btn_rec').onclick = async () => {
  const r = await fetch('/api/record', { method: 'POST' });
  const s = await r.json();
  recording = s.recording;
  const b = $('btn_rec');
  b.textContent = recording ? '停止录像' : '开始录像';
  b.classList.toggle('on', recording);
};

// ---- 视图切换 ----
$('view').onchange = e => {
  fetch('/api/view', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ view: e.target.value })
  }).catch(()=>{});
};

// ---- CSV 导出 ----
$('btn_csv').onclick = () => {
  const a = document.createElement('a');
  a.href = '/api/export?t=' + Date.now();
  a.download = 'targets.csv';
  a.click();
};
$('btn_clear').onclick = () => {
  fetch('/api/csv_clear', { method: 'POST' }).catch(()=>{});
};

poll();
</script>
</body>
</html>
"""


# ============================================================ PL 后端（读 P 的候选表）

class PlDetector(object):
    """PL 检测器：写帧到 udmabuf → 触发 PL → 读 AXI-Lite 候选表镜像。

    接口与 DualDetector 兼容（`__call__(gray) -> [{'x','y','area','peak'}, ...]`），
    所以主循环可在 PS 粗筛与 PL 检测之间无缝切换。

    寄存器布局（权威依据：docs/23-寄存器映射与候选表窗口.md，与 ps/cand_read.py 一致）：
      基址 0x43C00000，挂 PS 的 M_AXI_GP0
      0x00 CTRL        bit0 = start
      0x04 FRAME_ADDR  帧在 udmabuf 的物理地址（默认 0x30100000）
      0x08 RESULT_ADDR 结果区地址
      0x0C STATUS      bit1/bit2 = done，[15:8] = 候选数
      0x14 VERSION     期望 0x00010000
      0x10 候选表窗口  写 = 设字索引(0~112)，读 = 取该字数据（**同址**！）
                      113 字 = 452 字节 = 1 + 64×7，装 64 个候选
      0x18~0x38        legacy 兼容视图（9 字 = 36 字节 = 前 5 个候选）
                      老构建（6 位地址、无窗口）只能读这里

    候选表字节布局（每候选 7 字节，大端）：
      byte 0        : n_cand
      每候选 7 字节 : x_hi x_lo  y_hi y_lo  area_hi area_lo  peak
                      ↑ x/y 16 位          ↑ area **16 位**（2026-10-29 起，原 8 位）

    ⚠️ 0x40 不能用：6 位 s_axi 地址下 0x40 绕回 0x00 = 误触发一帧。

    注意：这是"检测器"而非"判别器"——它直接给出候选坐标，不需要 PS 再跑粗筛。
    """

    def __init__(self, base=0x43C00000, udma="/dev/udmabuf0",
                 w=W, h=H, max_cand=64, timeout_ms=3000):
        self.base = base
        self.udma = udma
        self.w, self.h = w, h
        self.npix = w * h
        self.max_cand = max_cand
        self.timeout_ms = timeout_ms
        self._reg = None
        self._mem = None
        self._fds = []
        self._view = "window"        # open() 里判定，判定过程不写任何寄存器

    # ---- 寄存器偏移 ----
    R_CTRL, R_FADDR, R_RADDR, R_STATUS = 0x00, 0x04, 0x08, 0x0C
    R_VER = 0x14
    R_CIDX = 0x10            # 写：设字索引
    R_CDAT = 0x10            # 读：取该字数据（同址）
    LEG_BASE = 0x18          # legacy 兼容视图起点
    N_WIN_WORDS = (1 + 64 * 7 + 3) // 4      # 113 字 = 452 字节
    N_LEG_WORDS = 9                          # 36 字节 = 5 个候选

    def open(self):
        import mmap as MM
        import struct
        if not os.path.exists(self.udma):
            raise RuntimeError("%s 不存在（这需要在板上运行，且 u_dma_buf 已加载）" % self.udma)
        if not os.path.exists("/dev/mem"):
            raise RuntimeError("/dev/mem 不存在（需要 root 且 CONFIG_DEVMEM）")

        fd_u = os.open(self.udma, os.O_RDWR | os.O_SYNC)
        self._fds.append(fd_u)
        size = self.npix if os.path.getsize(self.udma) < self.npix else self.npix
        self._mem = MM.mmap(fd_u, size, MM.MAP_SHARED,
                            prot=MM.PROT_READ | MM.PROT_WRITE)

        fd_r = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
        self._fds.append(fd_r)
        self._reg = MM.mmap(fd_r, 0x1000, MM.MAP_SHARED, offset=self.base)

        ver = self._rd(self.R_VER)
        if ver != 0x00010000:
            self.close()
            raise RuntimeError(
                "PL VERSION=0x%08X（期望 0x00010000）\n"
                "  · 位流没加载？跑 python3 ps/probe_addr.py 0x43C00000 先确认\n"
                "  · 基址不是 0x43C00000？" % ver)

        # 视图判定：先写索引 0，再比较窗口 0 号字与 legacy[0]。
        # 注意 1：索引寄存器可能被之前的操作改成非 0，直接读会误判成 legacy
        #        （实测：索引非 0 时 rd(0x10)=0，而 legacy[0]=候选表头）。
        # 注意 2：这个写操作在老构建上会把 0x10（当时的 FRAME_ID）清零，
        #        但 FRAME_ID 只用于调试显示，不影响检测功能，故可接受。
        try:
            self._wr(self.R_CIDX, 0)
            self._view = "window" if self._rd(self.R_CDAT) == self._rd(self.LEG_BASE) else "legacy"
        except Exception:
            self._view = "legacy"
        return ver

    def _rd(self, off):
        import struct
        return struct.unpack_from("<I", self._reg, off)[0]

    def _wr(self, off, val):
        import struct
        struct.pack_into("<I", self._reg, off, val & 0xFFFFFFFF)

    def _sync(self, name="sync_for_device"):
        """udmabuf 的 cache 同步（P 实测：不做会读到旧帧）"""
        p = "/sys/class/u-dma-buf/%s/%s" % (os.path.basename(self.udma), name)
        try:
            with open(p, "w") as f:
                f.write("1")
        except Exception:
            pass

    def __call__(self, gray):
        """写一帧 → 触发 → 等完成 → 读候选表"""
        if gray.shape[1] != self.w or gray.shape[0] != self.h:
            gray = cv2.resize(gray, (self.w, self.h), interpolation=cv2.INTER_AREA)
        self._mem[0:self.npix] = gray.astype(np.uint8).tobytes()
        self._sync()
        self._wr(self.R_CTRL, 1)

        t0 = time.time()
        while (time.time() - t0) * 1000 < self.timeout_ms:
            st = self._rd(self.R_STATUS)
            if st & 0x06:            # bit1 / bit2 = done
                break
            time.sleep(0.001)

        # 读候选表：window 视图走 0x10 索引窗口（113 字 / 64 候选），
        #             legacy 视图退化为 0x18 起 9 字（36 字节 / 5 候选）
        import struct as _st
        if self._view == "window":
            raw = bytearray()
            for i in range(self.N_WIN_WORDS):
                self._wr(self.R_CIDX, i)          # 设索引
                raw += self._rd(self.R_CDAT).to_bytes(4, "little")   # 取数据（同址）
            maxn = 64
        else:
            raw = bytearray()
            for i in range(self.N_LEG_WORDS):
                raw += self._rd(self.LEG_BASE + 4 * i).to_bytes(4, "little")
            maxn = 5

        n = raw[0]
        out = []
        for i in range(min(n, self.max_cand, maxn)):
            b = raw[1 + i * 7: 8 + i * 7]
            if len(b) < 7:
                break
            out.append({"x": (b[0] << 8) | b[1],
                        "y": (b[2] << 8) | b[3],
                        "area": ((b[4] << 8) | b[5]) or 1,   # 16 位大端（原为 b[5] 8 位）
                        "peak": int(b[6])})
        return out

    def close(self):
        for obj, name in ((self._reg, "reg"), (self._mem, "mem")):
            if obj is not None:
                try:
                    obj.close()
                except Exception:
                    pass
        self._reg = self._mem = None
        for fd in self._fds:
            try:
                os.close(fd)
            except Exception:
                pass
        self._fds = []


# ============================================================ 共享状态

class State(object):
    """主循环与 HTTP 线程共享的状态"""

    def __init__(self):
        self.lock = threading.Lock()
        self.frame = None            # 最新带叠加的 BGR 帧
        self.raw = None              # 最新原始灰度帧（截图用）
        self.stats = {
            "fps": 0.0, "total_ms": 0.0, "det_ms": 0.0,
            "cand": 0, "pass": 0, "trk": 0,
            "frame_w": W, "frame_h": H,
            "backend": "sim", "grid_info": "",
            "targets": [],
        }
        self.cfg = {"thr": 0.5, "cands": 64, "show_cand": True, "show_trail": True}
        self.recording = False
        self._writer = None
        # 新增：中间结果视图与 CSV 导出
        self.view = "raw"            # raw | tophat | binary
        self.csv_rows = []           # [(帧号, ms, ID, X, Y, 面积)]
        self.frame_no = 0
        self.csv_max = 5000          # 环形上限，避免内存无限增长

    def set_frame(self, bgr, gray):
        with self.lock:
            self.frame = bgr
            self.raw = gray

    def get_frame(self):
        with self.lock:
            return None if self.frame is None else self.frame.copy()

    def get_raw(self):
        with self.lock:
            return None if self.raw is None else self.raw.copy()

    def update_stats(self, **kw):
        with self.lock:
            self.stats.update(kw)

    def get_stats(self):
        with self.lock:
            return dict(self.stats)

    def get_cfg(self):
        with self.lock:
            return dict(self.cfg)

    def set_cfg(self, d):
        with self.lock:
            for k in ("thr", "cands", "show_cand", "show_trail"):
                if k in d:
                    self.cfg[k] = d[k]
            return dict(self.cfg)


STATE = State()


# ============================================================ HTTP

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]

        if path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", PAGE.encode("utf-8"))
            return

        if path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type",
                             "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            while True:
                fr = STATE.get_frame()
                if fr is not None:
                    ok, buf = cv2.imencode(".jpg", fr, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
                    if ok:
                        try:
                            self.wfile.write(b"--frame\r\n")
                            self.wfile.write(b"Content-Type: image/jpeg\r\n")
                            self.wfile.write(("Content-Length: %d\r\n\r\n" % len(buf)).encode())
                            self.wfile.write(buf.tobytes())
                            self.wfile.write(b"\r\n")
                        except (BrokenPipeError, ConnectionResetError):
                            break
                time.sleep(0.03)
            return

        if path == "/api/stats":
            self._send(200, "application/json",
                       json.dumps(STATE.get_stats()).encode("utf-8"))
            return

        if path == "/api/config":
            self._send(200, "application/json",
                       json.dumps(STATE.get_cfg()).encode("utf-8"))
            return

        if path == "/api/export":
            with STATE.lock:
                rows = list(STATE.csv_rows)
            lines = ["帧号,时间ms,目标ID,X,Y,面积"]
            for r in rows:
                lines.append("%d,%.1f,%d,%d,%d,%d" % r)
            body = ("\ufeff" + "\r\n".join(lines)).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition",
                             'attachment; filename="targets_%s.csv"'
                             % time.strftime("%Y%m%d_%H%M%S"))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/snapshot":
            fr = STATE.get_frame()
            if fr is None:
                self._send(503, "text/plain", b"no frame")
                return
            ok, buf = cv2.imencode(".jpg", fr, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
            if not ok:
                self._send(500, "text/plain", b"encode failed")
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Disposition",
                             'attachment; filename="snapshot.jpg"')
            self.send_header("Content-Length", str(len(buf)))
            self.end_headers()
            self.wfile.write(buf.tobytes())
            return

        self._send(404, "text/plain", b"not found")

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n) if n else b""

        if self.path == "/api/config":
            try:
                d = json.loads(body or b"{}")
            except Exception:
                d = {}
            cfg = STATE.set_cfg(d)
            self._send(200, "application/json", json.dumps(cfg).encode("utf-8"))
            return

        if self.path == "/api/record":
            STATE.recording = not STATE.recording
            self._send(200, "application/json",
                       json.dumps({"recording": STATE.recording}).encode("utf-8"))
            return

        if self.path == "/api/view":
            try:
                d = json.loads(body or b"{}")
            except Exception:
                d = {}
            v = d.get("view", "raw")
            if v not in ("raw",):        # 只保留 raw（见 draw_overlay 说明）
                v = "raw"
            with STATE.lock:
                STATE.view = v
            self._send(200, "application/json",
                       json.dumps({"view": v}).encode("utf-8"))
            return

        if self.path == "/api/csv_clear":
            with STATE.lock:
                STATE.csv_rows = []
            self._send(200, "application/json", b'{"ok":true}')
            return

        self._send(404, "text/plain", b"not found")


# ============================================================ 主循环

def draw_overlay(gray, cands, confirmed, cfg, backend_name, view="raw"):
    """生成显示帧。

    ⚠️ 2026-10-30 起只保留 raw 视图。
    原先的 tophat / binary 视图是用 Python 侧 cv2 复现的，参数与 PL 的 RTL 不一致
    （5×5 方核 vs SE=21、Top-Hat vs Black-Hat、k=4.0 vs K=1.0、BORDER_REFLECT vs
    因果窗口），画出来的"增强图"和 FPGA 实际看到的东西对不上，作为演示会误导。
    要展示算法内部，应当由 PL 直接输出增强图（需改 RTL），不是在这里复现。
    """
    bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    thr = cfg.get("thr", 0.5)

    if cfg.get("show_cand", True):
        for c in cands:
            if "p" in c and c["p"] > thr:
                color = (80, 220, 80)
            elif "p" in c:
                color = (60, 60, 190)
            else:
                color = (60, 160, 220)
            a = max(c.get("area", 4), 1)
            d = max(2, int(2 * (a / 3.14159) ** 0.5))
            x, y = int(c["x"]), int(c["y"])
            cv2.rectangle(bgr, (x - d, y - d), (x + d, y + d), color, 1)

    if cfg.get("show_trail", True):
        for t in confirmed:
            pts = [tuple(map(int, p)) for p in t.trail]
            for k in range(1, len(pts)):
                cv2.line(bgr, pts[k - 1], pts[k], (0, 190, 0), 1)

    for t in confirmed:
        x, y = int(t.trail[-1][0]), int(t.trail[-1][1])
        cv2.circle(bgr, (x, y), 11, (80, 240, 80), 1)
        cv2.putText(bgr, "ID %d" % t.id, (x + 13, y - 7),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (80, 240, 80), 1)

    cv2.putText(bgr, backend_name, (8, 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.48, (200, 220, 255), 1)
    return bgr


def main():
    ap = argparse.ArgumentParser(description="检测系统 Web 控制台")
    ap.add_argument("--backend", default="sim", choices=["sim", "pl"],
                    help="sim=PS 粗筛（PC 可跑）；pl=读 PL 候选表（需板上位流）")
    ap.add_argument("--src", default="test")
    ap.add_argument("--judge", default="dummy", choices=["dummy", "grid", "cls128"])
    ap.add_argument("--grid", type=int, default=8, choices=[4, 8])
    ap.add_argument("--cell", type=int, default=64, choices=[64, 128])
    ap.add_argument("--cands", type=int, default=0)
    ap.add_argument("--json", default="deploy/grid64/grid64_drone_ZG.json")
    ap.add_argument("--raw", default="deploy/grid64/grid64_drone_ZG.raw")
    ap.add_argument("--port", type=int, default=8081)
    ap.add_argument("--topk", type=int, default=64)
    ap.add_argument("--confirm", type=int, default=3)
    ap.add_argument("--reg-base", default="0x43C00000",
                    help="PL 寄存器基址（--backend pl 用）")
    a = ap.parse_args()

    # ---- 后端选择 ----
    pl_det = None
    if a.backend == "pl":
        # PL 后端：检测在 PL 里做，无 NPU 判别（P 的位流不含 AI-Mate）
        pl_det = PlDetector(base=int(a.reg_base, 16))
        try:
            ver = pl_det.open()
        except Exception as e:
            print("  ✗ PL 后端初始化失败：%s" % e)
            print("    提示：--backend pl 必须在板上运行，且位流已加载")
            return 1
        print("  ✓ PL VERSION = 0x%08X（基址 %s）" % (ver, a.reg_base))
        print("  ✓ 候选视图 = %s（%s）" % (
            pl_det._view,
            "113 字窗口 / 最多 64 个候选" if pl_det._view == "window"
            else "0x18 兼容视图 / 最多 5 个候选（老构建）"))
        judge = DummyJudge(a.grid, a.cell)   # 占位：PL 后端不做 NPU 判别
        judge.open()
        n_cand = 64 if pl_det._view == "window" else 5   # 按视图动态定
        grid_info = "PL@%s" % a.reg_base
        backend_name = "pl"
    else:
        n_cand = a.cands or (a.grid * a.grid if a.judge in ("grid", "dummy") else 8)
        grid_info = "%d×%d@%d" % (a.grid, a.grid, a.cell) if a.judge != "cls128" else "逐个判"
        backend_name = a.judge

        # ---- 判别器 ----
        if a.judge == "dummy":
            judge = DummyJudge(a.grid, a.cell)
            judge.open()
        elif a.judge == "grid":
            judge = GridJudge(a.json, a.raw, a.grid, a.cell)
            try:
                judge.open()
            except Exception as e:
                print("  ✗ 模型加载失败：%s" % e)
                return 1
        else:
            judge = Cls128Judge(a.json, a.raw, a.cell)
            try:
                judge.open()
            except Exception as e:
                print("  ✗ 模型加载失败：%s" % e)
                return 1

    # ---- 采集 ----
    # 注意：Grabber 默认 size=(1280,720)，但 PL 与显示都只用 640×360。
    # 不显式指定会让 ffmpeg 输出 4 倍像素、编码慢 4 倍（实测 fps 3.7 → 指定后 ~20）。
    grab = FakeGrabber() if a.src == "test" else Grabber(a.src, size=(W, H), gray=True)
    grab.start()
    for _ in range(200):
        if grab.latest() is not None:
            break
        time.sleep(0.05)
    if grab.latest() is None:
        print("  ✗ 取不到帧")
        return 1

    det = pl_det if pl_det is not None else DualDetector(topk=a.topk)
    tracker = Tracker(confirm=a.confirm)

    STATE.update_stats(backend=backend_name, grid_info=grid_info)
    STATE.set_cfg({"cands": n_cand})

    srv = ThreadingHTTPServer(("0.0.0.0", a.port), Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print("  ✓ 控制台: http://<IP>:%d/" % a.port)
    print("  backend=%s  grid=%s  src=%s" % (a.judge, grid_info, a.src))

    fps_t, fps_n = time.time(), 0
    fps = 0.0
    t_sum = 0.0
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

            cfg = STATE.get_cfg()
            thr = float(cfg.get("thr", 0.5))
            n_use = int(cfg.get("cands", n_cand))

            t0 = time.time()
            cs = det(gray)[:n_use]

            if a.backend == "pl":
                # PL 后端：候选直接来自 PL，无 NPU 判别（P 的位流不含 AI-Mate）
                # 用 peak 归一化当"置信度"仅用于着色，不做过滤
                probs = [min(1.0, c.get("peak", 255) / 255.0) for c in cs]
                pts = list(cs)
            elif a.judge == "cls128":
                pts, probs = [], []
                for c in cs:
                    p = judge.judge_one(crop_patch(gray, c["x"], c["y"], a.cell))
                    probs.append(p)
                    if p > thr:
                        pts.append(c)
            else:
                canvas, _ = build_canvas(gray, cs, a.grid, a.cell)
                probs = judge.judge_grid(canvas)
                pts = [cs[i] for i in range(min(len(cs), len(probs))) if probs[i] > thr]

            for i, c in enumerate(cs):
                c["p"] = probs[i] if i < len(probs) else 0.0

            det_ms = (time.time() - t0) * 1000
            confirmed = tracker.step([(c["x"], c["y"], c.get("area", 4)) for c in pts])

            with STATE.lock:
                view = STATE.view
            bgr = draw_overlay(gray, cs, confirmed, cfg, backend_name, view)
            STATE.set_frame(bgr, gray)

            # 记录目标轨迹到 CSV 缓冲（供 /api/export 下载）
            with STATE.lock:
                STATE.frame_no += 1
                fn = STATE.frame_no
                for t in confirmed:
                    STATE.csv_rows.append(
                        (fn, det_ms, t.id,
                         int(t.trail[-1][0]), int(t.trail[-1][1]),
                         len(t.trail)))
                if len(STATE.csv_rows) > STATE.csv_max:
                    STATE.csv_rows = STATE.csv_rows[-STATE.csv_max:]

            # 统计
            fps_n += 1
            now = time.time()
            if now - fps_t >= 0.5:
                fps = fps_n / (now - fps_t)
                fps_n, fps_t = 0, now
            t_sum = t_sum * 0.9 + det_ms * 0.1

            STATE.update_stats(
                fps=fps, det_ms=det_ms, total_ms=det_ms,
                cand=len(cs), trk=len(confirmed),
                frame_w=gray.shape[1], frame_h=gray.shape[0],
                targets=[{"id": t.id,
                          "x": int(t.trail[-1][0]), "y": int(t.trail[-1][1]),
                          "area": int(t.trail.__len__()),
                          "trail": len(t.trail)} for t in confirmed])
            STATE.stats["pass"] = len(pts)

            # 录像
            if STATE.recording:
                if STATE._writer is None:
                    fp = os.path.join(REPO, "results",
                                      "rec_%s.mp4" % time.strftime("%Y%m%d_%H%M%S"))
                    os.makedirs(os.path.dirname(fp), exist_ok=True)
                    STATE._writer = cv2.VideoWriter(
                        fp, cv2.VideoWriter_fourcc(*"mp4v"), 20,
                        (bgr.shape[1], bgr.shape[0]))
                    print("  ● 录像开始: %s" % fp)
                STATE._writer.write(bgr)
            elif STATE._writer is not None:
                STATE._writer.release()
                STATE._writer = None
                print("  ■ 录像结束")
    except KeyboardInterrupt:
        print("\n  停止")
    finally:
        grab.stop()
        judge.close()
        if pl_det is not None:
            pl_det.close()
        if STATE._writer is not None:
            STATE._writer.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
