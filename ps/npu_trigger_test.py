#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""npu_trigger_test.py —— 验证三域里「PL 出候选 → NPU 复核」真的被触发

用一张可控图（深底 + 若干 3px 白点，匹配当前 SE=5 位流的 2~4px 窗口）
跑一次 PL3D，再对每个候选裁剪 128×128 送 cls128，打印概率与耗时。
"""
import os
import time

import cv2
import numpy as np

from cam3d_test import PL3D, NPU, crop, NPIX

OUT = "/root/ip2/npu_trigger.png"
DOTS = [(400, 120), (460, 120), (520, 120), (580, 120)]


def make_img():
    img = np.full((360, 640), 40, np.uint8)
    for (x, y) in DOTS:
        img[y - 1:y + 2, x - 1:x + 2] = 235      # 3x3 实心
    cv2.imwrite(OUT, img)
    return img


def main():
    img = make_img()
    print("测试图 %s  白点数=%d  尺寸=%dx%d"
          % (OUT, len(DOTS), img.shape[1], img.shape[0]), flush=True)

    pl = PL3D()
    pl.run(img)          # 预热一拍：首帧 PL-DDR 常读到旧数据
    time.sleep(0.15)
    pl.ch.write(0, img.tobytes(), NPIX)
    try:
        pl.ch.sync(1)
    except Exception:
        pass
    time.sleep(0.15)
    t0 = time.time()
    cands, st, dt = pl.run(img)
    print("PL: st=0x%08X dt=%.2fms  n=%d  总耗时 %.0fms"
          % (st, dt, len(cands), (time.time() - t0) * 1000), flush=True)
    for i, c in enumerate(cands):
        print("  cand%d x=%d y=%d area=%d peak=%d"
              % (i, c["x"], c["y"], c["area"], c["peak"]), flush=True)

    if not cands:
        print("NO_CAND：PL 没出候选，NPU 无法触发", flush=True)
        return 2

    net = NPU("/root/npu/cls128_drone_ZG.json", "/root/npu/cls128_drone_ZG.raw", dev=pl.dev)
    print("NPU ready", flush=True)
    tot = 0.0
    for i, c in enumerate(cands):
        side = max(16, int(round(2.5 * (c["area"] ** 0.5))))
        patch = crop(img, c["x"], c["y"], side=side)
        t1 = time.time()
        pr = net.predict(patch)
        ms = (time.time() - t1) * 1000
        tot += ms
        cv2.imwrite("/root/ip2/pt_%d.png" % i, patch)
        print("  NPU cand%d  p=%s  %.2fms"
              % (i, ["%.3f" % p for p in pr], ms), flush=True)
    print("NPU 总 %.2fms  平均 %.2fms/候选" % (tot, tot / max(1, len(cands))), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
