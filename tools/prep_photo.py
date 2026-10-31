# -*- coding: utf-8 -*-
"""板卡实拍照片处理 —— 转正、自动裁剪、轻度增强

用途：把手机拍的板卡照片整理成可直接插入报告的规格。
处理链：旋转 → 绿色板卡区域自动检测 → 带边距裁剪 → 对比度拉伸 → 保存

用法：
    python tools/prep_photo.py <输入图> <输出图> [--rotate ccw|cw|none]
"""
import argparse
import os
import sys

import cv2
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")


def rotate(img, mode):
    if mode == "ccw":
        return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    if mode == "cw":
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    if mode == "180":
        return cv2.rotate(img, cv2.ROTATE_180)
    return img


def find_board_bbox(img, margin_ratio=0.03):
    """在 HSV 里找绿色 PCB，返回带边距的外接框；找不到则返回整图"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    # 绿色 PCB 的色相大约在 35~90，饱和度和亮度给较宽范围
    lo = np.array([30, 35, 30], np.uint8)
    hi = np.array([95, 255, 255], np.uint8)
    mask = cv2.inRange(hsv, lo, hi)

    # 形态学闭运算，把丝印、元件造成的小洞填上
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (31, 31))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, iterations=3)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,
                            cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9)), iterations=2)

    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if n <= 1:
        return 0, 0, img.shape[1], img.shape[0], 0.0

    # 取面积最大的连通域
    idx = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, w, h = (stats[idx, cv2.CC_STAT_LEFT], stats[idx, cv2.CC_STAT_TOP],
                  stats[idx, cv2.CC_STAT_WIDTH], stats[idx, cv2.CC_STAT_HEIGHT])
    frac = stats[idx, cv2.CC_STAT_AREA] / float(img.shape[0] * img.shape[1])

    # 太小说明没找到板子，别乱裁
    if frac < 0.15:
        return 0, 0, img.shape[1], img.shape[0], frac

    mx, my = int(w * margin_ratio), int(h * margin_ratio)
    x0, y0 = max(0, x - mx), max(0, y - my)
    x1 = min(img.shape[1], x + w + mx)
    y1 = min(img.shape[0], y + h + my)
    return x0, y0, x1, y1, frac


def enhance(img, clip=(1.2, 99.3)):
    """按百分位做对比度拉伸（不过曝、不压暗部）"""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    lo, hi = np.percentile(l, clip[0]), np.percentile(l, clip[1])
    if hi - lo < 10:
        return img
    l2 = np.clip((l.astype(np.float32) - lo) * (255.0 / (hi - lo)), 0, 255).astype(np.uint8)
    # 轻微提一点亮度（+6），避免逆光整体偏灰
    l2 = np.clip(l2.astype(np.int16) + 6, 0, 255).astype(np.uint8)
    return cv2.cvtColor(cv2.merge([l2, a, b]), cv2.COLOR_LAB2BGR)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--rotate", default="none", choices=["none", "ccw", "cw", "180"])
    ap.add_argument("--no-crop", action="store_true")
    ap.add_argument("--no-enhance", action="store_true")
    ap.add_argument("--quality", type=int, default=95)
    a = ap.parse_args()

    data = np.fromfile(a.src, dtype=np.uint8)      # 避免中文路径问题
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        print("  ✗ 读不到图片: %s" % a.src)
        return 1
    print("  输入 %dx%d" % (img.shape[1], img.shape[0]))

    img = rotate(img, a.rotate)
    if a.rotate != "none":
        print("  旋转 %-4s → %dx%d" % (a.rotate, img.shape[1], img.shape[0]))

    if not a.no_crop:
        x0, y0, x1, y1, frac = find_board_bbox(img)
        print("  板卡占比 %.1f%% → 裁剪 (%d,%d)-(%d,%d)" % (frac * 100, x0, y0, x1, y1))
        img = img[y0:y1, x0:x1]
        print("  裁剪后 %dx%d" % (img.shape[1], img.shape[0]))

    if not a.no_enhance:
        before = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).mean()
        img = enhance(img)
        after = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).mean()
        print("  增强 亮度 %.1f → %.1f" % (before, after))

    ext = os.path.splitext(a.dst)[1].lower()
    if ext in (".png",):
        ok, buf = cv2.imencode(".png", img, [cv2.IMWRITE_PNG_COMPRESSION, 6])
    else:
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, a.quality])
    if not ok:
        print("  ✗ 编码失败")
        return 1
    buf.tofile(a.dst)                              # 避免中文路径问题
    print("  ✓ 写出 %s  (%.0f KB)" % (a.dst, os.path.getsize(a.dst) / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
