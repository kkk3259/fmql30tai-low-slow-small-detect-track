# patch_regs2.py —— 把探针脚本的候选表窗口地址更新到新映射（0x40 索引 / 0x44 数据）
import io, re

def patch(path, pairs):
    s = io.open(path, encoding="utf-8").read()
    for a, b in pairs:
        if a not in s:
            print("  [warn] 未找到: %s" % a[:40])
        s = s.replace(a, b)
    io.open(path, "w", encoding="utf-8").write(s)
    print("patched", path)

base = r"D:\firstharness\repo\ps"

patch(base + r"\probe64.py", [
    ("R_CIDX = 0x10", "R_CIDX = 0x40"),
    ("R_CDAT = 0x10", "R_CDAT = 0x44"),
])

patch(base + r"\probe64b.py", [
    ("R_CIDX = 0x10          # 写：字索引；读：该字",
     "R_CIDX = 0x40          # 写：字索引（读回索引）\nR_CDAT = 0x44          # 读：该字"),
    ("wr(R_CIDX, i)\n        words.append(rd(R_CIDX))",
     "wr(R_CIDX, i)\n        words.append(rd(R_CDAT))"),
])

patch(base + r"\which_bit.py", [
    ("# 新版特征：0x40/0x44 窗口存在；写 0x40=5 后读 0x18 得到 5（0x18 是候选索引寄存器）",
     "# 新版特征：0x40/0x44 窗口存在（0x40 写索引、读回同一索引；0x44 读数据）"),
    ("print(\"\\n--- 写 0x40=5（候选索引），再读 0x18 ---\")\nwr(0x40, 5)\ntime.sleep(0.02)\nv18 = rd(0x18)\nv40 = rd(0x40)\nprint(\"0x18 = 0x%08x   (新版应=5)\" % v18)\nprint(\"0x40 = 0x%08x   (新版应=5)\" % v40)",
     "print(\"\\n--- 写 0x40=5（窗口索引），再读回 0x40 与 0x18 ---\")\nwr(0x40, 5)\ntime.sleep(0.02)\nv18 = rd(0x18)\nv40 = rd(0x40)\nprint(\"0x40 = 0x%08x   (新版索引寄存器应=5)\" % v40)\nprint(\"0x18 = 0x%08x   (新版这里是 36 字节兼容视图第 0 字)\" % v18)"),
    ("if v18 == 5 and v40 == 5:", "if v40 == 5:"),
])
