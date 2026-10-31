#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线检测：视频逐帧送进 PL，画框后经 ffmpeg(x264) 编码成清晰 mp4。

用法：python3 offline_detect.py 输入 输出 [最大帧数] [ms_on]
环境变量：
  INV=1     取反（等价 Black-Hat，找暗目标）
  DUAL=1    正反各跑一遍再合并
  TRACK=1   时域筛选（连续 HITS 帧才认）
  HITS=n    时域命中阈值（默认 2）
  AMIN/AMAX/PMIN  面积与峰值过滤
  CRF=18    x264 质量（越小越清楚）
  OUTW      输出宽度（默认用原视频宽度）
"""
import os
import subprocess
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, "/root/ip2")
import cam_pipe as cp

PW, PH = 640, 360          # 送进 PL 的分辨率（硬件固定）


def draw(img, cands, sx, sy, tag):
    for c in cands:
        x = int(c["x"] * sx)
        y = int(c["y"] * sy)
        side = max(2, int(round((c["area"]) ** 0.5)))
        r = max(6, min(int(40 * sx), int(side * sx * 0.75) + 6))
        cv2.rectangle(img, (x - r, y - r), (x + r, y + r), (0, 255, 0), max(2, int(2 * sx)))
        lbl = "%dpx pk%d" % (side, int(c["peak"]))
        ty = y - 8 if y > 26 else y + r + 18
        cv2.putText(img, lbl, (x + 4, ty), cv2.FONT_HERSHEY_SIMPLEX,
                    0.55 * sx, (0, 255, 0), max(1, int(1.5 * sx)), cv2.LINE_AA)
    cv2.putText(img, tag, (8, int(26 * sy)), cv2.FONT_HERSHEY_SIMPLEX,
                0.62 * sx, (0, 255, 255), max(2, int(2 * sx)), cv2.LINE_AA)
    return img


def main():
    src, dst = sys.argv[1], sys.argv[2]
    maxn = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3].isdigit() else 0
    use_ms = not (len(sys.argv) > 4 and sys.argv[4] == "0")

    amin = int(os.environ.get("AMIN", "4"))
    amax = int(os.environ.get("AMAX", "400"))
    pmin = int(os.environ.get("PMIN", "0"))
    inv = os.environ.get("INV", "0") == "1"
    dual = os.environ.get("DUAL", "0") == "1"
    track = os.environ.get("TRACK", "0") == "1"
    crf = os.environ.get("CRF", "18")

    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        print("打不开视频:", src)
        return 1
    srcw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    srch = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    OW = int(os.environ.get("OUTW", "0")) or srcw
    OH = int(round(OH_ := OW * srch / float(srcw))) if OW != srcw else srch
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    hw = cp.HW()
    trk = cp.Tracker()
    trk.MIN_HITS = int(os.environ.get("HITS", "2"))
    trk.MAX_MISS = int(os.environ.get("MISS", "3"))
    print("VERSION = 0x%08x  输出 %dx%d  CRF=%s" % (hw.rd(cp.R_VER), OW, OH, crf))

    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
         "-s", "%dx%d" % (OW, OH), "-r", "15", "-i", "-",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", crf, "-pix_fmt", "yuv420p", dst],
        stdin=subprocess.PIPE)

    n = 0
    t_all = 0.0
    n_tot = 0
    t_start = time.time()
    while True:
        ok, frame = cap.read()
        if not ok or (maxn and n >= maxn):
            break
        small = cv2.resize(frame, (PW, PH), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        t0 = time.time()
        st, cands, dt = hw.run_ms(gray) if use_ms else hw.run(gray)
        if inv or dual:
            inv_img = (255 - gray).astype(np.uint8)
            _r2 = hw.run_ms(inv_img) if use_ms else hw.run(inv_img)
            cands2 = _r2[1]
            if inv and not dual:
                cands = list(cands2)
            else:
                merged = list(cands)
                for c in cands2:
                    if not any(abs(c["x"] - m["x"]) <= 8 and abs(c["y"] - m["y"]) <= 8 for m in merged):
                        merged.append(c)
                cands = merged
        dt = (time.time() - t0)
        t_all += dt
        cands = [c for c in cands if amin <= c["area"] <= amax and c["peak"] >= pmin]
        if track:
            cands = cp.nms_tracks(trk.update(cands, 15.0), 0.3)
        n_tot += len(cands)

        base = frame if (srcw, srch) == (OW, OH) else cv2.resize(frame, (OW, OH), interpolation=cv2.INTER_AREA)
        disp = draw(base.copy(), cands, OW / float(PW), OH / float(PH),
                    "frame %d/%d  PL %.1fms  cand %d" % (n + 1, total, dt * 1000, len(cands)))
        ff.stdin.write(disp.tobytes())
        n += 1
        if n % 30 == 0:
            print("  %d 帧  PL均 %.1fms  候选均 %.1f" % (n, t_all / n * 1000, n_tot / n), flush=True)

    cap.release()
    ff.stdin.close()
    ff.wait()
    print("完成: %d 帧, 平均 PL %.1f ms, 平均每帧 %.1f 个候选, 总耗时 %.1f s"
          % (n, t_all / max(1, n) * 1000, n_tot / max(1, n), time.time() - t_start))
    print("输出:", dst, os.path.getsize(dst) if os.path.exists(dst) else "?")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
