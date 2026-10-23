# -*- coding: utf-8 -*-
"""用「真实标准差」模型重算 CFAR 参考图（与 cfar_threshold_stream.v 的整数判决逐位一致）。

背景：PS 侧基线 detect_v1.py 用的阈值是
    mu = boxFilter(img,(31,31)); mu2 = boxFilter(img²,(31,31))
    sd = sqrt(mu2 - mu²)
    thr = mu + k*sd + floor        (k=4.0, floor=3.0)
早期硬件用 MAD 近似（k=5, floor=3），常数差 1.4826 倍，候选表对不上 → 改真实 std。

硬件不开方，判决等价写成：
    L = x*A - S1 - floor*A
    detect = (L > 0) and (L² > k²*(A*S2 - S1²))
本脚本同时算出「整数判决」和「浮点判决」，两者差异应为 0（用来验证定点等价性）。

产出：
  pl/sim/ref_cfar.hex      ← 输入 pl/sim/input_cfar.hex        (64×64)
  pl/sim/ref_cfar_128.hex  ← 输入 pl/sim/output_tophat_128.hex (128×72)

注意：窗口裁剪用「贴合图像边界」（max/min），与 RTL 一致；PS 侧 OpenCV 的
boxFilter 默认是 BORDER_REFLECT，边界一圈本来就不同，属于已知差异，不在此处模仿。
"""
import os
import sys

import numpy as np

sys.stdout.reconfigure(encoding='utf-8')

HALF = 15
K = 4
FLOOR = 3

SIM = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "sim"))


def load_hex(name):
    with open(os.path.join(SIM, name)) as f:
        return np.array([int(x, 16) for x in f.read().split()], dtype=np.int64)


def rect_sum(ii, y1, y2, x1, x2):
    return ii[y2 + 1, x2 + 1] - ii[y1, x2 + 1] - ii[y2 + 1, x1] + ii[y1, x1]


def cfar_std(img_flat, W, H):
    img = img_flat.reshape(H, W)
    ii1 = np.zeros((H + 1, W + 1), np.int64)
    ii2 = np.zeros((H + 1, W + 1), np.int64)
    ii1[1:, 1:] = img.cumsum(0).cumsum(1)
    ii2[1:, 1:] = (img * img).cumsum(0).cumsum(1)

    r = np.arange(H, dtype=np.int64)[:, None]
    c = np.arange(W, dtype=np.int64)[None, :]
    y1 = np.maximum(r - HALF, 0)
    y2 = np.minimum(r + HALF, H - 1)
    x1 = np.maximum(c - HALF, 0)
    x2 = np.minimum(c + HALF, W - 1)
    A = (y2 - y1 + 1) * (x2 - x1 + 1)

    S1 = rect_sum(ii1, y1, y2, x1, x2)
    S2 = rect_sum(ii2, y1, y2, x1, x2)

    # ① 整数判决（= RTL 的平方比较）
    L = img * A - S1 - FLOOR * A
    var_n = A * S2 - S1 * S1
    det_int = (L > 0) & (L * L > K * K * var_n)

    # ② 浮点判决（= PS 侧 detect_v1.py 的语义）
    mu = S1 / A
    var = np.maximum(S2 / A - mu * mu, 0.0)
    sd = np.sqrt(var)
    det_flt = img > (mu + K * sd + FLOOR)

    return det_int, det_flt


def build(in_name, out_name, W, H, tag):
    flat = load_hex(in_name)
    assert flat.size == W * H, "%s 像素数 %d != %d" % (in_name, flat.size, W * H)
    det_int, det_flt = cfar_std(flat, W, H)
    out = (det_int.astype(np.uint8) * 255).reshape(-1)
    with open(os.path.join(SIM, out_name), "w") as f:
        for v in out:
            f.write("%02X\n" % int(v))
    same = int((det_int == det_flt).sum())
    print("[%s] %s(%d×%d) → %s：检出 %d 像素；整数/浮点判决一致 %d/%d，不一致 %d"
          % (tag, in_name, W, H, out_name, int(det_int.sum()), same, W * H, W * H - same))


if __name__ == '__main__':
    build("input_cfar.hex", "ref_cfar.hex", 64, 64, "cfar64")
    build("output_tophat_128.hex", "ref_cfar_128.hex", 128, 72, "cfar128")
