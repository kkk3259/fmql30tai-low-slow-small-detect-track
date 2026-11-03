# -*- coding: utf-8 -*-
"""作品海报生成器（A2 竖版，浅蓝科技底）

用法：python tools/make_poster_v2.py
输出：docs/poster/作品海报_A2.png / .pdf
"""
import os
import math
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "docs", "poster")
FIG = os.path.join(ROOT, "report", "figs")

W, H = 2480, 3508
M = 120

BG_TOP, BG_BOT = (64, 142, 172), (196, 224, 238)
INK, INK2, INK3 = (16, 48, 72), (72, 104, 128), (120, 148, 168)
BAR = (18, 92, 118)
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


def tech_bg():
    """浅蓝渐变 + 网格 + 光晕 + 无人机/检测框/航迹/电路"""
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)],
               fill=tuple(int(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOT)))

    # 细网格
    for x in range(0, W, 84):
        d.line([(x, 0), (x, H)], fill=(150, 196, 214), width=1)
    for y in range(0, H, 84):
        d.line([(0, y), (W, y)], fill=(150, 196, 214), width=1)

    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)

    # 柔和光晕
    for cx, cy, rr, col in [(W - 420, 260, 540, (205, 243, 252, 125)),
                            (240, H - 520, 480, (220, 247, 252, 110)),
                            (W - 200, H - 900, 400, (200, 238, 250, 95))]:
        for r in range(rr, 0, -10):
            a = int(col[3] * (1 - r / rr) ** 1.6)
            ld.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(col[0], col[1], col[2], a))

    # 无人机剪影（三角机身 + 两翼）
    def drone(cx, cy, s, alpha):
        c = (28, 88, 118, alpha)
        ld.polygon([(cx, cy + s), (cx - s * 0.55, cy - s * 0.5), (cx + s * 0.55, cy - s * 0.5)], fill=c)
        ld.line([(cx - s * 0.9, cy - s * 0.55), (cx + s * 0.9, cy - s * 0.55)], fill=c, width=max(3, int(s * 0.14)))
        ld.ellipse([cx - s * 0.98, cy - s * 0.7, cx - s * 0.7, cy - s * 0.42], outline=c, width=3)
        ld.ellipse([cx + s * 0.7, cy - s * 0.7, cx + s * 0.98, cy - s * 0.42], outline=c, width=3)

    for cx, cy, s, a in [(W - 270, 600, 58, 95), (W - 760, 520, 40, 80),
                         (300, 820, 34, 72), (W - 170, 1500, 48, 72),
                         (520, H - 700, 32, 64)]:
        drone(cx, cy, s, a)

    # 检测框 + 准星
    for x, y, bw, bh, a in [(W - 560, 620, 150, 110, 160), (250, 960, 120, 88, 140),
                            (W - 150, 900, 90, 66, 110)]:
        ld.rectangle([x, y, x + bw, y + bh], outline=(8, 112, 142, a), width=4)
        mx, my = x + bw // 2, y + bh // 2
        ld.line([(mx - 18, my), (mx + 18, my)], fill=(8, 112, 142, a), width=3)
        ld.line([(mx, my - 18), (mx, my + 18)], fill=(8, 112, 142, a), width=3)

    # 航迹
    tr = [(W - 560, 620), (W - 460, 560), (W - 360, 585), (W - 270, 520), (W - 170, 480)]
    for i in range(len(tr) - 1):
        ld.line([tr[i], tr[i + 1]], fill=(8, 112, 142, 150), width=4)
    for p in tr:
        ld.ellipse([p[0] - 7, p[1] - 7, p[0] + 7, p[1] + 7], fill=(8, 112, 142, 170))

    # 右上雷达弧
    for r in range(160, 520, 80):
        ld.arc([W - 70 - r, 70 - r, W - 70 + r, 70 + r], start=90, end=270,
               fill=(24, 104, 136, 90), width=2)

    # 电路走线（左下）
    pcb = [(0, H - 420), (170, H - 420), (240, H - 350), (240, H - 180),
           (400, H - 180), (470, H - 250), (470, H - 420), (620, H - 420)]
    for i in range(len(pcb) - 1):
        ld.line([pcb[i], pcb[i + 1]], fill=(36, 96, 126, 115), width=4)
    for p in pcb:
        ld.ellipse([p[0] - 6, p[1] - 6, p[0] + 6, p[1] + 6], fill=(36, 96, 126, 135))

    # 十字标记
    for cx, cy, s in [(W - 90, 380, 16), (90, 640, 14), (W - 120, 1180, 14), (120, H - 260, 14)]:
        ld.line([(cx - s, cy), (cx + s, cy)], fill=(255, 255, 255, 190), width=3)
        ld.line([(cx, cy - s), (cx, cy + s)], fill=(255, 255, 255, 190), width=3)

    # 底部低空城市剪影
    base = H - 40
    skyline = [(0, 120), (90, 120), (90, 80), (180, 80), (180, 140), (300, 140), (300, 60),
               (420, 60), (420, 150), (560, 150), (560, 90), (700, 90), (700, 160), (860, 160),
               (860, 70), (1000, 70), (1000, 140), (1160, 140), (1160, 100), (1320, 100),
               (1320, 170), (1500, 170), (1500, 80), (1660, 80), (1660, 150), (1820, 150),
               (1820, 60), (1980, 60), (1980, 140), (2140, 140), (2140, 90), (2300, 90),
               (2300, 160), (2480, 160)]
    poly = [(x, base - hh) for x, hh in skyline] + [(W, H), (0, H)]
    ld.polygon(poly, fill=(46, 104, 136, 85))
    # 楼宇窗格
    for x, hh in skyline[::2]:
        for wy in range(base - hh + 18, base - 8, 26):
            ld.line([(x + 14, wy), (x + 40, wy)], fill=(255, 255, 255, 110), width=2)

    img = Image.alpha_composite(img.convert("RGBA"), layer)
    return img


def section_at(d, cx, y, title, size=32):
    """标题条以 cx 为中点"""
    f = font(size)
    w = tw(d, title, f)[0]
    bw = w + 64
    bx = cx - bw // 2
    d.rounded_rectangle([bx, y, bx + bw, y + size + 26], radius=6, fill=BAR)
    d.text((bx + 32, y + 7), title, font=f, fill=WHITE)
    return y + size + 26 + 28


def section(d, x, y, title, size=32):
    """标题条居中"""
    f = font(size)
    w = tw(d, title, f)[0]
    bw = w + 64
    bx = (W - bw) // 2
    d.rounded_rectangle([bx, y, bx + bw, y + size + 26], radius=6, fill=BAR)
    d.text((bx + 32, y + 7), title, font=f, fill=WHITE)
    return y + size + 26 + 28


def metric(d, x, y, value, unit, label, sub, color, center=False):
    f_v, f_u = font(76, mono=True), font(24)
    if center:
        d.text((x, y), value, font=f_v, fill=color, anchor="ma")
        vw = tw(d, value, f_v)[0]
        d.text((x + vw // 2 + 8, y + 36), unit, font=f_u, fill=color)
        d.text((x, y + 92), label, font=font(25), fill=INK, anchor="ma")
        d.text((x, y + 128), sub, font=font(19, False), fill=INK3, anchor="ma")
    else:
        d.text((x, y), value, font=f_v, fill=color)
        d.text((x + tw(d, value, f_v)[0] + 8, y + 36), unit, font=f_u, fill=color)
        d.text((x, y + 92), label, font=font(25), fill=INK)
        d.text((x, y + 128), sub, font=font(19, False), fill=INK3)


def paste_pic(img, path, box, crop=None, pad=0, border=(150, 190, 210)):
    x0, y0, x1, y1 = box
    im = Image.open(path).convert("RGB")
    if crop:
        im = im.crop(crop)
    r = min((x1 - x0 - pad * 2) / im.width, (y1 - y0 - pad * 2) / im.height)
    im = im.resize((int(im.width * r), int(im.height * r)), Image.LANCZOS)
    px, py = x0 + ((x1 - x0) - im.width) // 2, y0 + ((y1 - y0) - im.height) // 2
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, im.width, im.height], radius=6, fill=255)
    img.paste(im, (px, py), mask)
    ImageDraw.Draw(img).rounded_rectangle([px - 2, py - 2, px + im.width + 2, py + im.height + 2],
                                          radius=8, outline=border, width=2)


def flow(d, x, y, w):
    stages = [
        ("采集", "V4L2 / 回放", (70, 110, 140), "彩色帧"),
        ("预处理", "灰度 + 降采样", ORANGE, "灰度图"),
        ("形态学", "Black-Hat", ORANGE, "增强图"),
        ("CFAR", "自适应阈值", ORANGE, "二值图"),
        ("候选", "8 连通 CCL", ORANGE, "候选表"),
        ("精判", "ZG330 NPU", GREEN, "置信度"),
        ("跟踪", "卡尔曼 + 匹配", CYAN, "航迹"),
        ("推流", "网页 MJPEG", CYAN, "画面"),
    ]
    bw, gap, bh = 238, 46, 104
    groups = [(0, 0, "PS", (70, 110, 140)), (1, 4, "PL", ORANGE), (5, 5, "NPU", GREEN), (6, 7, "PS", CYAN)]
    for a, b, label, col in groups:
        gx0 = x + a * (bw + gap)
        gx1 = x + b * (bw + gap) + bw
        d.line([(gx0, y + 12), (gx1, y + 12)], fill=col, width=3)
        d.text((gx0, y - 20), label, font=font(19), fill=col)

    for i, (head, sub, col, tag) in enumerate(stages):
        bx, by = x + i * (bw + gap), y + 32
        d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=8, fill=(255, 255, 255), outline=col, width=2)
        d.text((bx + 16, by + 10), head, font=font(25), fill=INK)
        d.text((bx + 16, by + 50), sub, font=font(19, False), fill=INK2)
        d.text((bx + 16, by + bh + 10), tag, font=font(17, False), fill=col)
        if i < len(stages) - 1:
            ax, ay = bx + bw + 8, by + bh // 2
            d.line([(ax, ay), (ax + gap - 18, ay)], fill=(110, 140, 160), width=2)
            d.polygon([(ax + gap - 18, ay - 7), (ax + gap - 4, ay), (ax + gap - 18, ay + 7)], fill=(110, 140, 160))
    return y + 32 + bh + 46


def coverage(d, x, y, w):
    rows = [("全分辨率", 2, 20, (60, 130, 200)),
            ("2× 降采样", 4, 40, (70, 110, 190)),
            ("3× 降采样", 6, 60, PURPLE),
            ("4× 降采样", 50, 80, (150, 100, 200))]
    label_w, rh = 240, 38
    bar_w = w - label_w - 150
    scale = bar_w / 80
    for i, (name, a, b, c) in enumerate(rows):
        ry = y + i * rh
        d.text((x, ry + 6), name, font=font(22, False), fill=INK)
        bx = x + label_w
        d.line([(bx, ry + 18), (bx + bar_w, ry + 18)], fill=(200, 220, 232), width=7)
        d.line([(bx + a * scale, ry + 18), (bx + b * scale, ry + 18)], fill=c, width=7)
        d.text((bx + bar_w + 14, ry + 6), f"{a}~{b} px", font=font(19, mono=True), fill=INK2)
    ry = y + 4 * rh + 8
    d.text((x + label_w, ry), "四路合并后覆盖 2 ~ 80 px，中间无空档", font=font(22), fill=GREEN)
    return ry + 30


def main():
    content = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(content)

    # 标题区（居中）
    t1 = "2026 全国大学生嵌入式芯片与系统设计竞赛 · FPGA 创新设计赛道 · 复旦微方向"
    d.text((W // 2, 92), t1, font=font(23, False), fill=INK2, anchor="ma")
    t2 = "低小慢空间目标智能检测与跟踪系统"
    d.text((W // 2, 136), t2, font=font(96), fill=INK, anchor="ma")
    t3 = "PL 像素粗筛   ·   NPU 候选精判   ·   PS 航迹管理"
    d.text((W // 2, 260), t3, font=font(36), fill=CYAN, anchor="ma")
    t4 = "FMQL30TAI 悟净 Lite    ARM 4×A53 @1 GHz    ZG330 8 TOPS INT8    78000 LUT @50 MHz"
    d.text((W // 2, 322), t4, font=font(23, False), fill=INK2, anchor="ma")

    # 指标（4 列居中）
    y = 412
    col_w = (W - 2 * M) // 4
    cols = [("16.6", "fps", "三域端到端帧率", "相机 → PL → NPU → 跟踪 → 推流", CYAN),
            ("4.19", "ms", "PL 检测单帧", "512 位 PL-DDR", ORANGE),
            ("0.68", "ms", "NPU 候选判别", "cls128 · 121 算子", GREEN),
            ("2~80", "px", "目标尺寸覆盖", "全分辨率 + 三档降采样", PURPLE)]
    for i, (v, u, l, sub, c) in enumerate(cols):
        cx = M + col_w * i + col_w // 2
        metric(d, cx, y, v, u, l, sub, c, center=True)
        if i:
            d.line([(M + col_w * i, y + 6), (M + col_w * i, y + 154)], fill=(180, 205, 220), width=1)

    # 左右两栏的几何
    colw = 1080
    gap = 40
    lcx = M + colw // 2
    rcx = M + colw + gap + colw // 2

    # 左栏：问题
    y = section_at(d, lcx, 640, "问题")
    items = [("目标只有几像素", "整图 CNN 下采样后几乎拿不到特征，<8 px 召回率仅 48.5%。"),
             ("对比度低、背景杂波", "真实场景是暗剪影；单路 Top-Hat 召回 55%，Black-Hat 后 86%。"),
             ("算力与目标数无关", "整帧推理每帧跑满网络，边缘端跑不动。")]
    yy = y
    for head, body_text in items:
        d.text((lcx, yy), head, font=font(25), fill=INK, anchor="ma")
        sub = wrap(d, body_text, font(20, False), 980)
        for j, line in enumerate(sub):
            d.text((lcx, yy + 38 + j * 28), line, font=font(20, False), fill=INK2, anchor="ma")
        yy += 44 + len(sub) * 28 + 20

    # 右栏：创新点
    y2 = section_at(d, rcx, 640, "创新点")
    inn = [("01", "暗剪影形态学", "单路 Black-Hat 召回 55%→86%，候选数比双路低 3.7 倍。"),
           ("02", "三域异构级联", "NPU 只算个位数候选，端到端 16.6 fps。"),
           ("03", "逐像素等价验证", "IP1 灰度化 0 误差，NPU 输出误差 0.002。"),
           ("04", "平台约束下落地", "绕开未焊接接口，检测器接入 AI_Mate。")]
    yy = y2
    for num, head, body_text in inn:
        d.text((rcx, yy), f"{num}   {head}", font=font(24), fill=INK, anchor="ma")
        sub = wrap(d, body_text, font(19, False), 980)
        for j, line in enumerate(sub):
            d.text((rcx, yy + 36 + j * 27), line, font=font(19, False), fill=INK2, anchor="ma")
        yy += 42 + len(sub) * 27 + 16

    # 方案（全宽居中）
    y = section_at(d, W // 2, 1140, "方案：一条流水线跑完检测与跟踪")
    flow(d, (W - 2196) // 2, y, 2196)

    # 左栏：结果
    y = section_at(d, lcx, 1420, "结果：系统整体与板上实测")
    pw = 470
    paste_pic(content, os.path.join(FIG, "系统整体实现.jpg"),
              [lcx - pw // 2, y, lcx + pw // 2, y + 352])
    dw = 500
    paste_pic(content, os.path.join(FIG, "图9b_NPU检测效果.png"),
              [lcx - dw // 2, y + 364, lcx + dw // 2, y + 532], crop=(0, 128, 1724, 445))
    ty = y + 560
    stats = [("76.6% → 0.8%", "航迹确认后的虚警残留", ORANGE),
             ("0.920", "mAP50（YOLOv11n 单类）", GREEN),
             ("13.1 s", "断电到服务就绪", CYAN),
             ("84.4%", "三域位流 LUT", PURPLE)]
    for i, (v, l, c) in enumerate(stats):
        sx = lcx + (i % 2 - 0.5) * 500
        sy = ty + (i // 2) * 96
        d.text((sx, sy), v, font=font(26, mono=True), fill=c, anchor="ma")
        d.text((sx, sy + 34), l, font=font(17, False), fill=INK2, anchor="ma")

    # 右栏：公开基准
    y2 = section_at(d, rcx, 1420, "公开基准对比（DUT Anti-UAV test）")
    paste_pic(content, os.path.join(FIG, "baseline_comparison.png"),
              [rcx - colw // 2 + 20, y2, rcx + colw // 2 - 20, y2 + 400])
    ty2 = y2 + 420
    for v, c in [("0.619  mAP@[.5:.95]（COCO 协议）", CYAN),
                 ("超过除 SSD 外全部单阶段（SSD 0.632 / 33 fps）", ORANGE),
                 ("−6.4 点 / FPS ×11.7，相比两阶段最优 Cascade-RCNN", GREEN),
                 ("精度略低，帧率高一个量级", GREEN)]:
        d.text((rcx, ty2), v, font=font(20), fill=c, anchor="ma")
        ty2 += 34

    # 能力边界（全宽）
    y = section_at(d, W // 2, 2340, "能力边界：一份硬件覆盖 2~80 px")
    coverage(d, M + 60, y, W - 2 * M - 120)

    # 页脚
    by = H - 74
    d.rectangle([0, H - 110, W, H], fill=(8, 24, 40, 210))
    d.text((W // 2, by), "全部指标为板上实测 ｜ 代码与文档：gitee.com/kkk3259/fmql30tai-low-slow-small-detect-track",
           font=font(21, False), fill=(214, 228, 240), anchor="ma")

    # 每个内容块加磨砂玻璃底
    blocks = [(M, W - M, 390, 610),
              (M, M + colw, 620, 1140), (M + colw + gap, W - M, 620, 1140),
              (M, W - M, 1140, 1420),
              (M, M + colw, 1420, 2320), (M + colw + gap, W - M, 1420, 2320),
              (M, W - M, 2340, 2700)]
    bg_clear = tech_bg()
    blur_bg = bg_clear.filter(ImageFilter.GaussianBlur(16))
    img = bg_clear.convert("RGBA")
    # 标题区淡色蒙版：压住背景元素，保证居中标题干净
    veil = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    vd = ImageDraw.Draw(veil)
    for yy in range(0, 400):
        a = int(200 * (1 - yy / 400) ** 0.65)
        vd.line([(0, yy), (W, yy)], fill=(238, 247, 251, a))
    img = Image.alpha_composite(img, veil)

    boxes = []
    for bx0, bx1, a, b in blocks:
        bb = content.crop((bx0, a, bx1, b)).getbbox()
        if not bb:
            continue
        boxes.append((bx0, a + bb[1] - 18, bx1, a + bb[3] + 18))

    # 柔和投影
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    for (x0, y0, x1, y1) in boxes:
        sd.rounded_rectangle([x0 + 4, y0 + 10, x1 + 4, y1 + 10], radius=16, fill=(8, 36, 56, 72))
    img = Image.alpha_composite(img, shadow.filter(ImageFilter.GaussianBlur(9)))

    # 磨砂玻璃：模糊背景 + 白色蒙层
    for (x0, y0, x1, y1) in boxes:
        w_, h_ = x1 - x0, y1 - y0
        if w_ <= 2 or h_ <= 2:
            continue
        region = blur_bg.crop((x0, y0, x1, y1))
        white = Image.new("RGBA", region.size, (255, 255, 255, 255))
        glass = Image.blend(region, white, 0.64)
        mask = Image.new("L", region.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, w_ - 1, h_ - 1], radius=14, fill=255)
        img.paste(glass, (x0, y0), mask)

    db = ImageDraw.Draw(img)
    for (x0, y0, x1, y1) in boxes:
        db.rounded_rectangle([x0, y0, x1, y1], radius=14, outline=(126, 188, 210), width=2)
        db.line([(x0 + 16, y0 + 3), (x0 + 64, y0 + 3)], fill=(14, 112, 142), width=4)
    img = Image.alpha_composite(img, content)

    os.makedirs(OUT_DIR, exist_ok=True)
    img = img.convert("RGB")
    png = os.path.join(OUT_DIR, "作品海报_A2_v2.png")
    img.save(png, "PNG")
    try:
        img.save(os.path.join(OUT_DIR, "作品海报_A2_v2.pdf"), "PDF", resolution=150.0)
    except PermissionError:
        print("PDF 被 WPS/阅读器占用，已跳过；关闭后重跑即可生成")
    print("saved", png, img.size)


if __name__ == "__main__":
    main()
