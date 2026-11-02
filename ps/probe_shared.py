# -*- coding: utf-8 -*-
"""probe_shared.py —— 验证「共享 dev 时 YOLO 建不出来」的假设。

对比两种构造：
  A) Yolo()           自建 Device（offline 脚本走这条，实测能跑）
  B) Yolo(dev=dev)    共享 Device（web 服务走这条，报 write 失败）
"""
import sys
import time

import numpy as np

sys.path.insert(0, "/root/ip2")
import icraft.xrt as xrt  # noqa
from yolo_det import Yolo  # noqa

img = np.full((640, 640, 3), 114, np.uint8)
cv = np.full((480, 640), 114, np.uint8)


def run(tag, **kw):
    try:
        y = Yolo(**kw)
        print(tag, "ctor OK  tt=", y.tt)
        t0 = time.time()
        out = y.detect(cv)
        print(tag, "detect OK  n=%d  %.1f ms" % (len(out), (time.time() - t0) * 1000))
    except Exception as e:
        print(tag, "FAIL", str(e)[:150])


run("A(own dev) ")
dev = xrt.Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
run("B(shared) ", dev=dev)
