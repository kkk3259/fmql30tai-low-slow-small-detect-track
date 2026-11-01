#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""phase_cal.py —— 三域检测器的列相位自校准。

背景：三域适配层 ip2_user_op.v 没有"每帧清 FIFO"的动作，上一帧尾部残留 0 或
64 字节（=64 像素）会让整幅光栅右移。残留量取决于启动后的 AXI 时序，因此
**同一进程内相位固定，重启后可能翻转**。软件侧每次启动量一次即可。

用法：
    from phase_cal import calibrate
    sh = calibrate(pl, W, H)      # 返回 0~W-1 的列偏移
    ...
    c["x"] = (c["x"] + sh) % W
"""
import cv2
import numpy as np

# 校准图：纯黑底 + 中心一个 7x7 白方块（尺寸落在 PL 的 6~28px 窗口内）
CAL_X, CAL_Y, CAL_SIDE = 320, 180, 7


def _cal_image(W, H):
    img = np.zeros((H, W), np.uint8)
    x0, y0 = CAL_X - CAL_SIDE // 2, CAL_Y - CAL_SIDE // 2
    img[y0:y0 + CAL_SIDE, x0:x0 + CAL_SIDE] = 230
    return img


def calibrate(pl, W=640, H=360, verbose=True):
    """跑一次校准图，返回列偏移 shift（加在检测出的 x 上）。"""
    img = _cal_image(W, H)
    cands, _st, _dt = pl.run(img)
    good = [c for c in cands if c.get("peak", 0) >= 20]
    if not good:
        if verbose:
            print("[cal] 无候选，相位按 0 处理", flush=True)
        return 0
    c = max(good, key=lambda z: z["peak"])
    shift = (CAL_X - c["x"]) % W
    # 大于半个画面视为反向绕回，按 0 处理更安全
    if shift > W // 2:
        shift = shift - W
    if verbose:
        print("[cal] 校准图候选 x=%d y=%d area=%d peak=%d -> shift=%+d"
              % (c["x"], c["y"], c["area"], c["peak"], shift), flush=True)
    return shift


if __name__ == "__main__":
    import sys

    sys.path.insert(0, "/root/ip2")
    from cam3d_test import PL3D  # noqa: E402

    _pl = PL3D()
    print("shift =", calibrate(_pl))
