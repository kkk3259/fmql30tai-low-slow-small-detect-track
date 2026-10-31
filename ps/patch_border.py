#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在板端给 cam_pipe.py 加“边界过滤”，去掉画面上沿/下沿/左右的常驻误报。

背景：实测发现 8 个候选全部钉在 y=0~18（相机拍到显示器上方的墙/天花板亮带），
      hits 累到 3 万多帧也不消失，看起来就是“框一直不动”。
"""
import io
import re
import sys

P = "/root/ip2/cam_pipe.py"
s = io.open(P, encoding="utf-8").read()

# 1) 全局变量
if "BORDER = " not in s:
    s = s.replace("MOTION_FRAC = 0.0", "BORDER = 24          # 边界过滤（像素）：上/下/左/右这么大的边带不参与检测\nMOTION_FRAC = 0.0", 1)

# 2) 在 hw.run 之后插入过滤
anchor = "            st, cands, dt = self.hw.run_ms(gray_pl) if MULTI_SCALE else self.hw.run(gray_pl)"
flt = anchor + """
            # 边界过滤：画面上沿是墙/天花板亮带，下沿是桌面，左右是边框，都是常驻误报
            _n0 = len(cands)
            cands = [c for c in cands
                     if int(c["y"]) >= BORDER and int(c["y"]) <= H - 8
                     and 8 <= int(c["x"]) <= W - 8]"""
if "_n0 = len(cands)" not in s:
    assert anchor in s, "anchor not found"
    s = s.replace(anchor, flt, 1)

io.open(P, "w", encoding="utf-8", newline="\n").write(s)
print("PATCH_OK")
print("BORDER 行:", re.search(r".*BORDER = .*", s).group(0).strip())
