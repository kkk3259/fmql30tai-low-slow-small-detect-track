# why_miss.py —— 只统计“画面区域”（屏蔽 HUD 与绿框），复算 Top-Hat + CFAR 看卡上方块能否过门限
import sys
import numpy as np
import cv2

path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/an.jpg"
img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
assert img is not None, "读图失败"
H, W = img.shape

# 屏蔽顶部 HUD（前 32 行）——那里有我们自己的白字
img2 = img.copy()
img2[:32, :] = 0

WIN, K, FLOOR = 31, 1.0, 3.0
half = WIN // 2
f = img2.astype(np.float64)
pad = cv2.copyMakeBorder(f, half, half, half, half, cv2.BORDER_REPLICATE)
mean = cv2.blur(pad, (WIN, WIN))[half:half + H, half:half + W]
sq = cv2.blur(pad * pad, (WIN, WIN))[half:half + H, half:half + W]
sd = np.sqrt(np.maximum(sq - mean * mean, 0.0))
thr = mean + K * sd + FLOOR
det = (f > thr).astype(np.uint8)
det[:32, :] = 0

n, lab, stats, cent = cv2.connectedComponentsWithStats(det, 8)
items = []
for i in range(1, n):
    x, y, w, h, a = stats[i]
    if 2 <= a <= 2000:
        items.append((a, int(cent[i][0]), int(cent[i][1]), w, h))
items.sort(reverse=True)

print("=== 按 RTL 语义复算（K=1, FLOOR=3, 31x31, 屏蔽 HUD）===")
print("过门限的连通域: %d 个（面积 2~2000）" % len(items))
print("%-6s %-10s %-6s %-6s %s" % ("面积", "中心", "宽", "高", "形状"))
for a, cx, cy, w, h in items[:15]:
    shape = "线" if (w > 6 * max(h, 1) or h > 6 * max(w, 1)) else "块"
    print("%-6d %-10s %-6d %-6d %s" % (a, "(%d,%d)" % (cx, cy), w, h, shape))

# 卡上 5 个方块的实际对比度（按经验位置采样）
print()
print("=== 屏幕上卡片的 5 个方块附近对比度 ===")
for cx, cy in [(88, 205), (170, 208), (295, 232), (410, 218), (525, 214)]:
    p = float(img2[cy, cx])
    m = float(mean[cy, cx])
    s = float(sd[cy, cx])
    t = float(thr[cy, cx])
    print("(%3d,%3d) 像素 %3.0f  邻域均值 %6.1f  标准差 %5.1f  门限 %6.1f  %s"
          % (cx, cy, p, m, s, t, "过" if p > t else "不过"))
