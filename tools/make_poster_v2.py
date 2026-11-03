# -*- coding: utf-8 -*-
"""作品海报生成器（A2 竖版）

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

CARD = (10, 24, 40, 150)
LINE = (70, 90, 115)
CYAN, ORANGE, GREEN, PURPLE = (34, 211, 238), (245, 158, 11), (52, 211, 153), (167, 139, 250)
WHITE, GREY, DIM = (236, 241, 248), (176, 190, 208), (128, 146, 168)

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


def photo_bg():
    src = Image.open(os.path.join(FIG, "图9b_NPU检测效果.png")).convert("RGB")
    frame = src.crop((580, 130, 755, 400))
    r = max(W / frame.width, H / frame.height)
    frame = frame.resize((int(frame.width * r), int(frame.height * r)), Image.LANCZOS)
    left, top = (frame.width - W) // 2, (frame.height - H) // 2
    frame = frame.crop((left, top, left + W, top + H))
    frame = frame.filter(ImageFilter.GaussianBlur(14))

    overlay = Image.new("RGB", (W, H), (9, 22, 38))
    img = Image.blend(frame, overlay, 0.60)

    # 顶部压暗，保证标题可读
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    for y in range(520):
        a = int(170 * (1 - y / 520) ** 0.8)
        ld.line([(0, y), (W, y)], fill=(7, 17, 30, a))
    for y in range(H - 260, H):
        a = int(140 * ((y - (H - 260)) / 260) ** 0.7)
        ld.line([(0, y), (W, y)], fill=(7, 17, 30, a))
    return Image.alpha_composite(img.convert("RGBA"), layer)


def section(d, x, y, title, size=34):
    d.text((x, y), title, font=font(size), fill=WHITE)
    w = tw(d, title, font(size))[0]
    d.line([(x, y + size + 14), (x + w + 36, y + size + 14)], fill=LINE, width=2)
    return y + size + 44


def metric(d, x, y, value, unit, label, sub, color):
    f_v, f_u = font(78, mono=True), font(26)
    d.text((x, y), value, font=f_v, fill=color)
    d.text((x + tw(d, value, f_v)[0] + 8, y + 38), unit, font=f_u, fill=color)
    d.text((x, y + 96), label, font=font(26), fill=WHITE)
    d.text((x, y + 132), sub, font=font(20, False), fill=DIM)


def paste_pic(img, path, box, crop=None, pad=0):
    x0, y0, x1, y1 = box
    im = Image.open(path).convert("RGB")
    if crop:
        im = im.crop(crop)
    r = min((x1 - x0 - pad * 2) / im.width, (y1 - y0 - pad * 2) / im.height)
    im = im.resize((int(im.width * r), int(im.height * r)), Image.LANCZOS)
    px, py = x0 + ((x1 - x0) - im.width) // 2, y0 + ((y1 - y0) - im.height) // 2
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, im.width, im.height], radius=8, fill=255)
    img.paste(im, (px, py), mask)


def flow(d, x, y, w):
    stages = [
        ("采集", "V4L2 / 回放", (150, 170, 192), "彩色帧"),
        ("预处理", "灰度 + 降采样", ORANGE, "灰度图"),
        ("形态学", "Black-Hat", ORANGE, "增强图"),
        ("CFAR", "自适应阈值", ORANGE, "二值图"),
        ("候选", "8 连通 CCL", ORANGE, "候选表"),
        ("精判", "ZG330 NPU", GREEN, "置信度"),
        ("跟踪", "卡尔曼 + 匹配", CYAN, "航迹"),
        ("推流", "网页 MJPEG", CYAN, "画面"),
    ]
    bw, gap, bh = 238, 46, 108
    groups = [(0, 0, "PS", (150, 170, 192)), (1, 4, "PL", ORANGE), (5, 5, "NPU", GREEN), (6, 7, "PS", CYAN)]
    for a, b, label, col in groups:
        gx0 = x + a * (bw + gap)
        gx1 = x + b * (bw + gap) + bw
        d.line([(gx0, y + 14), (gx1, y + 14)], fill=col, width=2)
        d.text((gx0, y - 18), label, font=font(20), fill=col)

    for i, (head, sub, col, tag) in enumerate(stages):
        bx, by = x + i * (bw + gap), y + 34
        d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=10, fill=(10, 24, 40, 170), outline=col, width=2)
        d.text((bx + 16, by + 12), head, font=font(26), fill=WHITE)
        d.text((bx + 16, by + 52), sub, font=font(20, False), fill=GREY)
        d.text((bx + 16, by + bh + 10), tag, font=font(18, False), fill=col)
        if i < len(stages) - 1:
            ax, ay = bx + bw + 8, by + bh // 2
            d.line([(ax, ay), (ax + gap - 18, ay)], fill=(90, 108, 130), width=2)
            d.polygon([(ax + gap - 18, ay - 7), (ax + gap - 4, ay), (ax + gap - 18, ay + 7)], fill=(90, 108, 130))
    return y + 34 + bh + 46


def coverage(d, x, y, w):
    rows = [("全分辨率", 2, 20, (96, 165, 250)),
            ("2× 降采样", 4, 40, (129, 140, 248)),
            ("3× 降采样", 6, 60, PURPLE),
            ("4× 降采样", 50, 80, (192, 132, 252))]
    label_w, rh = 240, 38
    bar_w = w - label_w - 150
    scale = bar_w / 80
    for i, (name, a, b, c) in enumerate(rows):
        ry = y + i * rh
        d.text((x, ry + 6), name, font=font(22, False), fill=WHITE)
        bx = x + label_w
        d.line([(bx, ry + 18), (bx + bar_w, ry + 18)], fill=(55, 72, 94), width=6)
        d.line([(bx + a * scale, ry + 18), (bx + b * scale, ry + 18)], fill=c, width=6)
        d.text((bx + bar_w + 14, ry + 6), f"{a}~{b} px", font=font(19, mono=True), fill=GREY)
    ry = y + 4 * rh + 8
    d.text((x + label_w, ry), "四路合并后覆盖 2 ~ 80 px，中间无空档", font=font(22), fill=GREEN)
    return ry + 30


def main():
    img = photo_bg()
    # 内容区蒙版：上半部保留天空，下半部压暗保证文字可读
    panel = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    pd = ImageDraw.Draw(panel)
    pd.rectangle([0, 400, W, H - 90], fill=(8, 18, 32, 125))
    img = Image.alpha_composite(img, panel)
    d = ImageDraw.Draw(img)

    # 标题区
    d.text((M, 92), "2026 全国大学生嵌入式芯片与系统设计竞赛 · FPGA 创新设计赛道 · 复旦微方向",
           font=font(24, False), fill=GREY)
    d.text((M, 146), "低小慢空间目标智能检测与跟踪系统", font=font(102), fill=WHITE)
    d.text((M, 280), "PL 像素粗筛   ·   NPU 候选精判   ·   PS 航迹管理", font=font(38), fill=CYAN)
    d.text((M, 344), "FMQL30TAI 悟净 Lite    ARM 4×A53 @1 GHz    ZG330 8 TOPS INT8    78000 LUT @50 MHz",
           font=font(24, False), fill=GREY)

    # 关键数字
    y = 420
    cols = [(M, "16.6", "fps", "三域端到端帧率", "相机 → PL → NPU → 跟踪 → 推流", CYAN),
            (M + 560, "4.19", "ms", "PL 检测单帧", "512 位 PL-DDR", ORANGE),
            (M + 1120, "0.68", "ms", "NPU 候选判别", "cls128 · 121 算子", GREEN),
            (M + 1680, "2~80", "px", "目标尺寸覆盖", "全分辨率 + 三档降采样", PURPLE)]
    for i, (x, v, u, l, s, c) in enumerate(cols):
        metric(d, x, y, v, u, l, s, c)
        if i:
            d.line([(x - 26, y + 6), (x - 26, y + 158)], fill=(60, 78, 100), width=1)

    # 问题
    y = section(d, M, 640, "问题")
    items = [("目标只有几像素", "整图 CNN 下采样后几乎拿不到特征，<8 px 召回率仅 48.5%。"),
             ("对比度低、背景杂波", "真实场景是暗剪影；单路 Top-Hat 召回 55%，Black-Hat 后 86%。"),
             ("算力与目标数无关", "整帧推理每帧跑满网络，边缘端跑不动，也浪费。")]
    yy = y
    for head, body in items:
        d.text((M, yy), "—", font=font(26, False), fill=ORANGE)
        d.text((M + 34, yy), head + "：", font=font(26), fill=WHITE)
        hw = tw(d, head + "：", font(26))[0]
        d.text((M + 34 + hw, yy), body, font=font(24, False), fill=GREY)
        yy += 48
    d.text((M + 1240, y - 6), "解法", font=font(22, False), fill=GREY)
    d.text((M + 1240, y + 28), "PL 粗筛（毫秒级）\nNPU 只判个位数候选\nPS 管航迹与推流",
           font=font(24, False), fill=WHITE, spacing=10)

    # 方案
    y = section(d, M, 1000, "方案：一条流水线跑完检测与跟踪")
    y = flow(d, M, y, W - M * 2)

    # 创新点
    y = section(d, M, y + 26, "创新点")
    inn = [("01", "暗剪影形态学", "把增强方向从亮斑改为暗斑：单路 Black-Hat 召回 55%→86%，候选数比双路低 3.7 倍。"),
           ("02", "三域异构级联", "NPU 算力只作用在个位数候选上，端到端 16.6 fps。"),
           ("03", "逐像素等价验证", "RTL 与 OpenCV 参考逐像素比对：IP1 灰度化 0 误差，NPU 输出误差 0.002。"),
           ("04", "平台约束下落地", "绕开 Lite 未焊接接口，全部走 PS 侧通路；检测器作为自定义算子接入 AI_Mate。")]
    for i, (num, head, body) in enumerate(inn):
        cx = M + (i % 2) * 1100
        cy = y + (i // 2) * 170
        d.text((cx, cy + 4), num, font=font(20, mono=True), fill=DIM)
        d.text((cx + 46, cy), head, font=font(30), fill=WHITE)
        for j, line in enumerate(wrap(d, body, font(24, False), 980)):
            d.text((cx + 46, cy + 44 + j * 34), line, font=font(24, False), fill=(198, 210, 226))
    y += 2 * 170 + 10

    # 结果
    y = section(d, M, y + 30, "结果：板上实测")
    img_w = 1400
    paste_pic(img, os.path.join(FIG, "图9b_NPU检测效果.png"),
              [M, y, M + img_w, y + 380], crop=(0, 128, 1724, 445))
    rx = M + img_w + 70
    d.text((rx, y + 6), "NPU 整图检测 · 真实 720P 逐帧", font=font(22, False), fill=GREY)
    ty = y + 44
    for v, l, c in [("76.6% → 0.8%", "航迹确认后的虚警残留", ORANGE),
                    ("0.920", "mAP50（自研 YOLOv11n 单类）", GREEN),
                    ("13.1 s", "断电到服务就绪", CYAN),
                    ("84.4%", "三域位流 LUT（独立位流 61.9%）", PURPLE)]:
        d.text((rx, ty), v, font=font(36, mono=True), fill=c)
        d.text((rx, ty + 44), l, font=font(21, False), fill=GREY)
        ty += 78
    y += 420

    # 对比
    y = section(d, M, y + 10, "与传统整图 CNN 的差异")
    rows = [("检测方式", "整图一次推理", "PL 像素粗筛 + NPU 候选精判"),
            ("小目标能力", "<8 px 召回 48.5%", "覆盖 2~80 px"),
            ("算力开销", "与目标数量无关", "神经网络只算个位数候选"),
            ("端到端帧率", "5.92 fps（软件基线）", "16.6 fps（三域同板）")]
    rh = 66
    col1, col2 = 470, 760
    d.text((M, y), "维度", font=font(22), fill=GREY)
    d.text((M + col1, y), "传统做法", font=font(22), fill=GREY)
    d.text((M + col1 + col2, y), "本方案", font=font(22), fill=CYAN)
    d.line([(M, y + 38), (W - M, y + 38)], fill=LINE, width=2)
    for i, (a, b, c) in enumerate(rows):
        ry = y + 38 + i * rh
        d.text((M, ry + 18), a, font=font(23, False), fill=WHITE)
        d.text((M + col1, ry + 18), b, font=font(23, False), fill=GREY)
        d.text((M + col1 + col2, ry + 18), c, font=font(23), fill=CYAN)
        d.line([(M, ry + rh), (W - M, ry + rh)], fill=(48, 64, 84), width=1)

    # 能力边界
    y = section(d, M, y + 38 + len(rows) * rh + 50, "能力边界：一份硬件覆盖 2~80 px")
    y2 = coverage(d, M, y, W - M * 2)

    # 交付与复现
    y3 = section(d, M, y2 + 64, "交付与复现")
    d.text((M, y3), "仓库包含 PL 源码与约束、PS 应用、模型与量化校准集、测试数据与完整报告。",
           font=font(23, False), fill=GREY)
    d.text((M, y3 + 42), "板上复现：加载 ours3d_s5.bin，启动 init.d 服务，浏览器打开 :8080。",
           font=font(23, False), fill=GREY)

    # 页脚
    by = H - 78
    d.text((M, by), "全部指标为板上实测 ｜ 代码与文档：gitee.com/kkk3259/fmql30tai-low-slow-small-detect-track",
           font=font(22, False), fill=DIM)

    os.makedirs(OUT_DIR, exist_ok=True)
    img = img.convert("RGB")
    png = os.path.join(OUT_DIR, "作品海报_A2_v2.png")
    img.save(png, "PNG")
    img.save(os.path.join(OUT_DIR, "作品海报_A2_v2.pdf"), "PDF", resolution=150.0)
    print("saved", png, img.size)


if __name__ == "__main__":
    main()
