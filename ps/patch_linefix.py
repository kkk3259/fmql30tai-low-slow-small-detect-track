# patch_linefix.py —— 修正线状剔除：只对画面上下边带生效（否则会把同一行上的多个真目标一起删掉）
import io

p = r"D:\firstharness\repo\ps\cam_pipe.py"
s = io.open(p, encoding="utf-8").read()

start = s.find("def reject_lines(")
assert start > 0
end = s.find("def cluster_cands(")
assert end > start

new_fn = '''def reject_lines(cands, dy=3, dx=30, need=3, band=48):
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


'''

s = s[:start] + new_fn + s[end:]
io.open(p, "w", encoding="utf-8").write(s)
print("patched OK")
