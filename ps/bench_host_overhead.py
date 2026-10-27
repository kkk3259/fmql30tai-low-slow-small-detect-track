# -*- coding: utf-8 -*-
"""拆解 forward 的 host 开销：numpy2Tensor / forward 内部 / read 各占多少"""
import sys, time
sys.path.insert(0, '/root/pywork')
from modelzoo_utils.pyrtutils import *
from icraft import xrt
import numpy as np, cv2

network = loadNetwork('/root/a_model/yolo11n_drone_trunc_ZG.json',
                      '/root/a_model/yolo11n_drone_trunc_ZG.raw')
netinfo = Netinfo(network)
device  = xrt.Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
session = initSession('zg330', network, device, ocm_option=4, mmuMode=bool(netinfo.mmu),
                      open_speedmode=False, open_compressFtmp=False)
session.enableTimeProfile(True); session.apply()

b1 = np.zeros(1*64*8400*4, np.uint8)
b2 = np.zeros(1*1*8400*4,  np.uint8)
img = np.random.randint(0, 255, (640,640,3), dtype=np.uint8)

def bench(fn, n=10):
    for _ in range(2): fn()          # warmup
    t = []
    for _ in range(n):
        t0 = time.perf_counter(); fn(); t.append((time.perf_counter()-t0)*1e3)
    return float(np.mean(t)), float(np.min(t)), float(np.max(t))

print("  ════ 各环节单独计时（10 次均值/最小/最大，ms）════")

# ① numpy2Tensor 构造
def f_tensor():
    return numpy2Tensor(img.reshape(1,640,640,3), network)
m, lo, hi = bench(f_tensor)
print("  ① numpy2Tensor 构造      : %6.2f  [%.2f ~ %.2f]" % (m, lo, hi))

# ② 整次 forward（含 tensor 构造）
def f_full():
    ten = numpy2Tensor(img.reshape(1,640,640,3), network)
    out = session.forward([ten])
    device.reset(1)
    return out
m2, lo2, hi2 = bench(f_full)
print("  ② 完整 forward + reset   : %6.2f  [%.2f ~ %.2f]" % (m2, lo2, hi2))

# ③ 复用同一个 tensor，只 forward
ten = numpy2Tensor(img.reshape(1,640,640,3), network)
def f_reuse():
    out = session.forward([ten])
    device.reset(1)
    return out
m3, lo3, hi3 = bench(f_reuse)
print("  ③ 复用 tensor + forward  : %6.2f  [%.2f ~ %.2f]" % (m3, lo3, hi3))

# ④ forward + read（不 reset）
def f_read():
    out = session.forward([ten])
    out[0].read(memoryview(b1),0,b1.size)
    out[1].read(memoryview(b2),0,b2.size)
    device.reset(1)
m4, lo4, hi4 = bench(f_read)
print("  ④ forward + read + reset : %6.2f  [%.2f ~ %.2f]" % (m4, lo4, hi4))

# ⑤ 只 reset
def f_reset():
    device.reset(1)
m5, lo5, hi5 = bench(f_reset, n=20)
print("  ⑤ 仅 device.reset(1)     : %6.2f  [%.2f ~ %.2f]" % (m5, lo5, hi5))

# ⑥ 只 read（用上一次的输出）
out = session.forward([ten])
def f_readonly():
    out[0].read(memoryview(b1),0,b1.size)
    out[1].read(memoryview(b2),0,b2.size)
m6, lo6, hi6 = bench(f_readonly, n=20)
print("  ⑥ 仅 read 2.2MB          : %6.2f  [%.2f ~ %.2f]" % (m6, lo6, hi6))

print()
print("  ════ 推断的构成 ════")
print("  forward 净耗时（③-⑤）  = %.2f ms" % (m3 - m5))
print("  其中硬件（timeProfile）= 7.955 ms（已知实测）")
print("  ⇒ host 侧（DMA 写入 + 同步等待）≈ %.2f ms" % (m3 - m5 - 7.955))
print()
print("  tensor 构造开销（①）    = %.2f ms  ← 可省（复用 tensor）" % m)
print("  read 开销（⑥）          = %.2f ms" % m6)

try: device.reset(1)
except Exception: pass
xrt.Device.Close(device)
print("DONE_HOST")
