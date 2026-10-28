# patch_decode.py —— 修正候选表解码：area 取 b[5]（8 位，<=200），peak 取 b[6]
import io
import os

OLD = '"area": b[5] * 256 + b[6], "peak": b[6]})'
NEW = '"area": b[5], "peak": b[6]})'

for name in ("cam_pipe.py", "cam_demo.py", "read_cand.py"):
    p = os.path.join(r"D:\firstharness\repo\ps", name)
    s = io.open(p, encoding="utf-8").read()
    if OLD not in s:
        print("%-14s 未找到待改串（跳过）" % name)
        continue
    s = s.replace(OLD, NEW)
    io.open(p, "w", encoding="utf-8").write(s)
    print("%-14s 已修正" % name)
