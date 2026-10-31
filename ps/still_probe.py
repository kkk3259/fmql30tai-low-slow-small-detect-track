#!/usr/bin/env python3
"""把一张静止图直接喂给 PL，看检测器到底能不能检出画面里的方块。

用途：判断“框不出来”是场景/尺寸问题，还是相机->链路的问题。
"""
import os, sys, time
import numpy as np
import cv2

sys.path.insert(0, "/root/ip2")
import cam_pipe as cp


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--cap":
        # 直接从相机抓一帧（不含 HUD，和真正送 PL 的图一样），存成 still.png
        cap = cv2.VideoCapture(0)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        for _ in range(4):
            ok, f = cap.read()
        cap.release()
        if not ok:
            print("抓图失败")
            return
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)[60:420, :]
        cv2.imwrite("/root/ip2/still.png", g)
        print("抓图存到 /root/ip2/still.png  %dx%d" % (g.shape[1], g.shape[0]))
        path = "/root/ip2/still.png"
    else:
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

    stretch = int(os.environ.get("STRETCH", "0"))
    for g in gammas:
        if g != 1.0:
            lut = np.array([min(255, int(255 * ((i / 255.0) ** g))) for i in range(256)], np.uint8)
            frame = lut[img]
        else:
            frame = img
        if stretch == 1:
            lo, hi = np.percentile(frame, (1, 99))
            if hi > lo + 8:
                frame = np.clip((frame.astype(np.float32) - lo) * (255.0 / (hi - lo)), 0, 255).astype(np.uint8)
        elif stretch == 2:
            frame = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(frame)
        st, cands, dt = hw.run(frame)
        print("\n[gamma %.2f] STATUS=0x%08X  PL=%.2f ms  候选 %d"
              % (g, st, dt, len(cands)))
        for c in cands[:12]:
            print("   (%3d,%3d) area=%-4d peak=%-4d" % (c["x"], c["y"], c["area"], c["peak"]))


if __name__ == "__main__":
    main()
