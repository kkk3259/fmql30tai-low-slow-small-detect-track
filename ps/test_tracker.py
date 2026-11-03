# -*- coding: utf-8 -*-
# test_tracker.py —— 用合成候选序列验证去抖/跟踪逻辑（不依赖相机与板卡）
import io, random, re, sys

src = io.open(r"D:\firstharness\repo\ps\cam_pipe.py", encoding="utf-8").read()
m = re.search(r"^class Tracker\(object\):.*?(?=^\S)", src, re.S | re.M)
if not m:
    print("没找到 Tracker 类"); sys.exit(1)
ns = {}
exec(compile(m.group(0), "cam_pipe.Tracker", "exec"), ns)
Tracker = ns["Tracker"]


def cand(x, y, area=9, peak=200):
    return {"x": x, "y": y, "area": area, "peak": peak}


def run(name, frames, expect):
    tr = Tracker()
    shown = []
    ids = []
    for f in frames:
        out = tr.update(f)
        shown.append(len(out))
        ids.append([t["id"] for t in out])
    ok = expect(shown, ids)
    print("%-34s 每帧显示数=%s  id序列=%s  %s" %
          (name, shown, ids[-1], "PASS" if ok else "FAIL"))
    return ok


random.seed(7)
allok = True

# A) 固定目标 10 帧：第 2 帧起稳定显示，id 不变
allok &= run("A 固定目标x10", [[cand(100, 120)]] * 10,
             lambda s, i: s[0] == 0 and all(v == 1 for v in s[1:]) and len(set(i[-1])) == 1)

# B) 位置抖动 ±3 px：仍是一条 track，不新增 id
jit = [[cand(100 + random.randint(-3, 3), 120 + random.randint(-3, 3))] for _ in range(12)]
allok &= run("B 抖动±3px x12", jit,
             lambda s, i: all(v == 1 for v in s[1:]) and len(set(i[-1])) == 1)

# C) 每帧随机噪声（互相远离）：不应产生稳定框
noise = [[cand(random.randint(0, 620), random.randint(0, 340))] for _ in range(15)]
allok &= run("C 随机噪声 x15", noise, lambda s, i: max(s) <= 1)

# D) 消失 3 帧后回到原位：id 保持（MAX_MISS=10）
seqd = [[cand(300, 200)]] * 5 + [[]] * 3 + [[cand(300, 200)]] * 3
allok &= run("D 丢3帧后回归", seqd,
             lambda s, i: len(set(i[-1])) == 1 and s[-1] == 1)

# E) 5 个目标同时存在：5 条稳定 id
five = [[cand(100 + k * 60, 120 + (k % 2) * 40) for k in range(5)] for _ in range(10)]
allok &= run("E 5目标同时 x10", five,
             lambda s, i: s[-1] == 5 and len(set(i[-1])) == 5)

print("总计:", "ALL-PASS" if allok else "HAS-FAIL")
