#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""offline3d.py —— 用三域位流离线跑图片/视频，输出带框结果。

用法：
  python3 offline3d.py --img  /root/ip2/drone_ref.png --out /root/o3d_img.png
  python3 offline3d.py --vid  /root/bird.mp4 --out /root/o3d_bird.mp4 --maxn 120
参数：
  --gamma 0.08   --invert 0/1   --invboth 1（正反各跑一遍合并）
  --amin/--amax/--pmin  面积与峰值过滤
"""
import argparse
import os
import sys

import subprocess

import cv2
import numpy as np

sys.path.insert(0, "/root/ip2")
os.chdir("/root/ip2")
import cam3d_test as C  # noqa: E402

W, H = 640, 360


def to_pl(g, gamma, invert):
    if gamma and abs(gamma - 1.0) > 1e-3:
        lut = np.array([min(255, int(round(255.0 * ((i / 255.0) ** gamma))))
                        for i in range(256)], np.uint8)
        g = cv2.LUT(g, lut)
    if invert:
        g = (255 - g).astype(np.uint8)
    return g


def detect(pl, gray, a):
    """跑一遍或正反两遍，返回 [(x,y,area,peak), ...]"""
    runs = [0, 1] if a.invboth else [a.invert]
    out = []
    for inv in runs:
        g = to_pl(gray, a.gamma, inv)
        try:
            cands, st, dt = pl.run(g)
        except TypeError:
            r = pl.run(g)
            cands = r[0]
        # cands 可能是 dict 或 tuple，统一成 (x,y,area,peak)
        norm = []
        for c in cands:
            if isinstance(c, dict):
                norm.append((c.get("x", 0), c.get("y", 0), c.get("area", 0), c.get("peak", 0)))
            elif isinstance(c, (tuple, list)) and len(c) >= 4:
                norm.append((c[0], c[1], c[2], c[3]))
        cands = norm
        for c in cands:
            x, y, area, peak = c[0], c[1], c[2], c[3]
            x = (x + C.X_SHIFT) % W
            if not (a.amin <= area <= a.amax):
                continue
            if peak < a.pmin:
                continue
            if y < a.border or y > H - a.border:
                continue
            out.append((x, y, area, peak, None))
    # 简单去重（10px 内取 peak 大的）
    out.sort(key=lambda t: -t[3])
    keep = []
    for t in out:
        if all((t[0] - k[0]) ** 2 + (t[1] - k[1]) ** 2 > 100 for k in keep):
            keep.append(t)
    return keep


_NPU_ERR = False



def _half(area):
    return max(6.0, (max(area, 1) ** 0.5) * 1.6)


def cluster(cands, radius=30):
    """把相距 radius 内的候选并成一个目标：取外接包围盒，面积换成等效边长。"""
    groups = []
    for c in sorted(cands, key=lambda t: -t[3]):     # 峰值高的先建组，避免大块吞小块
        for g in groups:
            span = max(_half(c[2]), _half(g["m"][0][2]))
            if (c[0] - g["cx"]) ** 2 + (c[1] - g["cy"]) ** 2 <= radius ** 2 and span < 70:
                g["m"].append(c)
                g["cx"] = sum(x[0] for x in g["m"]) / len(g["m"])
                g["cy"] = sum(x[1] for x in g["m"]) / len(g["m"])
                break
        else:
            groups.append({"m": [c], "cx": c[0], "cy": c[1]})
    out = []
    for g in groups:
        ms = g["m"]
        x0 = min(c[0] - _half(c[2]) for c in ms)
        x1 = max(c[0] + _half(c[2]) for c in ms)
        y0 = min(c[1] - _half(c[2]) for c in ms)
        y1 = max(c[1] + _half(c[2]) for c in ms)
        w, h = max(1, x1 - x0), max(1, y1 - y0)
        area = int(round((w * h) / 4.0))          # 等效：sqrt(area)*2 = sqrt(w*h)
        peak = max(int(c[3]) for c in ms)
        ps = [c[4] for c in ms if len(c) > 4 and c[4] is not None]
        p = max(ps) if ps else None
        out.append(((x0 + x1) / 2.0, (y0 + y1) / 2.0, area, peak, p))
    out.sort(key=lambda t: -t[3])
    return out


CS_SCALE = 1.7


_JUDGE = None


def classify(npu, gray, cands, side=40):
    global _JUDGE
    if npu is None:
        return cands
    if _JUDGE is None:
        from npu_judge import Judge
        _JUDGE = Judge()
    return _JUDGE.update(npu, gray, cands)


def draw(img, cands, extra=""):
    vis = img.copy()
    for c in cands:
        x, y, area, peak = c[0], c[1], c[2], c[3]
        pr = c[4] if len(c) > 4 else None
        r = max(6, int(round((area ** 0.5) * 1.6)))
        # 绿=NPU 判为无人机(p>=0.5)；橙=判不是；灰=没判
        col = (0, 255, 0) if (pr is not None and pr >= 0.5) else ((0, 165, 255) if pr is not None else (160, 160, 160))
        cv2.rectangle(vis, (x - r, y - r), (x + r, y + r), col, 2)
        tag = "%dpx p%d" % (area, peak) + ("" if pr is None else " %.0f%%" % (pr * 100))
        cv2.putText(vis, tag, (x + r + 2, y - r),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1, cv2.LINE_AA)
    cv2.putText(vis, "cand %d %s" % (len(cands), extra), (10, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2, cv2.LINE_AA)
    return vis


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cs", type=float, default=1.7)          # 裁剪边长 = cs * 2*sqrt(area)，1.7 时目标约占 60%
    ap.add_argument("--npu", type=int, default=1)          # 1=每个候选送 cls128 判是不是无人机
    ap.add_argument("--model", default="/root/npu/cls128_drone_ZG")
    ap.add_argument("--img", default="")
    ap.add_argument("--vid", default="")
    ap.add_argument("--out", default="/root/o3d.png")
    ap.add_argument("--maxn", type=int, default=120)
    ap.add_argument("--gamma", type=float, default=0.08)
    ap.add_argument("--invert", type=int, default=0)
    ap.add_argument("--invboth", type=int, default=1)
    ap.add_argument("--amin", type=int, default=4)
    ap.add_argument("--amax", type=int, default=4000)
    ap.add_argument("--pmin", type=int, default=15)
    ap.add_argument("--border", type=int, default=24)
    a = ap.parse_args()

    print("PL init ...")
    pl = C.PL3D()
    npu = None
    if a.npu:
        try:
            npu = C.NPU(a.model + ".json", a.model + ".raw", dev=pl.dev)
            print("NPU ok -> %s" % a.model)
        except Exception as ex:
            print("NPU load failed:", ex)
    print("PL3D ready")

    if a.img:
        im = cv2.imread(a.img)
        if im is None:
            print("IMG_FAIL")
            return
        h0, w0 = im.shape[:2]
        g = cv2.cvtColor(cv2.resize(im, (W, H), interpolation=cv2.INTER_AREA),
                         cv2.COLOR_BGR2GRAY)
        pl.run(g)                      # 预热
        cands = classify(npu, g, cluster(detect(pl, g, a)))
        print("IMG %dx%d -> cand %d" % (w0, h0, len(cands)))
        for c in cands[:12]:
            print("   x=%d y=%d area=%d peak=%d p=%s" % (c[0], c[1], c[2], c[3], c[4] if len(c) > 4 else None))
        cv2.imwrite(a.out, draw(im, [(int(x * w0 / W), int(y * h0 / H), ar, pk, p)
                                     for (x, y, ar, pk, p) in [(c[0], c[1], c[2], c[3], c[4] if len(c) > 4 else None) for c in cands]]))
        print("OUT", a.out)
        return

    if a.vid:
        cap = cv2.VideoCapture(a.vid)
        w0 = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h0 = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        ofps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        ow = 960
        oh = int(round(h0 * ow / w0 / 2)) * 2
        ff = ("ffmpeg -y -loglevel error -f rawvideo -pix_fmt bgr24 -s %dx%d "
              "-r %.2f -i - -c:v libx264 -crf 20 -pix_fmt yuv420p %s"
              % (ow, oh, ofps, a.out))
        pout = subprocess.Popen(ff.split(), stdin=subprocess.PIPE).stdin
        tot = 0
        n = 0
        while n < a.maxn:
            ok, fr = cap.read()
            if not ok:
                break
            g = cv2.cvtColor(cv2.resize(fr, (W, H), interpolation=cv2.INTER_AREA),
                             cv2.COLOR_BGR2GRAY)
            cands = classify(npu, g, cluster(detect(pl, g, a)))
            vis = draw(fr, [(int(x * w0 / W), int(y * h0 / H), ar, pk, p)
                            for (x, y, ar, pk, p) in [(c[0], c[1], c[2], c[3], c[4] if len(c) > 4 else None) for c in cands]],
                       "f%d" % n)
            pout.write(cv2.resize(vis, (ow, oh)).tobytes())
            tot += len(cands)
            n += 1
            if n % 20 == 0:
                print("  %d frames, cand/frame=%.1f" % (n, tot / n))
        pout.close()
        cap.release()
        print("VID done %d frames cand/frame=%.1f -> %s" % (n, tot / max(1, n), a.out))
        return

    print("need --img or --vid")


if __name__ == "__main__":
    main()
