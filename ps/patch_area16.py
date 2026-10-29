# -*- coding: utf-8 -*-
# patch_area16.py —— 把 PS 侧候选表解码从“8 位面积”改成“16 位面积”（高字节在 byte4）
import io, os, re

files = [
    r"D:\firstharness\repo\ps\cam_pipe.py",
    r"D:\firstharness\repo\ps\probe64.py",
    r"D:\firstharness\repo\ps\probe64b.py",
    r"D:\firstharness\repo\ps\probe_one.py",
    r"D:\firstharness\repo\ps\probe_sizes.py",
    r"D:\firstharness\repo\ps\read_cand.py",
    r"D:\firstharness\repo\ps\pl_debug.py",
]

pats = [
    # 形如 (b[0]<<8)|b[1], (b[2]<<8)|b[3], b[5], b[6]
    (re.compile(r"\(b\[0\] << 8\) \| b\[1\], \(b\[2\] << 8\) \| b\[3\], b\[5\], b\[6\]"),
     "((b[0] << 8) | b[1], (b[2] << 8) | b[3], (b[4] << 8) | b[5], b[6])"),
    (re.compile(r"b\[4\] \* 256 \+ b\[5\]"),
     "((b[4] << 8) | b[5])"),
]

for f in files:
    if not os.path.exists(f):
        print("跳过（不存在）", os.path.basename(f))
        continue
    s = io.open(f, encoding="utf-8").read()
    orig = s
    n = 0
    for pat, rep in pats:
        s, k = pat.subn(rep, s)
        n += k
    if s != orig:
        io.open(f, "w", encoding="utf-8").write(s)
        print("已改 %-18s 替换 %d 处" % (os.path.basename(f), n))
    else:
        print("未变 %-18s（检查是否已是 16 位面积解码）" % os.path.basename(f))
