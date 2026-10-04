# -*- coding: utf-8 -*-
"""IP3 后处理测试：候选列表（含一对近邻，测 NMS）+ 参考（×2 坐标 + NMS 抑制）。
产出：pl/sim/input_postproc.hex（57 字节候选列表，16 位坐标）
      pl/sim/ref_postproc.hex（57 字节，×2 后 + NMS 合并）
格式：n_cand + 8×(x_hi,x_lo,y_hi,y_lo,area_hi,area_lo,peak)
"""
import os

sim_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "sim"))
NMS_DIST = 6

# 输入候选（降采样坐标，peak 降序）：(x, y, area, peak)
# 覆盖：① 近邻对 (70,45)/(71,45) → NMS 抑制；② x>127 测 ×2 溢出（130→260、200→400）；③ 边界坐标 639→1278
cands = [(70, 45, 6, 23), (71, 45, 4, 20), (130, 60, 5, 25), (200, 40, 3, 18), (639, 359, 4, 30)]


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


def write_list(path, lst):
    with open(path, "w") as f:
        f.write("%02X\n" % len(lst))
        for i in range(8):
            if i < len(lst):
                x, y, a, p = lst[i]
                f.write("%02X\n%02X\n%02X\n%02X\n%02X\n%02X\n%02X\n" %
                        (x >> 8, x & 255, y >> 8, y & 255, a >> 8, a & 255, p))
            else:
                f.write("00\n00\n00\n00\n00\n00\n00\n")


ref = nms(cands)

os.makedirs(sim_dir, exist_ok=True)
write_list(os.path.join(sim_dir, "input_postproc.hex"), cands)
write_list(os.path.join(sim_dir, "ref_postproc.hex"), ref)

print("OK: 输入候选 %d -> NMS 后 %d (抑制了近邻)" % (len(cands), len(ref)))
