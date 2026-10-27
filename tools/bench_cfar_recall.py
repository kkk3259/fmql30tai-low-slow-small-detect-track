# -*- coding: utf-8 -*-
"""CFAR 粗筛召回实验（PC 端，不需要板子）

回答三个问题：
  1. topk 对召回的影响（此前默认 topk=5 导致小目标召回仅 4%）
  2. Top-Hat（提亮斑）vs Black-Hat（提暗斑）哪个对当前数据更有效
  3. 双路（两路各自检测再合并）能否进一步提升

数据：deploy/eval_roi_448/  100 张真实图，4 个尺寸档各 25 张（15-35 档 30 张）
判据：候选质心落在 2 倍 GT 框内算命中

实测结论（2026-10-27）：
  Top-Hat only  topk=64 : 合计 69.0%（15-35px 仅 28.0%）
  Black-Hat     topk=64 : 合计 87.0%（15-35px 80.0%）
  Black-Hat     topk=128: 合计 93.0%
  双路各 topk=64 再合并 : 合计 94.0%（15-35px 92.0%）← 最优

用法：
  python tools/bench_cfar_recall.py
  python tools/bench_cfar_recall.py --tol 1.5 --topk 32
"""
import os, csv, argparse, numpy as np, cv2
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(REPO, "deploy", "eval_roi_448")


def imread_cn(path):
    """cv2.imread 不支持中文路径，改用 fromfile + imdecode"""
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


def load_gt(fn, W, H):
    """读 YOLO label，返回原图像素坐标的 (cx, cy, w, h)"""
    lp = os.path.join(BASE, "labels", fn.replace(".jpg", ".txt"))
    out = []
    for line in open(lp, encoding="utf-8"):
        p = line.split()
        if len(p) < 5:
            continue
        cx, cy, bw, bh = [float(x) for x in p[1:5]]
        out.append((cx * W, cy * H, bw * W, bh * H))
    return out


def cfar_binary(img, win=31, k=4.0, floor=3.0):
    """局部均值 + k×局部标准差（CFAR 思想，硬件里是滑动累加）"""
    f = img.astype(np.float32)
    mu = cv2.boxFilter(f, -1, (win, win), normalize=True, borderType=cv2.BORDER_REFLECT)
    mu2 = cv2.boxFilter(f * f, -1, (win, win), normalize=True, borderType=cv2.BORDER_REFLECT)
    sd = np.sqrt(np.maximum(mu2 - mu * mu, 0))
    return ((f > mu + k * sd + floor)).astype(np.uint8) * 255


def candidates(binary, enh, topk, min_area=2, max_area=200):
    """连通域 → 质心，按 peak 降序取前 topk"""
    n, lab, stats, cents = cv2.connectedComponentsWithStats(binary, connectivity=8)
    out = []
    for i in range(1, n):
        a = stats[i, cv2.CC_STAT_AREA]
        if a < min_area or a > max_area:
            continue
        m = (lab == i)
        peak = float(enh[m].max()) if m.any() else 0.0
        out.append((float(cents[i][0]), float(cents[i][1]), int(a), peak))
    out.sort(key=lambda c: -c[3])
    return out[:topk]


class Detector(object):
    def __init__(self, down=2, se=5, win=31, k=4.0, floor=3.0):
        self.down, self.se, self.win, self.k, self.floor = down, se, win, k, floor
        self._kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (se, se))

    def enhance(self, bgr):
        """返回 (tophat, blackhat)，都做过降采样"""
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        g = gray[::self.down, ::self.down] if self.down > 1 else gray
        top = cv2.morphologyEx(g, cv2.MORPH_TOPHAT, self._kernel)
        blk = cv2.morphologyEx(g, cv2.MORPH_BLACKHAT, self._kernel)
        return top, blk

    def detect(self, bgr, mode="dual", topk=64, merge_r=8):
        """mode: top | black | dual"""
        top, blk = self.enhance(bgr)
        cs = []
        if mode in ("top", "dual"):
            cs += candidates(cfar_binary(top, self.win, self.k, self.floor), top, topk)
        if mode in ("black", "dual"):
            cs += candidates(cfar_binary(blk, self.win, self.k, self.floor), blk, topk)
        if mode == "dual":
            # 合并去重：距离 < merge_r 的只留 peak 最大的
            cs.sort(key=lambda c: -c[3])
            kept = []
            for c in cs:
                if all((c[0] - o[0]) ** 2 + (c[1] - o[1]) ** 2 > merge_r ** 2 for o in kept):
                    kept.append(c)
            cs = kept
        return [(x * self.down, y * self.down, a) for x, y, a, _ in cs]


def evaluate(rows, det, mode, topk, tol):
    stat = defaultdict(lambda: {"n": 0, "hit": 0, "nc": []})
    for r in rows:
        fn, tier = r["文件"], r["尺寸档"]
        img = imread_cn(os.path.join(BASE, "images", fn))
        if img is None:
            continue
        H, W = img.shape[:2]
        pts = det.detect(img, mode=mode, topk=topk)
        s = stat[tier]
        s["n"] += 1
        s["nc"].append(len(pts))
        hit = any(abs(x - gx) <= gw * tol / 2 and abs(y - gy) <= gh * tol / 2
                  for (gx, gy, gw, gh) in load_gt(fn, W, H)
                  for (x, y, a) in pts)
        if hit:
            s["hit"] += 1
    return stat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tol", type=float, default=2.0, help="GT 框容差倍数")
    ap.add_argument("--topk", type=int, default=64)
    a = ap.parse_args()

    with open(os.path.join(BASE, "manifest.csv"), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print("  样本 %d 张，容差 %.1f 倍 GT 框" % (len(rows), a["tol"] if isinstance(a, dict) else a.tol))

    det = Detector()
    tiers = ["15-35px", "35-70px", "70-150px", "150-400px"]

    print()
    print("  ════ 形态学方向对比（topk=%d）════" % a.topk)
    print("  %-12s %10s %10s %10s %10s" % ("模式", *tiers, ))
    for mode, name in (("top", "Top-Hat"), ("black", "Black-Hat"), ("dual", "双路")):
        st = evaluate(rows, det, mode, a.topk, a.tol)
        vals = [st[t]["hit"] / st[t]["n"] * 100 if t in st else 0 for t in tiers]
        tot_n = sum(st[t]["n"] for t in st)
        tot_h = sum(st[t]["hit"] for t in st)
        print("  %-12s %9.0f%% %9.0f%% %9.0f%% %9.0f%%   合计 %.1f%%"
              % (name, vals[0], vals[1], vals[2], vals[3], tot_h / tot_n * 100))

    print()
    print("  ════ Black-Hat 的 topk 曲线 ════")
    print("  %-8s %9s %9s %9s %9s %10s %8s"
          % ("topk", *tiers, "合计", "候选数"))
    for tk in (16, 32, 64, 128):
        st = evaluate(rows, det, "black", tk, a.tol)
        vals = [st[t]["hit"] / st[t]["n"] * 100 if t in st else 0 for t in tiers]
        tot_n = sum(st[t]["n"] for t in st)
        tot_h = sum(st[t]["hit"] for t in st)
        nc = np.mean([np.mean(st[t]["nc"]) for t in st])
        print("  %-8d %8.0f%% %8.0f%% %8.0f%% %8.0f%% %9.1f%% %8.1f"
              % (tk, vals[0], vals[1], vals[2], vals[3], tot_h / tot_n * 100, nc))


if __name__ == "__main__":
    main()