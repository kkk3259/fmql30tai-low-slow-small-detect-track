#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""peek_json.py —— 看 cls128 / yolo11n 模型 json 里有没有类别名。"""
import json
import re
import sys

for p in ["/root/npu/cls128_drone_ZG.json",
          "/root/npu/yolo11n_drone_trunc_ZG.json"]:
    print("=" * 60)
    print(p)
    try:
        d = json.load(open(p))
    except Exception as ex:
        print("  load fail:", ex)
        continue
    print("  top keys:", list(d.keys())[:15])
    s = json.dumps(d)
    for kw in ("drone", "label", "class", "category", "name"):
        n = len(re.findall(kw, s, re.I))
        print("  '%s' 出现 %d 次" % (kw, n))
    # 把含 drone/class/label 的短片段打出来
    for m in re.finditer(r'"[^"]{0,40}(drone|label|class|category)[^"]{0,40}"', s, re.I):
        print("   >", m.group(0)[:120])
        if m.start() > 4000:
            break
