#!/usr/bin/env python3
"""把一张静止图直接喂给 PL，看检测器到底能不能检出画面里的方块。

用途：判断“框不出来”是场景/尺寸问题，还是相机->链路的问题。
"""
import sys, time
import numpy as np
import cv2

sys.path.insert(0, "/root/ip2")
import cam_pipe as cp


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "/root/ip2/still.png"
    gammas = [1.0, 0.35, 0.08]
    if len(sys.argv) > 2:
        gammas = [float(x) for x in sys.argv[2].split(",")]

    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        print("读不到", path)
        return
    if img.shape[:2] != (360, 640):
        img = cv2.resize(img, (640, 360), interpolation=cv2.INTER_AREA)
    print("图像 %dx%d  灰度范围 %d~%d" % (img.shape[1], img.shape[0], img.min(), img.max()))

    cp.GAMMA = 1.0
    hw = cp.HW()
    print("VERSION = 0x%08X" % hw.rd(0x14))

    for g in gammas:
        if g != 1.0:
            lut = np.array([min(255, int(255 * ((i / 255.0) ** g))) for i in range(256)], np.uint8)
            frame = lut[img]
        else:
            frame = img
        st, cands, dt = hw.run(frame)
        print("\n[gamma %.2f] STATUS=0x%08X  PL=%.2f ms  候选 %d"
              % (g, st, dt, len(cands)))
        for c in cands[:12]:
            print("   (%3d,%3d) area=%-4d peak=%-4d" % (c["x"], c["y"], c["area"], c["peak"]))


if __name__ == "__main__":
    main()
