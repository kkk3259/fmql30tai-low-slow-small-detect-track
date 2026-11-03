# -*- coding: utf-8 -*-
"""fix_win.py —— 把各 PS 脚本里的候选表窗口地址对齐到 RTL 真值

RTL 真值（repo/pl/rtl/ip2_axi_top.v，6 位地址）：
    0x00 W start        R {31'd0,start_r}
    0x04 W/R frame_addr
    0x08 W/R result_addr
    0x0C R STATUS       {.., done, err, busy}
    0x10 W 窗口字索引   R cand_rdata（452 B = 113 字）
    0x14 R VERSION      0x00010000
    0x18..0x38 R legacy_ram[0..8]（36 字节兼容视图）
    0x3C R st_mirror
→ 窗口是 0x10（索引写、数据同址读），不是 0x40/0x44。
   0x40 在 6 位地址下会绕回 0x00（写它会误触 start），必须改掉。
"""
import io, os

PS = r"./ps"
files = ["cam_pipe.py", "cand_read.py", "probe64.py", "probe64b.py",
         "probe_one.py", "probe_sizes.py", "size_sweep.py"]

repl = [
    ("R_CIDX = 0x40", "R_CIDX = 0x10"),
    ("R_CDAT = 0x44", "R_CDAT = 0x10"),
    ("R_CIDX = 0x40             # 写：窗口字索引（0..112）", "R_CIDX = 0x10             # 写：窗口字索引（0..112）"),
    ("R_CDAT = 0x44             # 读：该字（全 452 字节 = 64 个候选）", "R_CDAT = 0x10             # 读：该字（与索引同址，452 字节 = 64 个候选）"),
]

changed = []
for f in files:
    p = os.path.join(PS, f)
    if not os.path.exists(p):
        continue
    s = io.open(p, encoding="utf-8").read()
    o = s
    for a, b in repl:
        s = s.replace(a, b)
    # 注释里提到 0x40/0x44 的地方一并纠正（只改看起来是地址说明的行）
    s = s.replace("写 0x40 字索引，读 0x44", "写 0x10 字索引，读 0x10")
    s = s.replace("写：候选表字索引（0x10 是 FRAME_ID，别写错）", "写：候选表字索引（6 位地址，0x40 会绕回 0x00）")
    s = s.replace("写：候选表字索引（注意 0x10 是 FRAME_ID，早期此处写错成 0x10）",
                  "写：候选表字索引（6 位地址，0x40 会绕回 0x00）")
    s = s.replace("说明这个位流没有 0x40/0x44 窗口（6 位地址的老构建），必须走 legacy。",
                  "说明这个位流没有窗口（老构建），必须走 legacy。")
    s = s.replace("往 0x40 写字索引 3 再读回；若读回值不等于 3（说明 0x40 绕回 0x00），则用 legacy。",
                  "写索引 0 后读回该字，与 legacy[0] 比对；不一致则用 legacy。")
    if s != o:
        io.open(p, "w", encoding="utf-8", newline="\n").write(s)
        changed.append(f)

print("已修改:", changed)
for f in changed:
    p = os.path.join(PS, f)
    for i, line in enumerate(io.open(p, encoding="utf-8"), 1):
        if "R_CIDX" in line or "R_CDAT" in line:
            print("  %s:%d %s" % (f, i, line.strip()))
