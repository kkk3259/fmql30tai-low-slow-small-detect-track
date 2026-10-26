# -*- coding: utf-8 -*-
import sys, time
sys.path.insert(0, '/root/pywork')
from modelzoo_utils.pyrtutils import *
from icraft import xrt
import numpy as np

network = loadNetwork('/root/a_model/yolo11n_drone_trunc_ZG.json',
                      '/root/a_model/yolo11n_drone_trunc_ZG.raw')
netinfo = Netinfo(network)
device  = xrt.Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
session = initSession('zg330', network, device, ocm_option=4, mmuMode=bool(netinfo.mmu),
                      open_speedmode=False, open_compressFtmp=False)
session.enableTimeProfile(True); session.apply()

img = np.random.randint(0,255,(640,640,3), dtype=np.uint8)
src = np.ascontiguousarray(img).reshape(1,640,640,3)
nbytes = src.nbytes
b1 = np.zeros(1*64*8400*4, np.uint8); b2 = np.zeros(1*1*8400*4, np.uint8)

def bench(fn, n=10, warm=2):
    for _ in range(warm): fn()
    t=[]
    for _ in range(n):
        t0=time.perf_counter(); fn(); t.append((time.perf_counter()-t0)*1e3)
    return float(np.mean(t))

# A: 现状
def A():
    ten = numpy2Tensor(src, network)
    out = session.forward([ten])
    out[0].read(memoryview(b1),0,b1.size); out[1].read(memoryview(b2),0,b2.size)
    device.reset(1)
    return 1/(1+np.exp(-b2.view(np.float32))).max()
mA = bench(A)
cA = A()
print("  [A] 重建 tensor + fwd + read : %6.2f ms   cls_max=%.4f" % (mA, cA))

# B: 复用 tensor（write 后直接 forward，不调 setReady）
ten = numpy2Tensor(src, network)
raw = np.ascontiguousarray(src)
def B():
    ten.write(0, memoryview(raw), nbytes)
    out = session.forward([ten])
    out[0].read(memoryview(b1),0,b1.size); out[1].read(memoryview(b2),0,b2.size)
    device.reset(1)
    return 1/(1+np.exp(-b2.view(np.float32))).max()
try:
    mB = bench(B); cB = B()
    print("  [B] 复用 tensor + fwd + read : %6.2f ms   cls_max=%.4f" % (mB, cB))
    print("  ⇒ 提速 %.2f ms (%.0f%%)，结果一致性: %s"
          % (mA-mB, (mA-mB)/mA*100, "✓ 一致" if abs(cA-cB)<1e-6 else "✗ 不一致(%.6f vs %.6f)"%(cA,cB)))
except Exception as e:
    print("  [B] 失败: %s" % str(e).split(chr(10))[-1][:150])

# C: 复用 + 只换数据（模拟真实视频帧切换）
raw2 = np.ascontiguousarray(np.random.randint(0,255,(640,640,3),dtype=np.uint8).reshape(1,640,640,3))
def C():
    ten.write(0, memoryview(raw), nbytes)
    session.forward([ten]); device.reset(1)
    ten.write(0, memoryview(raw2), nbytes)
    session.forward([ten]); device.reset(1)
mC = bench(C, n=5)
print("  [C] 连续两帧不同数据(每帧) : %6.2f ms" % (mC/2))

try: device.reset(1)
except Exception: pass
xrt.Device.Close(device)
print("DONE")
