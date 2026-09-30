# -*- coding: utf-8 -*-
"""
关键帧标注 + 线性插值 -> 生成逐帧真值 CSV（供 v1/v2 评测使用）

为什么这样设计：低小慢目标（气球/风筝/小四轴）在画面里基本是"缓慢匀速"运动，
所以只要标几个关键帧，中间每帧的坐标用线性插值补出来即可 —— 比逐帧手标省 10 倍力气。

用法 A：鼠标交互标注（推荐）
    python tools\\mark_gt.py --src D:\\lowslow\\data\\seq01.mp4
    左键点目标中心 = 记录该帧并前进 step 帧
    a / d = 前后单帧微调；j / k = 前后跳 step 帧；q = 结束并保存

用法 B：直接给关键点（目标运动很规整时最省事）
    python tools\\mark_gt.py --src D:\\lowslow\\data\\seq01.mp4 --points "0:320,360;149:500,412"

输出：与视频同名的 xxx_gt.csv，格式 frame,x,y（v1/v2 会自动读取）
"""
import argparse
import csv
import os

import cv2
import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="视频文件路径")
    ap.add_argument("--out", default="", help="输出 CSV（默认与视频同名 + _gt.csv）")
    ap.add_argument("--step", type=int, default=15, help="每次点击后前进多少帧")
    ap.add_argument("--points", default="", help='关键点，格式 "帧: x,y;帧:x,y"（不用鼠标时用）')
    a = ap.parse_args()

    cap = cv2.VideoCapture(a.src)
    if not cap.isOpened():
        raise SystemExit("打不开视频：" + a.src)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print("[输入] {}  {}x{}  {:.1f}fps  共 {} 帧".format(a.src, w, h, fps, n))

    keys = []   # (frame, x, y)

    if a.points:
        for seg in a.points.split(";"):
            seg = seg.strip()
            if not seg:
                continue
            fr, xy = seg.split(":")
            x, y = xy.split(",")
            keys.append((int(fr), float(x), float(y)))
        print("[关键点] 读入 {} 个（来自命令行）".format(len(keys)))
    else:
        cur = [0]

        def on_mouse(event, x, y, flags, param):
            if event == cv2.EVENT_LBUTTONDOWN:
                keys.append((cur[0], float(x), float(y)))
                print("  标记 帧{} -> ({}, {})   累计 {} 个点".format(cur[0], x, y, len(keys)))
                cur[0] = min(cur[0] + a.step, n - 1)

        cv2.namedWindow("mark_gt", cv2.WINDOW_NORMAL)
        cv2.setMouseCallback("mark_gt", on_mouse)
        print("")
        print("操作方法：左键点目标中心 -> 自动前进 {} 帧；a/d 单帧；j/k 跳 {} 帧；q 结束保存".format(a.step, a.step))
        while True:
            cap.set(cv2.CAP_PROP_POS_FRAMES, cur[0])
            ok, fr = cap.read()
            if not ok:
                break
            disp = fr.copy()
            cv2.putText(disp, "frame {}  (已标 {} 点)  L-click=mark  a/d=1frame  j/k={}frames  q=save".format(
                cur[0], len(keys), a.step), (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            for (kf, kx, ky) in keys[-5:]:
                cv2.circle(disp, (int(kx), int(ky)), 7, (0, 255, 0), 2)
            cv2.imshow("mark_gt", disp)
            k = cv2.waitKey(20) & 0xFF
            if k == ord('q'):
                break
            elif k == ord('a'):
                cur[0] = max(cur[0] - 1, 0)
            elif k == ord('d'):
                cur[0] = min(cur[0] + 1, n - 1)
            elif k == ord('j'):
                cur[0] = min(cur[0] + a.step, n - 1)
            elif k == ord('k'):
                cur[0] = max(cur[0] - a.step, 0)
        cv2.destroyAllWindows()

    if len(keys) < 2:
        raise SystemExit("关键点少于 2 个，无法插值（已记录 {} 个）".format(len(keys)))

    keys.sort()
    frs = np.array([k[0] for k in keys], dtype=float)
    xs = np.array([k[1] for k in keys], dtype=float)
    ys = np.array([k[2] for k in keys], dtype=float)
    f0, f1 = int(frs[0]), int(frs[-1])
    allf = np.arange(f0, f1 + 1)
    X = np.interp(allf, frs, xs)
    Y = np.interp(allf, frs, ys)

    out = a.out or (os.path.splitext(a.src)[0] + "_gt.csv")
    with open(out, "w", newline="") as f:
        wtr = csv.writer(f)
        wtr.writerow(["frame", "x", "y"])
        for i, fnum in enumerate(allf):
            wtr.writerow([int(fnum), round(float(X[i]), 1), round(float(Y[i]), 1)])

    print("")
    print("关键点    : {} 个".format(len(keys)))
    print("插值生成  : {} 行逐帧真值（帧 {} ~ {}）".format(len(allf), f0, f1))
    print("已保存    : {}".format(os.path.abspath(out)))
    print("")
    print("下一步直接跑评测：")
    print("  python baseline\\track_v2.py --src " + a.src)


if __name__ == "__main__":
    main()
