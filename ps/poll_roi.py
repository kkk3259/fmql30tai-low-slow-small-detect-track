#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""poll_roi.py —— 独立进程轮询 8099 的 /info（避免被 icraft 的 C 调用饿死 GIL）。"""
import json
import sys
import time
import urllib.request

port = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
best = 0
for i in range(10):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/info" % port, timeout=5) as r:
            d = json.loads(r.read().decode("utf-8"))
        cs = d.get("cands") or []
        best = max(best, len(cs))
        print("PAGE_INFO fps=%.1f npu_ms=%.1f n=%d err=%r"
              % (d.get("fps", 0), d.get("npu_ms", 0), d.get("n", 0), d.get("err", "")))
        print("PAGE_CANDS %d" % len(cs))
        for c in cs[:6]:
            print("   x=%s y=%s area=%s p=%s" % (c.get("x"), c.get("y"),
                                                 c.get("area"), c.get("p")))
    except Exception as e:                                        # noqa: BLE001
        print("poll fail %s" % e)
    time.sleep(2)
print("VERDICT PAGE-ROI-%s" % ("OK" if best > 0 else "FAIL"))
