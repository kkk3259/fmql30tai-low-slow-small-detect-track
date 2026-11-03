#!/usr/bin/env python3
# which_bit.py —— 判定板上现在跑的到底是新版还是旧版位流
# 新版特征：0x40/0x44 窗口存在（0x40 写索引、读回同一索引；0x44 读数据）
# 旧版特征：0x18 是调试计数（只读），0x40 会回卷到 0x00（CTRL）
import os, mmap, struct, time, sys

PAGE = 4096
mem = open('/dev/mem', 'rb+')
regs = mmap.mmap(mem.fileno(), PAGE, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=0x43C00000)

def rd(a):
    return struct.unpack('<I', regs[a:a + 4])[0]

def wr(a, v):
    regs[a:a + 4] = struct.pack('<I', v & 0xFFFFFFFF)

print("VERSION(0x14)   = 0x%08x" % rd(0x14))
print("STATUS (0x0C)   = 0x%08x" % rd(0x0C))
print("FRAME  (0x04)   = 0x%08x" % rd(0x04))
print("RESULT (0x08)   = 0x%08x" % rd(0x08))

print("\n--- 写 0x40=5（窗口索引），再读回 0x40 与 0x18 ---")
wr(0x40, 5)
time.sleep(0.02)
v18 = rd(0x18)
v40 = rd(0x40)
print("0x40 = 0x%08x   (新版索引寄存器应=5)" % v40)
print("0x18 = 0x%08x   (新版这里是 36 字节兼容视图第 0 字)" % v18)

print("\n--- 读 0x44（候选数据，新版）---")
print("0x44 = 0x%08x" % rd(0x44))

print("\n--- 对照：写 0x18=7 再读回 ---")
wr(0x18, 7)
time.sleep(0.02)
print("0x18 = 0x%08x   (旧版是只读调试计数，不会等于7)" % rd(0x18))

if v40 == 5:
    print("\n=== 板上是【新版】位流（0x40/0x44 窗口存在）===")
else:
    print("\n=== 板上是【旧版】位流（0x40 回卷或 0x18 只读）===")
