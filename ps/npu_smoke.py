# -*- coding: utf-8 -*-
"""npu_smoke.py —— NPU 冒烟测试（判断合并位流有没有伤到 AI_Mate 通路）

做三件事：
  1. 读 0x4000001C（NPU 侧寄存器）。若读出 0x00010000，说明 0x40000000 被我们的 IP 别名占了，
     NPU 根本没挂上 → 直接判 FAIL，不去跑 forward。
  2. 用 modelzoo 的 API 建会话（icraft 3.39.0 + /root/pywork/modelzoo_utils/pyrtutils）
  3. 一张 640×640 零图 forward 一次，打印耗时与输出形状

用法（板子）:
  python3 npu_smoke.py            # 默认模型 /root/a_model/yolo11n_drone_trunc_ZG.{json,raw}
  python3 npu_smoke.py --json ... --raw ...
"""
import argparse
import mmap
import os
import struct
import sys
import time

PYRT = "/root/pywork"
if PYRT not in sys.path:
    sys.path.insert(0, PYRT)

NPU_BASE = 0x40000000
OUR_MAGIC_VER = 0x00010000


def read_npu_probe():
    try:
        f = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
        m = mmap.mmap(f, 4096, offset=NPU_BASE)
        vals = {}
        for off in (0x00, 0x04, 0x1C, 0x20):
            vals[off] = struct.unpack_from("<I", m, off)[0]
        m.close()
        os.close(f)
        return vals
    except Exception as e:
        return {"err": repr(e)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="/root/a_model/yolo11n_drone_trunc_ZG.json")
    ap.add_argument("--raw", default="/root/a_model/yolo11n_drone_trunc_ZG.raw")
    ap.add_argument("--net", type=int, default=640)
    ap.add_argument("--runs", type=int, default=3)
    a = ap.parse_args()

    print("=== 1) NPU 地址探针 @0x%08X ===" % NPU_BASE)
    probe = read_npu_probe()
    for k, v in probe.items():
        if isinstance(k, int):
            print("  [0x%02X] = 0x%08X" % (k, v))
        else:
            print("  读失败: %s" % v)
    v1c = probe.get(0x1C)
    if v1c is None:
        print("VERDICT NPU_PROBE_FAIL（/dev/mem 读不到）")
        return 1
    if v1c == OUR_MAGIC_VER:
        print("VERDICT NPU_SHADOWED（0x4000001C == 我们的 VERSION，地址被别名，NPU 未挂上）")
        return 2
    print("  0x4000001C != 0x00010000 -> 不是我们的 IP 别名，继续")

    print("=== 2) 建会话 ===")
    t0 = time.time()
    try:
        import numpy as np
        from icraft import xrt
        from modelzoo_utils.pyrtutils import (Netinfo, initSession, loadNetwork,
                                              numpy2Tensor)
    except Exception as e:
        print("VERDICT IMPORT_FAIL: %r" % e)
        return 3

    network = loadNetwork(a.json, a.raw)
    netinfo = Netinfo(network)
    dev_url = "axi://zg330aiu?npu=0x%08X&dma=0x80000000" % NPU_BASE
    device = xrt.Device.Open(dev_url)
    session = initSession("zg330", network, device,
                          ocm_option=4, mmuMode=bool(netinfo.mmu),
                          open_speedmode=False, open_compressFtmp=False)
    session.enableTimeProfile(True)
    session.apply()
    print("  ops=%d  input=%s  mmu=%s  初始化 %.2f s"
          % (len(network.ops), netinfo.i_shape, netinfo.mmu, time.time() - t0))

    print("=== 3) forward x%d ===" % a.runs)
    ten = numpy2Tensor(np.zeros((1, a.net, a.net, 3), np.uint8), network)
    ts = []
    out = None
    for i in range(a.runs):
        t1 = time.time()
        try:
            out = session.forward([ten])
        except Exception as e:
            print("VERDICT FORWARD_FAIL: %r" % e)
            return 4
        dt = (time.time() - t1) * 1000.0
        ts.append(dt)
        print("  run %d: %.2f ms" % (i + 1, dt))

    print("  输出 %d 个：" % len(out))
    for i, o in enumerate(out):
        try:
            arr = o.read() if hasattr(o, "read") else np.asarray(o)
            print("    out[%d] shape=%s 前4=%s" % (i, getattr(arr, "shape", "?"),
                                                   np.asarray(arr).ravel()[:4]))
        except Exception as e:
            print("    out[%d] 读取失败: %r" % (i, e))
    avg = sum(ts) / len(ts)
    print("VERDICT NPU-OK  avg=%.2f ms  min=%.2f max=%.2f" % (avg, min(ts), max(ts)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
