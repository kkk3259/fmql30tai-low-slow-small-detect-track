# -*- coding: utf-8 -*-
"""作品海报·展板版（A2 竖版，图文混排）

用法：python tools/make_poster_board.py
输出：docs/poster/作品海报_A2_展板版.png / .pdf
"""
import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "docs", "poster")
FIG = os.path.join(ROOT, "report", "figs")

W, H = 2480, 3508
M = 100

TOP, BOT = (60, 138, 168), (192, 222, 236)
INK, INK2, INK3 = (16, 48, 72), (70, 102, 126), (118, 146, 166)
BAR = (24, 86, 134)
NAVY = (18, 62, 100)
CYAN, ORANGE, GREEN, PURPLE = (8, 122, 150), (190, 106, 6), (12, 118, 98), (96, 58, 186)
WHITE = (255, 255, 255)

F_BOLD = "C:/Windows/Fonts/msyhbd.ttc"
F_REG = "C:/Windows/Fonts/msyh.ttc"
F_MONO = "C:/Windows/Fonts/consola.ttf"


def font(size, bold=True, mono=False):
    return ImageFont.truetype(F_MONO if mono else (F_BOLD if bold else F_REG), size)


def tw(d, text, f):
    b = d.textbbox((0, 0), text, font=f)
    return b[2] - b[0], b[3] - b[1]


def wrap(d, text, f, maxw):
    lines, cur = [], ""
    for ch in text:
        if tw(d, cur + ch, f)[0] <= maxw:
            cur += ch
        else:
            lines.append(cur); cur = ch
    if cur:
        lines.append(cur)
    return lines


def bg():
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(TOP, BOT)))
    for x in range(0, W, 84):
        d.line([(x, 0), (x, H)], fill=(160, 204, 220), width=1)
    for y in range(0, H, 84):
        d.line([(0, y), (W, y)], fill=(160, 204, 220), width=1)

    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    # 城市剪影
    base = H - 20
    sky = [(0, 120), (100, 120), (100, 70), (220, 70), (220, 150), (360, 150), (360, 60),
           (520, 60), (520, 140), (680, 140), (680, 90), (840, 90), (840, 160), (1020, 160),
           (1020, 70), (1200, 70), (1200, 140), (1380, 140), (1380, 80), (1560, 80),
           (1560, 160), (1760, 160), (1760, 70), (1940, 70), (1940, 130), (2120, 130),
           (2120, 60), (2300, 60), (2300, 150), (2480, 150)]
    ld.polygon([(x, base - hh) for x, hh in sky] + [(W, H), (0, H)], fill=(46, 104, 136, 70))
    for x, hh in sky[::2]:
        for wy in range(base - hh + 16, base - 6, 26):
            ld.line([(x + 14, wy), (x + 40, wy)], fill=(255, 255, 255, 90), width=2)
    # 无人机
    for cx, cy, s in [(W - 210, 360, 46), (240, 520, 34)]:
        c = (28, 88, 118, 80)
        ld.polygon([(cx, cy + s), (cx - s * 0.55, cy - s * 0.5), (cx + s * 0.55, cy - s * 0.5)], fill=c)
        ld.line([(cx - s * 0.9, cy - s * 0.55), (cx + s * 0.9, cy - s * 0.55)], fill=c, width=4)
    img = Image.alpha_composite(img.convert("RGBA"), layer)
    return img


def bar(d, x, y, title, w=None, size=30):
    f = font(size)
    bw = w or tw(d, title, f)[0] + 52
    d.rectangle([x, y, x + bw, y + size + 22], fill=BAR)
    d.text((x + 26, y + 6), title, font=f, fill=WHITE)
    return y + size + 22


def pic(img, path, box, crop=None, pad=0):
    x0, y0, x1, y1 = box
    im = Image.open(path).convert("RGB")
    if crop:
        im = im.crop(crop)
    r = min((x1 - x0 - pad * 2) / im.width, (y1 - y0 - pad * 2) / im.height)
    im = im.resize((int(im.width * r), int(im.height * r)), Image.LANCZOS)
    px, py = x0 + ((x1 - x0) - im.width) // 2, y0 + ((y1 - y0) - im.height) // 2
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, im.width, im.height], radius=4, fill=255)
    img.paste(im, (px, py), mask)


def flow(d, x, y, w):
    stages = [("采集", "V4L2"), ("预处理", "灰度+降采样"), ("形态学", "Black-Hat"),
              ("CFAR", "自适应阈值"), ("候选", "8 连通 CCL"), ("精判", "ZG330 NPU"),
              ("跟踪", "卡尔曼"), ("推流", "网页 MJPEG")]
    bw, gap, bh = 250, 42, 88
    for i, (head, sub) in enumerate(stages):
        bx = x + i * (bw + gap)
        col = ORANGE if 1 <= i <= 4 else (GREEN if i == 5 else (CYAN if i >= 6 else (70, 110, 140)))
        d.rounded_rectangle([bx, y, bx + bw, y + bh], radius=6, fill=WHITE, outline=col, width=2)
        d.text((bx + 14, y + 10), head, font=font(24), fill=INK)
        d.text((bx + 14, y + 48), sub, font=font(18, False), fill=INK2)
        if i < len(stages) - 1:
            ax, ay = bx + bw + 6, y + bh // 2
            d.line([(ax, ay), (ax + gap - 16, ay)], fill=(110, 140, 160), width=2)
            d.polygon([(ax + gap - 16, ay - 6), (ax + gap - 4, ay), (ax + gap - 16, ay + 6)], fill=(110, 140, 160))
    return y + bh


def coverage(d, x, y, w):
    rows = [("全分辨率", 2, 20, (60, 130, 200)),
            ("2× 降采样", 4, 40, (70, 110, 190)),
            ("3× 降采样", 6, 60, PURPLE),
            ("4× 降采样", 50, 80, (150, 100, 200))]
    label_w, rh = 230, 36
    bar_w = w - label_w - 150
    scale = bar_w / 80
    for i, (name, a, b, c) in enumerate(rows):
        ry = y + i * rh
        d.text((x, ry + 4), name, font=font(21, False), fill=INK)
        bx = x + label_w
        d.line([(bx, ry + 16), (bx + bar_w, ry + 16)], fill=(200, 220, 232), width=7)
        d.line([(bx + a * scale, ry + 16), (bx + b * scale, ry + 16)], fill=c, width=7)
        d.text((bx + bar_w + 14, ry + 4), f"{a}~{b} px", font=font(18, mono=True), fill=INK2)
    ry = y + 4 * rh + 6
    d.text((x + label_w, ry), "四路合并后覆盖 2 ~ 80 px，中间无空档", font=font(21), fill=GREEN)


def main():
    img = bg()
    d = ImageDraw.Draw(img)

    # 顶部深蓝条
    d.rectangle([0, 0, W, 250], fill=NAVY)
    d.text((M, 46), "2026 全国大学生嵌入式芯片与系统设计竞赛 · FPGA 创新设计赛道 · 复旦微方向",
           font=font(22, False), fill=(196, 220, 236))
    d.text((M, 92), "低小慢空间目标智能检测与跟踪系统", font=font(64), fill=WHITE)
    d.text((M, 186), "PL 像素粗筛  ·  NPU 候选精判  ·  PS 航迹管理", font=font(28), fill=(150, 220, 240))
    d.text((W - M - 260, 186), "队伍编号 55375", font=font(26, False), fill=(196, 220, 236))

    # 01 问题与思路
    y = 300
    bar(d, M, y, "01  问题与思路")
    px, py, pw, ph = M, y + 76, 1150, 300
    d.rounded_rectangle([px - 10, py - 10, px + pw + 10, py + ph + 10], radius=12,
                        fill=(255, 255, 255, 178), outline=(78, 148, 178), width=2)
    items = [("目标只有几像素", "整图 CNN 下采样后几乎拿不到特征，<8 px 召回率仅 48.5%。"),
             ("对比度低、背景杂波", "真实场景是暗剪影；单路 Top-Hat 召回 55%，Black-Hat 后 86%。"),
             ("算力与目标数无关", "整帧推理每帧跑满网络，边缘端跑不动。")]
    ty = py + 18
    for head, body in items:
        d.text((px + 18, ty), "—", font=font(24, False), fill=ORANGE)
        d.text((px + 50, ty), head, font=font(25), fill=INK)
        for j, line in enumerate(wrap(d, body, font(22, False), pw - 80)):
            d.text((px + 50, ty + 38 + j * 30), line, font=font(22, False), fill=INK2)
        ty += 94

    # 右侧三域分工
    rx = M + 1200
    d.text((rx, py - 4), "三域异构分工", font=font(26), fill=BAR)
    for i, (tag, desc, col) in enumerate([("PL", "像素级粗筛，毫秒级", ORANGE),
                                         ("NPU", "只判个位数候选", GREEN),
                                         ("PS", "航迹与推流", CYAN)]):
        by = py + 44 + i * 82
        d.rounded_rectangle([rx, by, rx + 96, by + 56], radius=8, fill=col)
        d.text((rx + 24, by + 10), tag, font=font(24, mono=True), fill=WHITE)
        d.text((rx + 116, by + 12), desc, font=font(24, False), fill=INK)

    # 02 方案
    y = 760
    bar(d, M, y, "02  方案：一条流水线跑完检测与跟踪")
    flow(d, M, y + 82, W - M * 2)

    # 03 创新点（2×2 图文卡）
    y = 1010
    bar(d, M, y, "03  创新点")
    cards = [("暗剪影形态学", "单路 Black-Hat 召回 55%→86%，候选数比双路低 3.7 倍。",
              os.path.join(FIG, "图6_PL检测链路模块框图.png")),
             ("三域异构级联", "NPU 只算个位数候选，端到端 16.6 fps。",
              os.path.join(FIG, "图9b_NPU检测效果.png")),
             ("逐像素等价验证", "IP1 灰度化 0 误差，NPU 输出误差 0.002。",
              os.path.join(FIG, "图14_耗时分解.png")),
             ("平台约束下落地", "绕开未焊接接口，检测器接入 AI_Mate。",
              os.path.join(FIG, "图C_网页控制台界面.png"))]
    cw, ch = 1110, 380
    for i, (head, body, path) in enumerate(cards):
        cx = M + (i % 2) * (cw + 50)
        cy = y + 78 + (i // 2) * (ch + 40)
        d.rounded_rectangle([cx, cy, cx + cw, cy + ch], radius=12,
                            fill=(255, 255, 255, 178), outline=(78, 148, 178), width=2)
        d.text((cx + 22, cy + 16), head, font=font(27), fill=INK)
        d.text((cx + 22, cy + 56), body, font=font(20, False), fill=INK2)
        pic(img, path, [cx + 16, cy + 96, cx + cw - 16, cy + ch - 16])

    # 04 结果
    y = 2010
    bar(d, M, y, "04  结果：板上实测")
    pic(img, os.path.join(FIG, "图9b_NPU检测效果.png"),
        [M, y + 78, M + 1380, y + 400], crop=(0, 128, 1724, 445))
    rx = M + 1430
    for i, (v, l, c) in enumerate([("16.6 fps", "三域端到端", CYAN),
                                   ("4.19 ms", "PL 检测单帧", ORANGE),
                                   ("0.68 ms", "NPU 候选判别", GREEN),
                                   ("2~80 px", "目标尺寸覆盖", PURPLE)]):
        d.text((rx, y + 80 + i * 82), v, font=font(34, mono=True), fill=c)
        d.text((rx, y + 122 + i * 82), l, font=font(20, False), fill=INK2)

    # 05 公开基准对比
    y = 2440
    bar(d, M, y, "05  公开基准对比（DUT Anti-UAV test）")
    pic(img, os.path.join(FIG, "baseline_comparison.png"), [M, y + 76, M + 980, y + 76 + 330])
    rx = M + 1020
    ty = y + 88
    for v, l, c in [("0.619", "mAP@[.5:.95]（COCO 协议）", CYAN),
                    ("超过除 SSD 外", "的全部单阶段方法（SSD 0.632 / 33 fps）", ORANGE),
                    ("−6.4 点 / FPS ×11.7", "与两阶段最优 Cascade-RCNN 相比，精度略低，帧率高一个量级", GREEN)]:
        d.text((rx, ty), v, font=font(28), fill=c)
        for j, line in enumerate(wrap(d, l, font(20, False), 700)):
            d.text((rx, ty + 40 + j * 28), line, font=font(20, False), fill=INK2)
        ty += 116

    # 06 跨数据集泛化
    y = 2860
    bar(d, M, y, "06  跨数据集泛化（Halmstad，零样本）")
    pic(img, os.path.join(FIG, "halmstad_detection_grid.png"), [M, y + 76, M + 980, y + 76 + 300])
    rx = M + 1020
    d.text((rx, y + 84), "90.6%", font=font(62, mono=True), fill=GREEN)
    d.text((rx, y + 166), "64 帧检出 58 帧", font=font(22, False), fill=INK2)
    d.text((rx, y + 204), "置信度 median 0.76", font=font(22, False), fill=INK2)
    d.text((rx, y + 242), "DUT 训练，未微调直接推理", font=font(22, False), fill=INK2)

    # 底部深蓝条
    d.rectangle([0, H - 170, W, H], fill=NAVY)
    d.text((M, H - 126), "低空探测  ·  边缘智能", font=font(44), fill=WHITE)
    d.text((W - M - 900, H - 108), "代码与文档：gitee.com/kkk3259/fmql30tai-low-slow-small-detect-track",
           font=font(20, False), fill=(196, 220, 236))

    os.makedirs(OUT_DIR, exist_ok=True)
    img = img.convert("RGB")
    png = os.path.join(OUT_DIR, "作品海报_A2_展板版.png")
    img.save(png, "PNG")
    try:
        img.save(os.path.join(OUT_DIR, "作品海报_A2_展板版.pdf"), "PDF", resolution=150.0)
    except PermissionError:
        print("PDF 被占用，已跳过")
    print("saved", png, img.size)


if __name__ == "__main__":
    main()
