# -*- coding: utf-8 -*-
"""
公开数据集 -> 本项目的序列格式（mp4 + 逐帧真值 CSV）

为什么需要它：公开数据集多是「图片序列 + 框标注(x,y,w,h)」，
而我们的链路（detect_v1 / track_v2 / ps_app）吃的是「视频 + frame,x,y（中心坐标）」。
本工具做这个转换，并把框中心算出来。

支持的格式：
  --fmt antuav    Anti-UAV 结构：<root>/<seq>/visible.mp4 + <root>/<seq>/visible.txt
                  标注每行：x,y,w,h,...（逗号或空格分隔，只取前 4 个数）
  --fmt uav123    UAV123 结构：<root>/data_seq/UAV123/<seq>/*.jpg
                              + <root>/anno/UAV123/<seq>_gt.txt（每行 x,y,w,h）
                  （若你的目录结构不同，用 --img-dir / --anno 手动指定）
  --fmt imgdir    通用：<img-dir> 下是 xxx.jpg 图片序列，<anno> 是逐行 x,y,w,h

用法示例：
  # Anti-UAV（解压后）
  python tools\\dataset2seq.py --fmt antuav --root D:\\lowslow\\data\\Anti-UAV\\test `
      --seq 20190925_101849_1_1 --out D:\\lowslow\\data\\real

  # UAV123
  python tools\\dataset2seq.py --fmt uav123 --root D:\\lowslow\\data\\UAV123 `
      --seq car1 --out D:\\lowslow\\data\\real

  # 通用图片目录
  python tools\\dataset2seq.py --fmt imgdir --img-dir D:\\seq01_frames `
      --anno D:\\seq01\\gt.txt --name seq01 --out D:\\lowslow\\data\\real

输出：
  <out>/<seq>.mp4        视频（帧率默认 30）
  <out>/<seq>_gt.csv     真值：frame,x,y（x,y 为框中心，原图坐标）
做完后直接跑：python baseline\\track_v2.py --src <out>/<seq>.mp4
"""
import argparse
import csv
import glob
import os
import re
import sys

import cv2
import numpy as np


def parse_boxes(path, sep_candidates=(",", " ", "\t")):
    """读标注文件，每行取前 4 个数当作 x,y,w,h（框左上角+宽高）。容错：跳过坏行。"""
    boxes = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for ln in f:
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            parts = None
            for sep in sep_candidates:
                if sep in ln:
                    parts = [p for p in ln.replace(",", " ").split() if p]
                    break
            if parts is None:
                parts = ln.split()
            if len(parts) < 4:
                continue
            try:
                vals = [float(x) for x in parts[:4]]
            except ValueError:
                continue
            boxes.append(vals)
    return boxes


def write_seq(frames, boxes, out_mp4, out_csv, fps=30, skip_invalid=True):
    """frames: 图片路径列表（已排序）；boxes: 与之一一对应的 x,y,w,h"""
    if not frames:
        raise SystemExit("没有找到任何图片帧")
    if len(boxes) < len(frames):
        print("  提示：标注行数({}) 少于帧数({})，后面几帧将按最后一帧的框外推".format(len(boxes), len(frames)))
    first = cv2.imread(frames[0])
    if first is None:
        raise SystemExit("读不了第一帧：" + frames[0])
    h, w = first.shape[:2]
    vw = cv2.VideoWriter(out_mp4, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    if not vw.isOpened():
        raise SystemExit("视频写入器打不开：" + out_mp4)

    rows = []
    n_ok = 0
    for i, fp in enumerate(frames):
        img = cv2.imread(fp)
        if img is None:
            continue
        if img.shape[0] != h or img.shape[1] != w:
            img = cv2.resize(img, (w, h))
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        vw.write(img)
        # 框 -> 中心点
        if i < len(boxes):
            bx, by, bw, bh = boxes[i]
        elif boxes:
            bx, by, bw, bh = boxes[-1]
        else:
            bx = by = bw = bh = 0
        if bw <= 0 or bh <= 0:          # 无效标注（有些数据集用 0 表示目标不存在）
            if skip_invalid:
                continue
        cx, cy = bx + bw / 2.0, by + bh / 2.0
        rows.append([i, round(cx, 1), round(cy, 1)])
        n_ok += 1
    vw.release()

    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["frame", "x", "y"])
        wr.writerows(rows)

    print("")
    print("  ✅ 已生成视频 : {}  ({} 帧, {}x{})".format(out_mp4, len(frames), w, h))
    print("  ✅ 已生成真值 : {}  ({} 行有效标注)".format(out_csv, n_ok))
    print("")
    print("  下一步跑评测：")
    print("    python baseline\\detect_v1.py --src \"{}\"".format(out_mp4))
    print("    python baseline\\track_v2.py  --src \"{}\"".format(out_mp4))


def main():
    ap = argparse.ArgumentParser(description="公开数据集 -> mp4 + frame,x,y 真值")
    ap.add_argument("--fmt", required=True, choices=["antuav", "uav123", "imgdir"])
    ap.add_argument("--root", default="", help="数据集根目录")
    ap.add_argument("--seq", default="", help="序列名")
    ap.add_argument("--img-dir", default="", help="（imgdir）图片目录")
    ap.add_argument("--anno", default="", help="（imgdir）标注文件")
    ap.add_argument("--name", default="", help="（imgdir）输出序列名")
    ap.add_argument("--out", required=True, help="输出目录")
    ap.add_argument("--fps", type=int, default=30)
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)

    if a.fmt == "antuav":
        seq_dir = os.path.join(a.root, a.seq)
        # 找视频
        vids = glob.glob(os.path.join(seq_dir, "*.mp4"))
        if not vids:
            raise SystemExit("在 {} 里没找到 .mp4".format(seq_dir))
        vid = [v for v in vids if "visible" in os.path.basename(v).lower()] or vids
        vid = vid[0]
        # 找标注
        annos = glob.glob(os.path.join(seq_dir, "*.txt"))
        if not annos:
            raise SystemExit("在 {} 里没找到 .txt 标注".format(seq_dir))
        anno = [x for x in annos if "visible" in os.path.basename(x).lower()] or annos
        anno = anno[0]
        boxes = parse_boxes(anno)
        print("Anti-UAV: 视频={} 标注={} ({} 行)".format(os.path.basename(vid), os.path.basename(anno), len(boxes)))
        cap = cv2.VideoCapture(vid)
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or a.fps
        out_mp4 = os.path.join(a.out, a.seq + ".mp4")
        vw = cv2.VideoWriter(out_mp4, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
        rows, i = [], 0
        while True:
            ok, fr = cap.read()
            if not ok:
                break
            vw.write(fr)
            if i < len(boxes):
                bx, by, bw, bh = boxes[i]
                if bw > 0 and bh > 0:
                    rows.append([i, round(bx + bw / 2.0, 1), round(by + bh / 2.0, 1)])
            i += 1
        cap.release(); vw.release()
        out_csv = os.path.join(a.out, a.seq + "_gt.csv")
        with open(out_csv, "w", newline="", encoding="utf-8") as f:
            wr = csv.writer(f); wr.writerow(["frame", "x", "y"]); wr.writerows(rows)
        print("  ✅ {} 帧 -> {}".format(i, out_mp4))
        print("  ✅ 真值 {} 行 -> {}".format(len(rows), out_csv))
        print("     （Anti-UAV 是红外视频，注意转换到灰度链路的适配）")
        return

    if a.fmt == "uav123":
        img_dir = os.path.join(a.root, "data_seq", "UAV123", a.seq)
        if not os.path.isdir(img_dir):
            img_dir = os.path.join(a.root, a.seq)
        anno = os.path.join(a.root, "anno", "UAV123", a.seq + "_gt.txt")
        if not os.path.exists(anno):
            cands = glob.glob(os.path.join(a.root, "**", a.seq + "_gt.txt"), recursive=True)
            if not cands:
                raise SystemExit("找不到 {} 的标注".format(a.seq))
            anno = cands[0]
    else:
        img_dir = a.img_dir
        anno = a.anno
        a.seq = a.name or os.path.basename(img_dir.rstrip("\\/"))

    exts = ("*.jpg", "*.jpeg", "*.png", "*.bmp")
    frames = []
    for e in exts:
        frames += glob.glob(os.path.join(img_dir, e))
        frames += glob.glob(os.path.join(img_dir, e.upper()))
    # Windows 文件名不区分大小写 -> 上面两轮会重复匹配同一批文件，必须去重
    frames = list({os.path.normcase(os.path.abspath(p)): p for p in frames}.values())

    def keyfn(p):
        m = re.findall(r"(\d+)", os.path.basename(p))
        return int(m[-1]) if m else 0
    frames.sort(key=keyfn)

    if not frames:
        raise SystemExit("在 {} 里没找到图片".format(img_dir))
    boxes = parse_boxes(anno)
    print("格式={} 图片={} 帧 标注={} 行".format(a.fmt, len(frames), len(boxes)))
    write_seq(frames, boxes, os.path.join(a.out, a.seq + ".mp4"),
              os.path.join(a.out, a.seq + "_gt.csv"), fps=a.fps)


if __name__ == "__main__":
    main()
