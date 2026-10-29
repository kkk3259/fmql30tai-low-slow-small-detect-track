# -*- coding: utf-8 -*-
# patch_area16b.py —— 处理 dict 风格解码：{"x": .., "y": .., "area": b[5], "peak": b[6]}
import io, os, re

files = [
    r"D:\firstharness\repo\ps\cam_pipe.py",
    r"D:\firstharness\repo\ps\read_cand.py",
    r"D:\firstharness\repo\ps\pl_debug.py",
]
pat = re.compile(r'"area": b\[5\], "peak": b\[6\]')
for f in files:
    if not os.path.exists(f):
        continue
    s = io.open(f, encoding="utf-8").read()
    s2, n = pat.subn('"area": (b[4] << 8) | b[5], "peak": b[6]', s)
    if n:
        io.open(f, "w", encoding="utf-8").write(s2)
        print("已改 %-16s 替换 %d 处" % (os.path.basename(f), n))
    else:
        print("未变 %-16s" % os.path.basename(f))
