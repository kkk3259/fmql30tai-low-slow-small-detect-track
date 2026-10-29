# track_lag_test.py —— 合成移动目标：量“外推前/后”的框与目标中心偏差
import sys
sys.path.insert(0, "/root/ip2")
import time
import numpy as np
from cam_pipe import HW, Tracker, W, H

def frame(x, y, s=10):
    f = np.full((H, W), 30, np.uint8)
    f[y:y+s, x:x+s] = 240
    return f

def main():
    hw = HW(); trk = Tracker()
    print("step  true_x  track_x  err_before  err_after")
    eb = ea = n = 0
    for i in range(24):
        tx = 40 + i * 16          # 每帧右移 16 px（约 480 px/s @30fps）
        ty = 180
        st, cands, dt = hw.run(frame(tx, ty))
        tracks = trk.update(cands, 29.0)
        if not tracks:
            continue
        t = max(tracks, key=lambda k: k["hits"])
        ex = t["x"] + t["vx"] * 3.0        # 与 cam_pipe 相同的 3 帧外推
        e0 = abs(t["x"] - tx); e1 = abs(ex - tx)
        eb += e0; ea += e1; n += 1
        if i % 4 == 0 or i > 19:
            print("%-5d %-7d %-8.1f %-11.1f %.1f" % (i, tx, t["x"], e0, e1))
    print()
    print("=== 命中 %d 帧：外推前平均偏差 %.1f px，外推后 %.1f px ===" % (n, eb / max(n, 1), ea / max(n, 1)))

main()
