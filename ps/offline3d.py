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
            out.append((x, y, area, peak))
    # 简单去重（10px 内取 peak 大的）
    out.sort(key=lambda t: -t[3])
    keep = []
    for t in out:
        if all((t[0] - k[0]) ** 2 + (t[1] - k[1]) ** 2 > 100 for k in keep):
            keep.append(t)
    return keep


def draw(img, cands, extra=""):
    vis = img.copy()
    for (x, y, area, peak) in cands:
        r = max(6, int(round((area ** 0.5) * 1.6)))
        cv2.rectangle(vis, (x - r, y - r), (x + r, y + r), (0, 255, 0), 2)
        cv2.putText(vis, "%dpx p%d" % (area, peak), (x + r + 2, y - r),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(vis, "cand %d %s" % (len(cands), extra), (10, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2, cv2.LINE_AA)
    return vis


def main():
    ap = argparse.ArgumentParser()
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
        cands = detect(pl, g, a)
        print("IMG %dx%d -> cand %d" % (w0, h0, len(cands)))
        for c in cands[:12]:
            print("   x=%d y=%d area=%d peak=%d" % c)
        cv2.imwrite(a.out, draw(im, [(int(x * w0 / W), int(y * h0 / H), ar, pk)
                                     for (x, y, ar, pk) in cands]))
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
            cands = detect(pl, g, a)
            vis = draw(fr, [(int(x * w0 / W), int(y * h0 / H), ar, pk)
                            for (x, y, ar, pk) in cands],
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
