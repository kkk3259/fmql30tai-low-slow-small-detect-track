# -*- coding: utf-8 -*-
"""作品海报生成器（A2 竖版，深色科技风，v2）

用法：python tools/make_poster_v2.py
输出：docs/poster/作品海报_A2_v2.png / .pdf
"""
import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "docs", "poster")
FIG = os.path.join(ROOT, "report", "figs")

W, H = 2480, 3508
M = 110

BG0, BG1 = (7, 19, 32), (12, 30, 51)
CARD, CARD2 = (13, 27, 44), (17, 33, 52)
LINE = (38, 58, 84)
CYAN, ORANGE, GREEN, PURPLE = (34, 211, 238), (245, 158, 11), (52, 211, 153), (167, 139, 250)
BLUE = (96, 165, 250)
WHITE, GREY, DIM = (232, 238, 247), (150, 170, 196), (105, 125, 152)

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
        if ch == "\n":
            lines.append(cur); cur = ""; continue
        if tw(d, cur + ch, f)[0] <= maxw:
            cur += ch
        else:
            lines.append(cur); cur = ch
    if cur:
        lines.append(cur)
    return lines


def photo_bg():
    """项目实拍背景：低空检测画面压暗做纹理 + 工程网格 + 雷达环"""
    src = Image.open(os.path.join(FIG, "图9b_NPU检测效果.png")).convert("RGB")
    # 取中间一帧（避开标题与帧标签）
    frame = src.crop((580, 130, 1140, 450))
    r = max(W / frame.width, H / frame.height)
    frame = frame.resize((int(frame.width * r), int(frame.height * r)), Image.LANCZOS)
    left = (frame.width - W) // 2
    top = (frame.height - H) // 2
    frame = frame.crop((left, top, left + W, top + H))
    frame = frame.filter(ImageFilter.GaussianBlur(10))

    overlay = Image.new("RGB", (W, H), (7, 19, 32))
    img = Image.blend(frame, overlay, 0.86)
    d = ImageDraw.Draw(img)

    # 工程网格
    for x in range(0, W, 80):
        d.line([(x, 0), (x, H)], fill=(16, 42, 62), width=1)
    for y in range(0, H, 80):
        d.line([(0, y), (W, y)], fill=(16, 42, 62), width=1)

    # 右上雷达环
    cx, cy = W - 280, 300
    for rr in range(160, 820, 120):
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=(20, 70, 92), width=2)
    d.line([(cx - 820, cy), (cx + 820, cy)], fill=(20, 70, 92), width=1)
    d.line([(cx, cy - 820), (cx, cy + 820)], fill=(20, 70, 92), width=1)
    d.arc([cx - 660, cy - 660, cx + 660, cy + 660], start=-70, end=12,
          fill=(28, 130, 150), width=4)

    # 顶部与底部压暗，保证标题和页脚可读
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    for y in range(560):
        a = int(200 * (1 - y / 560) ** 0.7)
        ld.line([(0, y), (W, y)], fill=(5, 13, 24, a))
    for y in range(H - 360, H):
        a = int(190 * ((y - (H - 360)) / 360) ** 0.6)
        ld.line([(0, y), (W, y)], fill=(5, 13, 24, a))
    img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")
    return img


def card(d, box, fill=CARD, outline=LINE, radius=22, width=2):
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def pill(d, x, y, text, f, fg=CYAN, bg=(18, 40, 56), padx=22, pady=9):
    w, h = tw(d, text, f)
    d.rounded_rectangle([x, y, x + w + padx * 2, y + h + pady * 2],
                        radius=(h + pady * 2) // 2, fill=bg, outline=fg, width=2)
    d.text((x + padx, y + pady - 2), text, font=f, fill=fg)
    return x + w + padx * 2


def section(d, x, y, num, title, color=CYAN, size=50):
    d.text((x, y), num, font=font(size - 6, mono=True), fill=color)
    d.text((x + 76, y), title, font=font(size), fill=WHITE)
    w = tw(d, title, font(size))[0]
    d.line([(x, y + size + 16), (x + 76 + w + 18, y + size + 16)], fill=color, width=3)
    return y + size + 42


def metric_card(d, x, y, w, h, value, unit, label, sub, color):
    card(d, [x, y, x + w, y + h], fill=CARD2, outline=LINE)
    d.rounded_rectangle([x, y, x + 8, y + h], radius=4, fill=color)
    f_v, f_u = font(96, mono=True), font(32)
    d.text((x + 34, y + 26), value, font=f_v, fill=color)
    d.text((x + 34 + tw(d, value, f_v)[0] + 8, y + 70), unit, font=f_u, fill=color)
    d.text((x + 34, y + 134), label, font=font(30), fill=WHITE)
    d.text((x + 34, y + 176), sub, font=font(22, False), fill=DIM)


def bullet(d, x, y, w, head, body, color):
    d.ellipse([x, y + 12, x + 14, y + 26], fill=color)
    d.text((x + 30, y), head, font=font(31), fill=WHITE)
    hw = tw(d, head, font(31))[0]
    lines = wrap(d, body, font(25, False), w - 30)
    d.text((x + 30 + hw + 12, y + 5), lines[0] if lines else "", font=font(25, False), fill=GREY)
    for i, ln in enumerate(lines[1:]):
        d.text((x + 30, y + 40 + i * 34), ln, font=font(25, False), fill=GREY)
    return y + 44 + max(1, len(lines)) * 34


def paste_card(img, path, box, crop=None, pad=14, radius=16):
    x0, y0, x1, y1 = box
    d = ImageDraw.Draw(img)
    card(d, box, fill=(255, 255, 255), outline=(205, 216, 230), radius=radius, width=2)
    im = Image.open(path).convert("RGB")
    if crop:
        im = im.crop(crop)
    r = min(((x1 - x0) - pad * 2) / im.width, ((y1 - y0) - pad * 2) / im.height)
    im = im.resize((int(im.width * r), int(im.height * r)), Image.LANCZOS)
    px, py = x0 + ((x1 - x0) - im.width) // 2, y0 + ((y1 - y0) - im.height) // 2
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, im.width, im.height], radius=10, fill=255)
    img.paste(im, (px, py), mask)


def flow(d, x, y, w):
    """自制检测流水线条：8 个环节，按 PL/NPU/PS 分组着色"""
    stages = [
        ("① 采集", "V4L2 / 回放", BLUE, "彩色帧"),
        ("② 预处理", "灰度 + 降采样", ORANGE, "灰度图"),
        ("③ 形态学", "Black-Hat", ORANGE, "增强图"),
        ("④ CFAR", "自适应阈值", ORANGE, "二值图"),
        ("⑤ 候选", "8 连通 CCL", ORANGE, "候选表"),
        ("⑥ 精判", "ZG330 NPU", GREEN, "置信度"),
        ("⑦ 跟踪", "卡尔曼 + 匹配", CYAN, "航迹"),
        ("⑧ 推流", "网页 MJPEG", CYAN, "画面"),
    ]
    bw, gap, bh = 236, 44, 116
    groups = [(0, 0, "PS", BLUE), (1, 4, "PL 可编程逻辑", ORANGE), (5, 5, "NPU", GREEN), (6, 7, "PS", CYAN)]
    for a, b, label, col in groups:
        gx0 = x + a * (bw + gap)
        gx1 = x + b * (bw + gap) + bw
        d.line([(gx0, y + 20), (gx1, y + 20)], fill=col, width=3)
        d.text((gx0 + 8, y - 14), label, font=font(22), fill=col)

    for i, (head, sub, col, tag) in enumerate(stages):
        bx = x + i * (bw + gap)
        by = y + 44
        d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=14, fill=CARD2, outline=col, width=2)
        d.text((bx + 16, by + 14), head, font=font(28), fill=WHITE)
        d.text((bx + 16, by + 58), sub, font=font(21, False), fill=GREY)
        d.text((bx + 16, by + bh + 12), tag, font=font(19, False), fill=col)
        if i < len(stages) - 1:
            ax = bx + bw + 10
            ay = by + bh // 2
            d.line([(ax, ay), (ax + gap - 20, ay)], fill=DIM, width=3)
            d.polygon([(ax + gap - 20, ay - 8), (ax + gap - 4, ay), (ax + gap - 20, ay + 8)], fill=DIM)
    return y + 44 + bh + 52


def coverage(d, x, y, w):
    """尺寸覆盖条形图（自制，避免白底截图字太小）"""
    rows = [("全分辨率（1×）", 2, 20, (96, 165, 250)),
            ("2× 降采样", 4, 40, (129, 140, 248)),
            ("3× 降采样", 6, 60, PURPLE),
            ("4× 降采样", 50, 80, (192, 132, 252))]
    label_w, rh = 300, 40
    bar_w = w - label_w - 150
    scale = bar_w / 80
    for i, (name, a, b, c) in enumerate(rows):
        ry = y + i * rh
        d.text((x, ry + 6), name, font=font(24, False), fill=WHITE)
        bx = x + label_w
        d.rounded_rectangle([bx, ry + 4, bx + bar_w, ry + rh - 6], radius=8, fill=(15, 24, 42))
        d.rounded_rectangle([bx + a * scale, ry + 4, bx + b * scale, ry + rh - 6], radius=8, fill=c)
        tx = bx + a * scale + 12
        d.text((tx, ry + 10), f"{a}~{b} px", font=font(19, mono=True), fill=(8, 13, 26))
    ry = y + 4 * rh + 12
    bx = x + label_w
    d.rounded_rectangle([bx, ry, bx + bar_w, ry + 36], radius=8, fill=(22, 60, 52), outline=GREEN, width=2)
    d.text((bx + 20, ry + 6), "四路合并：2 ~ 80 px，中间无空档", font=font(23), fill=GREEN)
    return ry + 36


def main():
    img = photo_bg()
    d = ImageDraw.Draw(img)

    # 顶部
    d.text((M, 88), "2026 全国大学生嵌入式芯片与系统设计竞赛 · FPGA 创新设计赛道 · 复旦微方向",
           font=font(28, False), fill=GREY)
    d.text((M, 146), "低小慢空间目标智能检测与跟踪系统", font=font(108), fill=WHITE)
    d.text((M, 286), "PL 像素粗筛  ·  NPU 候选精判  ·  PS 航迹管理", font=font(44), fill=CYAN)
    x = M
    for text, col in [("FMQL30TAI 悟净 Lite", CYAN), ("ZG330 NPU · 8 TOPS INT8", ORANGE),
                      ("78000 LUT @50 MHz", GREEN)]:
        x = pill(d, x, 366, text, font(26), fg=col) + 16

    # 指标条
    y, gap = 462, 24
    cw = (W - M * 2 - gap * 3) // 4
    for i, (v, u, l, s, c) in enumerate([
        ("16.6", "fps", "三域端到端帧率", "相机→PL→NPU→跟踪→推流", CYAN),
        ("4.19", "ms", "PL 检测单帧", "512 位 PL-DDR", ORANGE),
        ("0.68", "ms", "NPU 候选判别", "cls128 · 121 算子", GREEN),
        ("2~80", "px", "目标尺寸覆盖", "全分辨率 + 三档降采样", PURPLE)]):
        metric_card(d, M + i * (cw + gap), y, cw, 212, v, u, l, s, c)

    # 01
    y = section(d, M, 726, "01", "为什么「低小慢」难", CYAN)
    left_w = 1380
    yy = y
    for h, b in [("目标只有几像素", "整图 CNN 下采样后几乎拿不到特征，<8 px 召回率仅 48.5%。"),
                 ("对比度低、背景杂波", "真实场景是暗剪影；单路 Top-Hat 召回 55%，改 Black-Hat 后 86%。"),
                 ("算力与目标数无关", "整图推理每帧都要跑满网络，边缘端跑不动，也浪费。")]:
        yy = bullet(d, M, yy, left_w, h, b, ORANGE) + 14
    rx, rw = M + left_w + 40, W - M - (M + left_w + 40)
    card(d, [rx, y - 6, W - M, y + 262], fill=CARD, outline=LINE)
    d.text((rx + 28, y + 18), "解法：三域异构分工", font=font(33), fill=CYAN)
    ty = y + 76
    for tag, desc, c in [("PL", "像素级粗筛（毫秒级、便宜）", ORANGE),
                         ("NPU", "只判个位数候选（准、贵）", GREEN),
                         ("PS", "流程调度与卡尔曼航迹（灵活）", CYAN)]:
        d.rounded_rectangle([rx + 28, ty, rx + 108, ty + 42], radius=10, fill=c)
        d.text((rx + 42, ty + 6), tag, font=font(25, mono=True), fill=(8, 13, 26))
        d.text((rx + 124, ty + 8), desc, font=font(24, False), fill=WHITE)
        ty += 60

    # 02
    y = section(d, M, 1080, "02", "系统架构：一条流水线跑完检测与跟踪", ORANGE)
    y = flow(d, M, y, W - M * 2)

    # 03
    y = section(d, M, y + 20, "03", "四个创新点", GREEN)
    gap, cw2, ch = 24, (W - M * 2 - 24) // 2, 214
    for i, (num, head, body, c) in enumerate([
        ("01", "暗剪影形态学", ["把增强方向从亮斑改为暗斑：单路 Black-Hat", "召回 55%→86%，候选数比双路方案低 3.7 倍。"], ORANGE),
        ("02", "三域异构级联", ["NPU 算力只作用在个位数候选上；整图推理改为", "「PL 粗筛 + NPU 精判」，端到端 16.6 fps。"], CYAN),
        ("03", "逐像素等价验证", ["RTL 与 OpenCV 参考逐像素比对：IP1 灰度化 0 误差，", "NPU 输出数值误差 0.002。"], GREEN),
        ("04", "平台约束下落地", ["绕开 Lite 未焊接接口，全部走 PS 侧通路；检测器作为", "自定义算子接入 AI_Mate，同板共享 DDR。"], PURPLE)]):
        cx, cy = M + (i % 2) * (cw2 + gap), y + (i // 2) * (ch + gap)
        card(d, [cx, cy, cx + cw2, cy + ch], fill=CARD2, outline=LINE)
        d.text((cx + 28, cy + 20), num, font=font(38, mono=True), fill=c)
        d.text((cx + 94, cy + 22), head, font=font(34), fill=WHITE)
        d.line([(cx + 28, cy + 78), (cx + cw2 - 28, cy + 78)], fill=LINE, width=2)
        ty = cy + 96
        for ln in body:
            d.text((cx + 28, ty), ln, font=font(25, False), fill=GREY)
            ty += 38
    y += ch * 2 + gap + 24

    # 04
    y = section(d, M, y + 16, "04", "板上实测：看得见的效果", CYAN)
    img_w = 1430
    paste_card(img, os.path.join(FIG, "图9b_NPU检测效果.png"),
               [M, y, M + img_w, y + 400], crop=(0, 128, 1724, 470))
    rx, rw = M + img_w + 32, W - M - (M + img_w + 32)
    card(d, [rx, y, W - M, y + 400], fill=CARD, outline=LINE)
    d.text((rx + 28, y + 18), "NPU 整图检测 · 真实 720P 逐帧", font=font(24), fill=GREY)
    ty = y + 58
    for v, l, c in [("76.6% → 0.8%", "航迹确认后的虚警残留", ORANGE),
                    ("0.920", "mAP50（自研 YOLOv11n 单类）", GREEN),
                    ("13.1 s", "断电到服务就绪", CYAN),
                    ("84.4%", "三域位流 LUT（独立位流 61.9%）", PURPLE)]:
        d.text((rx + 28, ty), v, font=font(38, mono=True), fill=c)
        d.text((rx + 28, ty + 48), l, font=font(22, False), fill=GREY)
        ty += 82
    y += 430

    # 05
    y = section(d, M, y + 16, "05", "与传统整图 CNN 的差异", ORANGE)
    rows = [("检测方式", "整图一次推理", "PL 像素粗筛 + NPU 候选精判"),
            ("小目标能力", "<8 px 召回 48.5%", "覆盖 2~80 px"),
            ("算力开销", "与目标数量无关", "神经网络只算个位数候选"),
            ("端到端帧率", "5.92 fps（软件基线）", "16.6 fps（三域同板）")]
    rh = 80
    col1, col2 = 470, 700
    d.rounded_rectangle([M, y, W - M, y + rh], radius=12, fill=CARD2)
    d.text((M + 28, y + 20), "维度", font=font(27), fill=GREY)
    d.text((M + col1, y + 20), "传统做法", font=font(27), fill=GREY)
    d.text((M + col1 + col2, y + 20), "本方案", font=font(27), fill=CYAN)
    for i, (a, b, c) in enumerate(rows):
        ry = y + rh * (i + 1)
        d.rounded_rectangle([M, ry, W - M, ry + rh], radius=12, fill=CARD if i % 2 == 0 else BG1)
        d.text((M + 28, ry + 22), a, font=font(26, False), fill=WHITE)
        d.text((M + col1, ry + 22), b, font=font(26, False), fill=GREY)
        d.text((M + col1 + col2, ry + 22), c, font=font(26), fill=CYAN)

    # 06 能力边界
    y += rh * (len(rows) + 1)
    y = section(d, M, y + 14, "06", "能力边界：一份硬件覆盖 2~80 px", GREEN)
    coverage(d, M, y, W - M * 2)

    # 底部
    by = H - 132
    d.line([(M, by - 22), (W - M, by - 22)], fill=LINE, width=2)
    d.text((M, by + 6), "平台：FMQL30TAI 悟净 Lite ｜ 4×A53@1 GHz ｜ ZG330 8 TOPS ｜ 78000 LUT @50 MHz",
           font=font(24, False), fill=GREY)
    d.text((M, by + 48), "全部指标为板上实测 ｜ 代码与文档：gitee.com/kkk3259/fmql30tai-low-slow-small-detect-track",
           font=font(24, False), fill=DIM)

    os.makedirs(OUT_DIR, exist_ok=True)
    png = os.path.join(OUT_DIR, "作品海报_A2_v2.png")
    img.save(png, "PNG")
    img.save(os.path.join(OUT_DIR, "作品海报_A2_v2.pdf"), "PDF", resolution=150.0)
    print("saved", png, img.size)


if __name__ == "__main__":
    main()
