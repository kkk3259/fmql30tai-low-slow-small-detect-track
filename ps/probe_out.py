# -*- coding: utf-8 -*-
"""probe_out.py —— 确认 NPU 输出能否按偏移/局部读取，以及 OUT0 的内存布局。"""
import sys
import time

import numpy as np

sys.path.insert(0, "/root/ip2")
from icraft.xir import Network  # noqa
import icraft.xrt as xrt  # noqa
from icraft.zg330backend import ZG330Backend  # noqa
from icraft.host_backend import HostBackend  # noqa

MODEL = "/root/npu/yolo11n_drone_trunc_ZG"

net = Network.CreateFromJsonFile(MODEL + ".json")
net.lazyLoadParamsFromFile(MODEL + ".raw", 0)
dev = xrt.Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
sess = xrt.Session.Create([ZG330Backend, HostBackend], net.view(0),
                          [dev, xrt.HostDevice.Default()])
sess.apply()

img = np.zeros((1, 640, 640, 3), np.uint8)
t = sess.getInputTensor(0)
t.write(img.tobytes(), 0, img.size)
outs = sess.forward([t])
print("n_out =", len(outs))

o0 = outs[0]
print("out0 dtype:", str(o0.dtype())[:120])

n_full = 64 * 8400
for n in (n_full, 42000, 5 * 8400, 8400):
    buf = bytearray(n)
    t0 = time.time()
    try:
        o0.read(buf, 0, n)
        dt = (time.time() - t0) * 1000
        print("read %7d B -> %.2f ms   head=%s" %
              (n, dt, list(buf[:8])))
    except Exception as e:
        print("read %7d B -> FAIL %s" % (n, str(e)[:80]))

# 尝试偏移读取（判断是通道优先还是锚点优先）
try:
    buf = bytearray(8400)
    o0.read(buf, 8400, 8400)          # 第二段
    print("offset read OK  head=", list(buf[:8]))
except Exception as e:
    print("offset read FAIL:", str(e)[:100])
