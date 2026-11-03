#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_page_roi.py —— 假相机 + ROI 模式端到端验证。

假相机把 t4（四架无人机）缩到 45% 再贴进 640×480 画面，
这样无人机在画面里只有 ~15~35 px —— 和真实远距离目标一致，
PL 才有可能把它们作为候选抓出来，ROI 模式才有意义。
"""
import sys
import os
import threading
import time
import urllib.request
import json

import cv2
import numpy as np

PORT = 8099
SRC = "/root/ip2/t4_fourdrones.png"
SCALE = 0.45

_big = cv2.imread(SRC)
_sw, _sh = int(_big.shape[1] * SCALE), int(_big.shape[0] * SCALE)
_small = cv2.resize(_big, (_sw, _sh), interpolation=cv2.INTER_AREA)
FRAME = np.full((480, 640, 3), 40, np.uint8)
_y0, _x0 = (480 - _sh) // 2, (640 - _sw) // 2
FRAME[_y0:_y0 + _sh, _x0:_x0 + _sw] = _small
print("fake frame: drone scale %.2f  (%dx%d at %d,%d)" % (SCALE, _sw, _sh, _x0, _y0))

cnt = {"n": 0}


class FakeCap(object):
    def __init__(self, *a, **k):
        pass

    def isOpened(self):
        return True

    def set(self, *a, **k):
        return True

    def get(self, prop):
        return {3: 640.0, 4: 480.0}.get(prop, 0.0)

    def read(self):
        cnt["n"] += 1
        time.sleep(0.012)
        return True, FRAME.copy()

    def release(self):
        pass


cv2.VideoCapture = FakeCap

sys.argv = ["cam3d_pipe.py", "--port", str(PORT), "--npu", "1",
            "--mode", "roi", "--quality", "60", "--push-every", "1"]

import cam3d_pipe  # noqa: E402


def poll():
    time.sleep(14)
    for _ in range(6):
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/info" % PORT, timeout=5) as r:
                d = json.loads(r.read().decode("utf-8"))
            print("PAGE_INFO frames=%d npu_ms=%.1f n=%d err=%r"
                  % (cnt["n"], d.get("npu_ms", 0), d.get("n", 0), d.get("err", "")))
            cs = d.get("cands") or []
            print("PAGE_CANDS %d" % len(cs))
            for c in cs[:6]:
                print("   x=%s y=%s area=%s p=%s" % (c.get("x"), c.get("y"),
                                                     c.get("area"), c.get("p")))
            print("VERDICT PAGE-ROI-%s" % ("OK" if len(cs) > 0 else "FAIL"))
            return
        except Exception as e:                                   # noqa: BLE001
            print("poll fail", e)
        time.sleep(2)


if os.environ.get("NOPOLL") != "1":
    threading.Thread(target=poll, daemon=True).start()
cam3d_pipe.main()
