#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""npu_judge.py —— 把「NPU 判是不是无人机」做成稳定的判定器。

要解决三个已实测的问题：
  1) 绿橙疯狂跳动：裁剪边长原来按每帧 area 反推，同一目标每帧视野不同 -> 概率翻。
     => 每条航迹第一次命中时锁定裁剪边长，之后一直用同一尺寸。
  2) 概率单帧抽风：单帧概率噪声大。
     => EMA 平滑（alpha=0.35）。
  3) 状态抖动：概率在 0.5 附近来回。
     => 双阈值迟滞（>=0.60 才置"无人机"，<=0.40 才置"非无人机"，中间保持原状态）。

用法（离线）：
    j = Judge()
    cands = j.update(npu, gray, cands, tracks=None)   # 每帧调一次
    # cands 里每项变成 (x, y, area, peak, p_smooth, is_drone)

用法（在线 cam3d_pipe）：把 cands 换成“带 id 的航迹”即可，用 tid 做键。
"""
import math

import numpy as np


class Judge(object):
    def __init__(self, side_init=48, side_min=24, side_max=128,
                 ema=0.35, hi=0.60, lo=0.40, cs_scale=1.7, min_side_from_area=True):
        self.side_init = side_init
        self.side_min = side_min
        self.side_max = side_max
        self.ema = ema
        self.hi = hi
        self.lo = lo
        self.cs_scale = cs_scale
        self.min_side_from_area = min_side_from_area
        self.mem = {}          # key -> {"side": int, "p": float, "state": bool}

    # ---------- 内部 ----------
    def _key(self, x, y, tid=None):
        if tid is not None:
            return ("t", int(tid))
        # 没给 tid 时按 32px 网格聚成一个“伪航迹”，让相邻帧的同一目标复用一个 key
        return ("g", int(x) // 32, int(y) // 32)

    def _side_for(self, area, x, y):
        if self.min_side_from_area:
            s = int(round(self.cs_scale * 2.0 * math.sqrt(max(area, 1))))
        else:
            s = self.side_init
        return max(self.side_min, min(self.side_max, s))

    # ---------- 主接口 ----------
    def update(self, npu, gray, cands, crop_fn=None):
        """cands: [(x, y, area, peak, tid?), ...]  ->  [(x, y, area, peak, p, is_drone), ...]"""
        out = []
        seen = set()
        for c in cands:
            x, y, area, peak = c[0], c[1], c[2], c[3]
            tid = c[4] if len(c) >= 5 else None
            k = self._key(x, y, tid)
            seen.add(k)
            st = self.mem.get(k)
            if st is None:
                st = {"side": self._side_for(area, x, y), "p": 0.5, "state": False,
                      "hits": 0}
                self.mem[k] = st
            else:
                # 已经稳定跟过的目标：裁剪尺寸只允许缓慢变化（避免视野跳）
                want = self._side_for(area, x, y)
                st["side"] = int(round(0.8 * st["side"] + 0.2 * want))
                st["side"] = max(self.side_min, min(self.side_max, st["side"]))
                st["hits"] += 1

            # 首次命中先用它自己的尺寸裁一次，拿到初始概率
            p_raw = None
            if npu is not None:
                try:
                    if crop_fn is not None:
                        patch = crop_fn(gray, int(x), int(y), st["side"])
                    else:
                        patch = _crop(gray, int(x), int(y), st["side"])
                    r = npu.predict(patch)
                    arr = np.ravel(np.asarray(r, dtype=np.float64))
                    p_raw = float(arr[-1])
                except Exception:
                    p_raw = None

            if p_raw is not None:
                st["p"] = (1.0 - self.ema) * st["p"] + self.ema * p_raw
            # 迟滞
            if st["p"] >= self.hi:
                st["state"] = True
            elif st["p"] <= self.lo:
                st["state"] = False

            out.append((x, y, area, peak, st["p"], st["state"]))

        # 回收 60 帧没再出现的记忆
        for k in [k for k in self.mem if k not in seen]:
            self.mem[k]["hits"] = self.mem[k].get("hits", 0) - 1
            if self.mem[k]["hits"] < -60:
                self.mem.pop(k, None)
        return out


def _crop(gray, cx, cy, side):
    """在 (cx,cy) 处裁 side×side 并缩到 128×128（灰度）。"""
    h, w = gray.shape[:2]
    r = max(4, side // 2)
    x0, x1 = max(0, cx - r), min(w, cx + r)
    y0, y1 = max(0, cy - r), min(h, cy + r)
    patch = gray[y0:y1, x0:x1]
    if patch.size == 0:
        patch = np.zeros((8, 8), np.uint8)
    import cv2
    return cv2.resize(patch, (128, 128), interpolation=cv2.INTER_AREA)
