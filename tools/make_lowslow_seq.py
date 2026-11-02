# -*- coding: utf-8 -*-
"""
把"大目标"视频转成"低小慢"测试序列（裁剪 + 缩放 + 限帧）

为什么需要：Pexels 上的无人机视频里，目标往往占几十上百像素 —— 那是"大目标"，
直接跑我们的链路只能验证"功能通不通"，验证不了"低小慢"这个难点。
本工具把画面裁出一小块并缩放，让目标只剩几个像素，才是真实工作条件。

三步用法：
  ① 先预览：抽 3 帧存成图片，看看目标在哪、多大
       python tools\\make_lowslow_seq.py --src D:\\lowslow\\data\\real\\raw.mp4 --probe
  ② 生成：给出裁剪框（x,y,w,h）和目标输出尺寸
       python tools\\make_lowslow_seq.py --src ...\\raw.mp4 --crop 800,400,480,270 `
              --frames 900 --out D:\\lowslow\\data\\real\\drone_lowslow.mp4
  ③ 标注 + 评测（用现成工具）
       python tools\\mark_gt.py --src ...\\drone_lowslow.mp4 --step 15
       python baseline\\track_v2.py --src ...\\drone_lowslow.mp4

关于"目标变多小"的换算（重要）：
    目标在输出图里的像素 = 原图目标像素 × (输出宽 / 裁剪宽)
    例如：原图目标 60px，裁剪宽 480，输出宽 1280  ->  60 × (1280/480) = 160px   变大了
    想要变小，要【裁剪小区域 + 输出尺寸不变】：裁剪宽 480、输出 640 -> 60 × (640/480) = 80px
    更彻底：先在预览里量出目标像素，再按公式反推需要的裁剪框。
    经验值：目标在【处理分辨率(640×360)】里 2~4 px 最合适。
"""
import argparse
import os
import sys

import cv2
import numpy as np


def probe(src, n_show=3, out_dir=None):
    """抽几帧存图，方便肉眼看目标位置与大小"""
    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        raise SystemExit("打不开视频：" + src)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print("")
    print("=== 视频信息 ===")
    print("  分辨率 : {}x{}".format(w, h))
    print("  帧率   : {:.1f} fps".format(fps))
    print("  总帧数 : {}  (时长 {:.1f} 秒)".format(total, total / fps if fps else 0))
    print("")
    if out_dir is None:
        out_dir = os.path.dirname(os.path.abspath(src))
    os.makedirs(out_dir, exist_ok=True)
    saved = []
    for k in range(n_show):
        idx = int(total * (k + 1) / (n_show + 1))
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, fr = cap.read()
        if not ok:
            continue
        p = os.path.join(out_dir, "_probe_f{}.jpg".format(idx))
        cv2.imwrite(p, fr)
        saved.append(p)
        print("  抽帧 帧{} -> {}".format(idx, p))
    cap.release()
    print("")
    print("  提示：用图片查看器打开上面几帧，用画图/截图工具量一下目标占多少像素，")
    print("       再用 --crop 给出裁剪框（建议让目标落在裁剪区中心）。")
    return saved


def convert(src, out, crop, out_size, frames, fps_out):
    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        raise SystemExit("打不开视频：" + src)
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30

    if crop:
        cx, cy, cw, ch = crop
        cx = max(0, min(cx, src_w - 2))
        cy = max(0, min(cy, src_h - 2))
        cw = max(2, min(cw, src_w - cx))
        ch = max(2, min(ch, src_h - cy))
    else:
        cx, cy, cw, ch = 0, 0, src_w, src_h

    if out_size:
        ow, oh = out_size
    else:
        ow, oh = cw, ch

    scale_x = ow / float(cw)
    scale_y = oh / float(ch)
    print("")
    print("=== 转换参数 ===")
    print("  源      : {}x{} @ {:.1f}fps".format(src_w, src_h, src_fps))
    print("  裁剪框  : x={} y={} w={} h={}".format(cx, cy, cw, ch))
    print("  输出    : {}x{}  (x 缩放 {:.2f} 倍)".format(ow, oh, scale_x))
    print("  限帧    : {}".format(frames if frames else "不限制"))
    print("")
    if scale_x < 1.0:
        print("  说明：输出比裁剪区小 -> 目标会被【缩小】，适合做「低小慢」测试 ")
    elif scale_x > 1.0:
        print("  说明：输出比裁剪区大 -> 目标会被【放大】(警告：这是在放大细节，不利于模拟小目标)")
    print("")

    vw = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*"mp4v"), fps_out, (ow, oh))
    if not vw.isOpened():
        raise SystemExit("输出写入器打不开：" + out)

    i = 0
    while True:
        if frames and i >= frames:
            break
        ok, fr = cap.read()
        if not ok:
            break
        c = fr[cy:cy + ch, cx:cx + cw]
        if (ow, oh) != (cw, ch):
            c = cv2.resize(c, (ow, oh), interpolation=cv2.INTER_AREA if scale_x < 1 else cv2.INTER_LINEAR)
        vw.write(c)
        i += 1
    cap.release()
    vw.release()

    print("  [OK] 已生成: {}  ({} 帧, {}x{})".format(out, i, ow, oh))
    print("")
    print("  下一步：")
    print("    1) 标注真值：python tools\\mark_gt.py --src \"{}\" --step 15".format(out))
    print("    2) 跑评测　：python baseline\\track_v2.py --src \"{}\"".format(out))
    print("    3) 看效果　：打开 results\\track_v2.mp4")


def main():
    ap = argparse.ArgumentParser(description="大目标视频 -> 低小慢测试序列（裁剪+缩放+限帧）")
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", default="", help="输出视频路径")
    ap.add_argument("--crop", default="", help="裁剪框 x,y,w,h（不给则用全画面）")
    ap.add_argument("--out-size", default="1280,720", help="输出尺寸 W,H（默认 1280,720）")
    ap.add_argument("--frames", type=int, default=900, help="最多取多少帧（默认 900 = 30秒@30fps）")
    ap.add_argument("--fps", type=int, default=30, help="输出帧率")
    ap.add_argument("--probe", action="store_true", help="只抽帧预览，不转换")
    a = ap.parse_args()

    if a.probe:
        probe(a.src)
        return

    if not a.out:
        base = os.path.splitext(a.src)[0]
        a.out = base + "_lowslow.mp4"

    crop = None
    if a.crop:
        vals = [int(x) for x in a.crop.replace(" ", "").split(",")]
        if len(vals) != 4:
            raise SystemExit("--crop 需要 4 个数：x,y,w,h")
        crop = vals

    osize = None
    if a.out_size:
        osize = tuple(int(x) for x in a.out_size.replace(" ", "").split(","))

    convert(a.src, a.out, crop, osize, a.frames, a.fps)


if __name__ == "__main__":
    main()
