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

BG_TOP, BG_BOT = (116, 202, 224), (244, 251, 253)
INK, INK2, INK3 = (16, 48, 72), (72, 104, 128), (120, 148, 168)
BAR = (26, 88, 136)
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

    for cx, cy, s, a in [(W - 270, 520, 62, 100), (W - 720, 300, 42, 85),
                         (300, 760, 36, 78), (W - 170, 1500, 50, 78),
                         (520, H - 700, 34, 70)]:
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
    for r in range(200, 760, 90):
        ld.arc([W - 160 - r, 160 - r, W - 160 + r, 160 + r], start=90, end=270,
               fill=(24, 104, 136, 95), width=3)
    ld.line([(W - 160, 160), (W - 160 - 700, 160)], fill=(24, 104, 136, 90), width=2)

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


def section(d, x, y, title, size=32):
    f = font(size)
    w = tw(d, title, f)[0]
    d.rounded_rectangle([x, y, x + w + 60, y + size + 26], radius=6, fill=BAR)
    d.text((x + 30, y + 7), title, font=f, fill=WHITE)
    return y + size + 26 + 28


def metric(d, x, y, value, unit, label, sub, color):
    f_v, f_u = font(76, mono=True), font(24)
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

    # 标题区
    d.text((M, 90), "2026 全国大学生嵌入式芯片与系统设计竞赛 · FPGA 创新设计赛道 · 复旦微方向",
           font=font(23, False), fill=INK2)
    d.rounded_rectangle([M, 136, M + 14, 268], radius=7, fill=BAR)
    d.text((M + 34, 134), "低小慢空间目标智能检测与跟踪系统", font=font(96), fill=INK)
    d.text((M + 34, 258), "PL 像素粗筛   ·   NPU 候选精判   ·   PS 航迹管理", font=font(36), fill=CYAN)
    d.text((M + 34, 320), "FMQL30TAI 悟净 Lite    ARM 4×A53 @1 GHz    ZG330 8 TOPS INT8    78000 LUT @50 MHz",
           font=font(23, False), fill=INK2)

    # 关键数字
    y = 412
    cols = [(M, "16.6", "fps", "三域端到端帧率", "相机 → PL → NPU → 跟踪 → 推流", CYAN),
            (M + 560, "4.19", "ms", "PL 检测单帧", "512 位 PL-DDR", ORANGE),
            (M + 1120, "0.68", "ms", "NPU 候选判别", "cls128 · 121 算子", GREEN),
            (M + 1680, "2~80", "px", "目标尺寸覆盖", "全分辨率 + 三档降采样", PURPLE)]
    for i, (x, v, u, l, s, c) in enumerate(cols):
        metric(d, x, y, v, u, l, s, c)
        if i:
            d.line([(x - 26, y + 6), (x - 26, y + 154)], fill=(180, 205, 220), width=1)

    # 问题
    y = section(d, M, 650, "问题")
    items = [("目标只有几像素", "整图 CNN 下采样后几乎拿不到特征，<8 px 召回率仅 48.5%。"),
             ("对比度低、背景杂波", "真实场景是暗剪影；单路 Top-Hat 召回 55%，Black-Hat 后 86%。"),
             ("算力与目标数无关", "整帧推理每帧跑满网络，边缘端跑不动，也浪费。")]
    yy = y
    for head, body in items:
        d.text((M, yy), "—", font=font(25, False), fill=ORANGE)
        d.text((M + 34, yy), head + "：", font=font(25), fill=INK)
        hw = tw(d, head + "：", font(25))[0]
        d.text((M + 34 + hw, yy), body, font=font(23, False), fill=INK2)
        yy += 46
    d.text((M + 1240, y - 4), "解法", font=font(21, False), fill=INK3)
    d.text((M + 1240, y + 28), "PL 粗筛（毫秒级）\nNPU 只判个位数候选\nPS 管航迹与推流",
           font=font(23, False), fill=INK, spacing=10)

    # 方案
    y = section(d, M, 900, "方案：一条流水线跑完检测与跟踪")
    flow(d, M, y, W - M * 2)

    # 创新点
    y = section(d, M, 1290, "创新点")
    inn = [("01", "暗剪影形态学", "把增强方向从亮斑改为暗斑：单路 Black-Hat 召回 55%→86%，候选数比双路低 3.7 倍。"),
           ("02", "三域异构级联", "NPU 算力只作用在个位数候选上，端到端 16.6 fps。"),
           ("03", "逐像素等价验证", "RTL 与 OpenCV 参考逐像素比对：IP1 灰度化 0 误差，NPU 输出误差 0.002。"),
           ("04", "平台约束下落地", "绕开 Lite 未焊接接口，全部走 PS 侧通路；检测器作为自定义算子接入 AI_Mate。")]
    for i, (num, head, body) in enumerate(inn):
        cx = M + (i % 2) * 1100
        cy = y + (i // 2) * 150
        d.text((cx, cy + 4), num, font=font(19, mono=True), fill=INK3)
        d.text((cx + 46, cy), head, font=font(29), fill=INK)
        for j, line in enumerate(wrap(d, body, font(23, False), 980)):
            d.text((cx + 46, cy + 42 + j * 32), line, font=font(23, False), fill=INK2)

    # 结果
    y = section(d, M, 1730, "结果：板上实测")
    img_w = 1400
    paste_pic(content, os.path.join(FIG, "图9b_NPU检测效果.png"),
              [M, y, M + img_w, y + 290], crop=(0, 128, 1724, 445))
    rx = M + img_w + 70
    d.text((rx, y + 4), "NPU 整图检测 · 真实 720P 逐帧", font=font(21, False), fill=INK3)
    ty = y + 40
    for v, l, c in [("76.6% → 0.8%", "航迹确认后的虚警残留", ORANGE),
                    ("0.920", "mAP50（自研 YOLOv11n 单类）", GREEN),
                    ("13.1 s", "断电到服务就绪", CYAN),
                    ("84.4%", "三域位流 LUT（独立位流 61.9%）", PURPLE)]:
        d.text((rx, ty), v, font=font(34, mono=True), fill=c)
        d.text((rx, ty + 42), l, font=font(20, False), fill=INK2)
        ty += 76

    # 对比
    y = section(d, M, 2190, "与传统整图 CNN 的差异")
    rows = [("检测方式", "整图一次推理", "PL 像素粗筛 + NPU 候选精判"),
            ("小目标能力", "<8 px 召回 48.5%", "覆盖 2~80 px"),
            ("算力开销", "与目标数量无关", "神经网络只算个位数候选"),
            ("端到端帧率", "5.92 fps（软件基线）", "16.6 fps（三域同板）")]
    rh = 60
    col1, col2 = 470, 760
    d.text((M, y), "维度", font=font(21), fill=INK3)
    d.text((M + col1, y), "传统做法", font=font(21), fill=INK3)
    d.text((M + col1 + col2, y), "本方案", font=font(21), fill=CYAN)
    d.line([(M, y + 36), (W - M, y + 36)], fill=(150, 185, 205), width=2)
    for i, (a, b, c) in enumerate(rows):
        ry = y + 36 + i * rh
        d.text((M, ry + 16), a, font=font(22, False), fill=INK)
        d.text((M + col1, ry + 16), b, font=font(22, False), fill=INK2)
        d.text((M + col1 + col2, ry + 16), c, font=font(22), fill=CYAN)
        d.line([(M, ry + rh), (W - M, ry + rh)], fill=(196, 218, 230), width=1)

    # 能力边界
    y = section(d, M, 2570, "能力边界：一份硬件覆盖 2~80 px")
    coverage(d, M, 2640, W - M * 2)

    # 交付与复现
    y3 = section(d, M, 2860, "交付与复现")
    d.text((M, y3), "仓库包含 PL 源码与约束、PS 应用、模型与量化校准集、测试数据与完整报告。",
           font=font(22, False), fill=INK2)
    d.text((M, y3 + 40), "板上复现：加载 ours3d_s5.bin，启动 init.d 服务，浏览器打开 :8080。",
           font=font(22, False), fill=INK2)

    # 页脚
    by = H - 74
    d.text((M, by), "全部指标为板上实测 ｜ 代码与文档：gitee.com/kkk3259/fmql30tai-low-slow-small-detect-track",
           font=font(21, False), fill=INK3)

    # 每个内容块加白底框
    blocks = [(390, 600), (620, 850), (870, 1230), (1250, 1670),
              (1690, 2140), (2160, 2570), (2590, 2850), (2870, 3020)]
    img = tech_bg()
    db = ImageDraw.Draw(img)
    for a, b in blocks:
        bb = content.crop((0, a, W, b)).getbbox()
        if not bb:
            continue
        x0 = max(0, bb[0] - 26)
        y0 = a + bb[1] - 18
        x1 = min(W, bb[2] + 26)
        y1 = a + bb[3] + 18
        db.rounded_rectangle([x0, y0, x1, y1], radius=18,
                             fill=(255, 255, 255, 212), outline=(150, 195, 215), width=2)
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
