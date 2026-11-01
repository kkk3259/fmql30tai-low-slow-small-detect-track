#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_page_yolo.py —— 端到端验证"网页 /info 里的框确实来自 yolo11n"。

做法：把 cv2.VideoCapture 换成一个"假相机"，它每帧返回 t4_fourdrones.png
缩放成的 640x480 图像；然后用 cam3d_pipe 的真实 main() 起服务（端口 8099），
读 /info 看 n 与 cands。这样走的是页面完全相同的代码路径。

用法：python3 test_page_yolo.py
"""
import json
import sys
import threading
import time
import urllib.request

import cv2
import numpy as np

sys.path.insert(0, "/root/ip2")

IMG = "/root/ip2/t4_fourdrones.png"
PORT = 8099

_base = cv2.imread(IMG)
if _base is None:
    raise SystemExit("cannot read %s" % IMG)


def _fit(img, w=640, h=480):
    """等比缩放后居中填充到 w x h（模拟相机 640x480 视野）。"""
    ih, iw = img.shape[:2]
    s = min(w / float(iw), h / float(ih))
    nw, nh = int(iw * s), int(ih * s)
    r = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
    out = np.zeros((h, w, 3), np.uint8)
    y0, x0 = (h - nh) // 2, (w - nw) // 2
    out[y0:y0 + nh, x0:x0 + nw] = r
    return out


FRAME = _fit(_base)


class FakeCap(object):
    def __init__(self, *a, **k):
        self.opened = True

    def isOpened(self):
        return True

    def set(self, *a, **k):
        return True

    def get(self, prop):
        if prop == cv2.CAP_PROP_FRAME_WIDTH:
            return 640
        if prop == cv2.CAP_PROP_FRAME_HEIGHT:
            return 480
        if prop == cv2.CAP_PROP_FPS:
            return 30
        return 0

    def read(self):
        return True, FRAME.copy()

    def release(self):
        pass


cv2.VideoCapture = FakeCap

import cam3d_pipe as CP  # noqa: E402  必须在打补丁之后导入

sys.argv = ["cam3d_pipe.py", "--port", str(PORT), "--npu", "1", "--yolo", "1",
            "--quality", "60", "--push-every", "1"]

threading.Thread(target=CP.main, daemon=True).start()

info = None
for _ in range(120):                     # 最多等 40 s（含模型加载）
    time.sleep(0.5)
    try:
        info = json.load(urllib.request.urlopen("http://127.0.0.1:%d/info" % PORT, timeout=3))
        if info.get("frames", 0) >= 8:
            break
    except Exception:
        pass

if info is None:
    raise SystemExit("PAGE_FAIL no /info")

print("PAGE_INFO frames=%s fps=%.1f npu_ms=%.1f n=%s err=%r"
      % (info.get("frames"), info.get("fps", 0), info.get("npu_ms", 0),
         info.get("n"), info.get("err")), flush=True)

cs = info.get("cands") or []
print("PAGE_CANDS %d" % len(cs), flush=True)
for c in cs[:10]:
    print("   x=%s y=%s area=%s peak=%s p=%s"
          % (c.get("x"), c.get("y"), c.get("area"), c.get("peak"), c.get("p")), flush=True)

print("VERDICT %s" % ("PAGE-YOLO-OK" if len(cs) >= 3 else "PAGE-YOLO-FAIL"), flush=True)
