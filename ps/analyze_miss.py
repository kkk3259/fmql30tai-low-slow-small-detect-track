# analyze_miss.py —— 用同帧图像复算 CFAR，解释“为什么屏幕上的方块检不出来”
import sys
import numpy as np
import cv2

path = sys.argv[1] if len(sys.argv) > 1 else r"./data/line_rej.jpg"
img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
assert img is not None, "读图失败: " + path
H, W = img.shape

# 1) 用 OpenCV 当“地面真值”：找亮块
_, bw = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
n, lab, stats, cent = cv2.connectedComponentsWithStats(bw, 8)
gt = []
for i in range(1, n):
    x, y, w, h, a = stats[i]
    if 4 <= a <= 2000 and w <= 60 and h <= 60:
        gt.append((int(cent[i][0]), int(cent[i][1]), int(a), w, h))

print("OpenCV 认定的小亮块: %d 个" % len(gt))
print("Otsu 阈值 = %.0f, 全图均值 %.1f" % (cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[0], img.mean()))

# 2) 按 RTL 语义复算 CFAR:  x > mean + K*sd + FLOOR,  K=1, FLOOR=3, 窗口 31x31（因果近似=居中）
K, FLOOR, WIN = 1.0, 3.0, 31
half = WIN // 2
pad = cv2.copyMakeBorder(img.astype(np.float64), half, half, half, half, cv2.BORDER_REPLICATE)
mean = cv2.blur(pad, (WIN, WIN))[half:half + H, half:half + W]
sq = cv2.blur(pad * pad, (WIN, WIN))[half:half + H, half:half + W]
var = np.maximum(sq - mean * mean, 0.0)
sd = np.sqrt(var)

print()
print("%-6s %-10s %-8s %-8s %-8s %-8s %s" % ("#", "中心(x,y)", "像素x", "邻域均值", "标准差", "门限", "判定"))
npass = 0
for i, (cx, cy, a, w, h) in enumerate(gt[:20]):
    x = float(img[cy, cx])
    m = float(mean[cy, cx])
    s = float(sd[cy, cx])
    thr = m + K * s + FLOOR
    ok = x > thr
    npass += 1 if ok else 0
    print("%-6d %-10s %-8.0f %-8.1f %-8.1f %-8.1f %s" % (i, "(%d,%d)" % (cx, cy), x, m, s, thr, "过" if ok else "不过"))
print()
print("按 RTL 门限：%d/%d 个亮块能过" % (npass, min(20, len(gt))))
