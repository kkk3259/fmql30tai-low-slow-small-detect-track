# -*- coding: utf-8 -*-
"""chk_pl.py —— 确认 PL 到底有没有在跑：AR/STATUS 变化 + 候选表内容。"""
import sys
import time

import numpy as np

sys.path.insert(0, "/root/ip2")
from cam3d_test import PL3D, NPIX, REG, R_AR, R_STATUS  # noqa

pl = PL3D()
g = np.full((360, 640), 120, np.uint8)
# 中心放一个 3x3 亮块，落在 SE=5 的窗口内
g[178:181, 318:321] = 250

for i in range(3):
    a0 = pl.reg.read(REG + R_AR) & 0xFFFFFFFF
    cands, st, dt = pl.run(g)
    a1 = pl.reg.read(REG + R_AR) & 0xFFFFFFFF
    print("run%d  dAR=%d  STATUS=0x%08X  n=%d  dt=%.2fms" %
          (i, (a1 - a0) & 0xFFFFFFFF, st, len(cands), dt))
    for c in cands[:4]:
        print("    x=%d y=%d area=%d peak=%d" %
              (c["x"], c["y"], c["area"], c["peak"]))
