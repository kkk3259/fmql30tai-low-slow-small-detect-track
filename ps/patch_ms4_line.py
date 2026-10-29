# patch_ms4_line.py —— 开 4x 尺度（补 50~80px） + 剔除“细长亮线”类误报
import io

p = r"D:\firstharness\repo\ps\cam_pipe.py"
s = io.open(p, encoding="utf-8").read()

# 1) 开 4x
old = "MS_FACTOR2 = 0        # 第三遍倍数（4 => 补 20~80px；0=关闭，会再慢 1/3）"
assert old in s
s = s.replace(old, "MS_FACTOR2 = 4        # 第三遍倍数（4 => 补 20~80px）")

# 2) 线状剔除函数（插在 cluster_cands 之前）
anchor = "def cluster_cands(cands, r=12):"
assert anchor in s
func = '''def reject_lines(cands, dy=3, dx=30, need=3):
    """剔除“细长亮线”类误报：同一行（±dy）上出现 >=need 个相距 >dx 的候选 → 认为是边线，不是目标。
    显示器上边框、窗框、桌沿都属于这一类。"""
    if len(cands) < need:
        return cands
    rows = {}
    for c in cands:
        rows.setdefault(int(c["y"]) // (dy + 1), []).append(c)
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


'''
s = s.replace(anchor, func + anchor)

# 3) 在合并多尺度结果之后、聚类之前调用
old2 = "            shown = nms_tracks(self.tracker.update(cands, self.pl_fps()), NMS_IOU)"
assert old2 in s
s = s.replace(old2,
              "            cands = reject_lines(cands)\n"
              "            shown = nms_tracks(self.tracker.update(cands, self.pl_fps()), NMS_IOU)")

io.open(p, "w", encoding="utf-8").write(s)
print("patched OK")
