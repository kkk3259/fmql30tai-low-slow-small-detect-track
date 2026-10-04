# -*- coding: utf-8 -*-
"""IP3 后处理测试：候选列表（含一对近邻，测 NMS）+ 参考（×2 坐标 + NMS 抑制）。
产出：pl/sim/input_postproc.hex（33 字节候选列表，降采样坐标）
      pl/sim/ref_postproc.hex（33 字节，×2 后 + NMS 合并）
"""
import os

sim_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "sim"))
NMS_DIST = 6

# 输入候选（降采样坐标，peak 降序）：(x, y, area, peak)
# (70,45) 与 (71,45) ×2 后相距 2 < NMS_DIST，后者应被 NMS 抑制
cands = [(70, 45, 6, 23), (71, 45, 4, 20), (100, 30, 2, 14)]

def nms(cands):
    out = []
    for cx, cy, a, p in cands:
        x2, y2 = cx * 2, cy * 2
        suppressed = False
        for ox, oy, _, _ in out:
            if abs(x2 - ox) <= NMS_DIST and abs(y2 - oy) <= NMS_DIST:
                suppressed = True
                break
        if not suppressed:
            out.append((x2, y2, a, p))
    return out

ref = nms(cands)

os.makedirs(sim_dir, exist_ok=True)
with open(os.path.join(sim_dir, "input_postproc.hex"), "w") as f:
    f.write("%02X\n" % len(cands))
    for i in range(8):
        if i < len(cands):
            f.write("%02X\n%02X\n%02X\n%02X\n" % cands[i])
        else:
            f.write("00\n00\n00\n00\n")
with open(os.path.join(sim_dir, "ref_postproc.hex"), "w") as f:
    f.write("%02X\n" % len(ref))
    for i in range(8):
        if i < len(ref):
            f.write("%02X\n%02X\n%02X\n%02X\n" % ref[i])
        else:
            f.write("00\n00\n00\n00\n")

print("OK: 输入候选 %d -> NMS 后 %d (抑制了近邻)" % (len(cands), len(ref)))
