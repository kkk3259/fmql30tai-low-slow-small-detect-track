# -*- coding: utf-8 -*-
"""作品海报生成器 —— A2 竖版 420×594 mm（第二版）

修复首版问题：
  1. badge 用 Consolas 渲染中文 → 方块（改 cn_b）
  2. para 的 maxw 未扣除起始 x 偏移 → 文字压到右栏（逐处精算）
  3. 架构图框宽 148 装不下 "Top-Hat/Black-Hat" → 加宽到 176
  4. 下半部分空 1800 px → 左栏加实拍图，右栏加两张对比表
数据来源：docs/24、docs/27、docs/14 v0.6 的板上实测值，不虚构

用法：python tools/make_poster.py
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(encoding="utf-8")

# ============================================================
W_MM, H_MM, DPI = 420, 594, 150
W = round(W_MM / 25.4 * DPI)      # 2480
H = round(H_MM / 25.4 * DPI)      # 3508

BG, CARD, CARD_H, LINE = (10, 16, 28), (18, 27, 44), (25, 37, 57), (44, 60, 86)
CYAN, CYAN_D = (34, 211, 238), (14, 116, 144)
AMBER, GREEN, RED = (245, 158, 11), (52, 211, 153), (248, 113, 113)
TXT, TXT2, TXT3 = (240, 245, 250), (148, 163, 184), (94, 112, 138)

_FP = {
    "cn": r"C:\Windows\Fonts\msyh.ttc",
    "cn_b": r"C:\Windows\Fonts\msyhbd.ttc",
    "mono": r"C:\Windows\Fonts\consola.ttf",
    "mono_b": r"C:\Windows\Fonts\consolab.ttf",
}
_c = {}


def F(size, kind="cn"):
    k = (size, kind)
    if k not in _c:
        _c[k] = ImageFont.truetype(_FP[kind], size)
    return _c[k]


def card(d, xy, r=16, fill=CARD, outline=LINE, w=2):
    d.rounded_rectangle(xy, radius=r, fill=fill, outline=outline, width=w)


def wrap(d, s, font, maxw):
    out, cur = [], ""
    for seg in s.split(" "):
        cand = (cur + " " + seg) if cur else seg
        if d.textlength(cand, font=font) <= maxw:
            cur = cand
            continue
        if cur:
            out.append(cur)
        if d.textlength(seg, font=font) <= maxw:
            cur = seg
        else:
            cur = ""
            for ch in seg:
                if d.textlength(cur + ch, font=font) <= maxw:
                    cur += ch
                else:
                    out.append(cur)
                    cur = ch
    if cur:
        out.append(cur)
    return out


def para(d, x, y, s, font, fill, maxw, lh=None, maxlines=None):
    """段落：maxw 是**可用宽度**（已扣掉 x 偏移），返回结束 y"""
    lh = lh or round(font.size * 1.58)
    lines = wrap(d, s, font, maxw)
    if maxlines:
        lines = lines[:maxlines]
    for i, ln in enumerate(lines):
        d.text((x, y + i * lh), ln, font=font, fill=fill)
    return y + len(lines) * lh


def section(d, x, y, w, num, title, color=CYAN, tsize=46):
    if num:
        d.text((x, y), num, font=F(32, "mono_b"), fill=color)
        d.text((x + 60, y - 5), title, font=F(tsize, "cn_b"), fill=TXT)
    else:
        d.text((x, y - 5), title, font=F(tsize, "cn_b"), fill=TXT)
    ny = y + 60
    d.line([x, ny, x + w, ny], fill=color, width=3)
    return ny + 24


def badge(d, xr, y, s, col, size=28, h=42):
    """右上角标签：中文用 cn_b，纯 ASCII 用 mono_b"""
    fnt = F(size, "mono_b" if s.isascii() else "cn_b")
    tw = d.textlength(s, font=fnt)
    x0 = xr - tw - 32
    d.rounded_rectangle([x0, y, xr, y + h], radius=h // 2,
                        fill=CARD_H, outline=col, width=2)
    d.text((x0 + 16, y + (h - size) // 2 - 3), s, font=fnt, fill=col)


# ============================================================
img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)

for i in range(14):                                  # 顶部彩条
    t = i / 13
    d.line([0, i, W, i], fill=(round(CYAN[0] * (1 - t) + AMBER[0] * t),
                               round(CYAN[1] * (1 - t) + AMBER[1] * t),
                               round(CYAN[2] * (1 - t) + AMBER[2] * t)))

M = 90
WI = W - 2 * M

# ---------------- 标题区 ----------------
d.text((M, 92), "2026 全国大学生嵌入式芯片与系统设计竞赛 · FPGA 创新设计赛道 · 复旦微方向",
       font=F(31, "cn"), fill=TXT3)
d.text((M, 142), "低小慢空间目标智能检测与跟踪系统", font=F(110, "cn_b"), fill=TXT)
d.text((M, 280), "FPGA · NPU · PS  三域异构协同的端侧实时方案", font=F(50, "cn"), fill=CYAN)

tx = M
for t in ["FMQL30TAI 悟净 Lite", "ZG330 NPU 8 TOPS@INT8", "640×480 实时链路"]:
    tw = d.textlength(t, font=F(29, "cn"))
    d.rounded_rectangle([tx, 364, tx + tw + 38, 418], radius=27,
                        fill=CARD_H, outline=CYAN_D, width=2)
    d.text((tx + 19, 377), t, font=F(29, "cn"), fill=TXT2)
    tx += tw + 54

# ---------------- 指标卡 ----------------
KY, KH, gap = 458, 240, 30
cw = (WI - 3 * gap) // 4
for i, (val, unit, label, sub, col) in enumerate([
    ("27.6", "fps", "PL 检测帧率", "13.8 ms / 帧", CYAN),
    ("2~80", "px", "目标尺寸覆盖", "多尺度合并", GREEN),
    ("7.96", "ms", "NPU 单帧推理", "8 TOPS  INT8", AMBER),
    ("41", "ms", "端到端时延", "采集 → 画框", CYAN),
]):
    cx = M + i * (cw + gap)
    card(d, [cx, KY, cx + cw, KY + KH], r=20)
    d.rounded_rectangle([cx, KY, cx + cw, KY + 7], radius=4, fill=col)
    d.text((cx + 30, KY + 40), val, font=F(94, "mono_b"), fill=col)
    d.text((cx + 30 + d.textlength(val, font=F(94, "mono_b")) + 10, KY + 90),
           unit, font=F(36, "cn"), fill=col)
    d.text((cx + 30, KY + 158), label, font=F(35, "cn_b"), fill=TXT)
    d.text((cx + 30, KY + 204), sub, font=F(27, "cn"), fill=TXT3)

# ============================================================
BODY_Y = 762
LX, LW = M, 1392
RX = M + LW + 56
RW = WI - LW - 56

# ---------------- 左 ① ----------------
y = BODY_Y
y = section(d, LX, y, LW, "01", "为什么「低小慢」难 —— 四个实测结论")
FOUR = [
    ("目标小", "全图 CNN 是盲区：实测 <8 px 目标 YOLO 召回仅 48.5%，而「低小慢」定义恰在 <10 px，两者错位。"),
    ("对比度低", "真实场景目标是暗点剪影，而非亮背景上的暗目标 —— 单路 Top-Hat 召回 55%，改 Black-Hat 后 86%。"),
    ("背景杂波", "地板纹理、显示器边框产生大量虚警，跟踪三帧确认只能压 0.7%（63.01 → 62.59）。"),
    ("CFAR 自抑制", "目标越大 → 窗内 σ 越大 → 门限越高 → 越检不出。实测 SE 5→61 都只检 2~6 px，放宽 MAX_AREA 完全无效。"),
]
for i, (name, desc) in enumerate(FOUR):
    ry = y + i * 106
    d.text((LX + 2, ry), "▪", font=F(28, "cn"), fill=AMBER)
    d.text((LX + 32, ry - 4), name, font=F(36, "cn_b"), fill=AMBER)
    nx = LX + 32 + d.textlength(name, font=F(36, "cn_b")) + 18
    para(d, nx, ry + 2, desc, F(30, "cn"), TXT2, maxw=LX + LW - nx, maxlines=2)
y += 4 * 106 + 6

# ---------------- 左 ② ----------------
y = section(d, LX, y, LW, "02", "三域串联架构 —— 一条流水线跑完检测到跟踪")
STAGES = [
    ("摄像头", ["USB UVC"], CYAN_D, 0),
    ("PS 解码", ["A53"], CYAN_D, 0),
    ("PL 检测", ["Black-Hat", "CFAR+CCL"], CYAN, 1),
    ("候选表", ["0x10 窗口", "64 个"], AMBER, 1),
    ("PS 拼网格", ["8×8×64²"], CYAN_D, 0),
    ("NPU 精判", ["ZG330"], AMBER, 1),
    ("卡尔曼", ["PS"], CYAN_D, 0),
    ("推流", ["MJPEG"], CYAN_D, 0),
]
BW, BH, BGAP = 160, 116, 14
row_w = len(STAGES) * BW + (len(STAGES) - 1) * BGAP
bx = LX + (LW - row_w) // 2
for i, (name, subs, col, key) in enumerate(STAGES):
    x0 = bx + i * (BW + BGAP)
    card(d, [x0, y, x0 + BW, y + BH], r=12,
         fill=CARD_H if key else CARD, outline=col, w=3 if key else 1)
    d.text((x0 + BW // 2, y + 16), name, font=F(25, "cn_b"), fill=TXT, anchor="ma")
    for j, s in enumerate(subs):
        d.text((x0 + BW // 2, y + 56 + j * 26), s, font=F(20, "cn"), fill=TXT3, anchor="ma")
    if i < len(STAGES) - 1:
        ax = x0 + BW + 1
        d.polygon([(ax, y + BH // 2 - 8), (ax + 12, y + BH // 2), (ax, y + BH // 2 + 8)], fill=TXT3)
y += BH + 16
d.text((LX, y), "高亮框 = 三域各自的独有能力；同色箭头 = 数据流方向",
       font=F(24, "cn"), fill=TXT3)
y += 38

y = section(d, LX, y, LW, "", "分工与实测指标", CYAN_D, 38)
for i, (dom, sub, duty, perf) in enumerate([
    ("PL", "FPGA", "Top-Hat / Black-Hat 形态学 → CFAR 门限 → 8 连通 CCL 质心", "13.8 ms · 27.6 fps"),
    ("NPU", "ZG330", "候选网格二分类精判（128×128 单块 / 512×512 网格）", "7.96 ms · mAP50 0.920"),
    ("PS", "4×A53", "V4L2 解码 → 裁剪拼网格 → 卡尔曼跟踪 → MJPEG 推流", "跟踪 2.8 ms · 编码 12.9 ms"),
]):
    ry = y + i * 84
    card(d, [LX, ry, LX + LW, ry + 74], r=12, w=1)
    d.text((LX + 18, ry + 10), dom, font=F(27, "mono_b"), fill=CYAN)
    d.text((LX + 18, ry + 44), sub, font=F(19, "cn"), fill=TXT3)
    d.text((LX + 118, ry + 24), duty, font=F(27, "cn"), fill=TXT2)
    d.text((LX + LW - 22, ry + 24), perf, font=F(26, "mono"), fill=GREEN, anchor="ra")
y += 3 * 84 + 4

# ---------------- 左 ③ ----------------
y = section(d, LX, y, LW, "03", "四个技术亮点（全部有板上实测支撑）")
HL = [
    ("① 形态学方向修正", "实测发现真实场景目标是「暗点剪影」：单路 Top-Hat 召回 69% → Black-Hat 87% → 双路 94%。RTL 新增 MODE 参数支持运行时切换。", "召回 55% → 86%", CYAN),
    ("② 软件多尺度绕开硬件上限", "CFAR 在 31×31 窗内对大而均匀亮块自抑制，调 K 无法解决。改在 PS 侧跑全分辨率 + 2×/3×/4× 降采样四遍，触发后按坐标合并。", "覆盖 2~80 px", GREEN),
    ("③ 时域差分 + 线状剔除", "帧差只保留相对上一帧有变化的候选，静止纹理直接滤掉。线状剔除仅对边带生效 —— 全图生效会把排成一行的真目标一起删掉（raw 16→2）。", "静态虚警显著下降", AMBER),
    ("④ 候选表 5 → 64", "AXI-Lite 是 6 位地址，0x40 绕回 0x00 会误触发一帧。改用 0x10「写索引/读数据」同址窗口，113 字装下 64 个候选。", "单次读回 64 候选", CYAN),
]
for i, (name, desc, gain, col) in enumerate(HL):
    ry = y + i * 152
    d.rounded_rectangle([LX, ry + 2, LX + 6, ry + 108], radius=3, fill=col)
    d.text((LX + 24, ry - 4), name, font=F(36, "cn_b"), fill=col)
    badge(d, LX + LW, ry - 10, gain, col, 26, 40)
    para(d, LX + 24, ry + 46, desc, F(29, "cn"), TXT2, maxw=LW - 26, maxlines=3)
y += 4 * 152 + 6

# ---------------- 左 ④ 实拍图 ----------------
y = section(d, LX, y, LW, "04", "板上实拍 —— 实时运行中的检测界面")

PHOTO = r"D:\lowslow\_roi_check\board_snap5.jpg"
if os.path.exists(PHOTO):
    pim = Image.open(PHOTO).convert("RGB")
    pw = 940
    ph = round(pim.height * pw / pim.width)
    pim = pim.resize((pw, ph), Image.LANCZOS)
    px, py = LX, y
    img.paste(pim, (px, py))
    d.rounded_rectangle([px, py, px + pw, py + ph], radius=14, outline=CYAN, width=3)

    nx = px + pw + 34
    nw = LX + LW - nx
    d.text((nx, py + 4), "画面里是什么", font=F(32, "cn_b"), fill=CYAN)
    notes = [
        "640×360 灰度实时流，MJPEG 编码 12.9 ms/帧",
        "HUD 左上角为分段耗时：PL / raw / stable / cap / fps",
        "绿色框为 PL 输出的候选，右侧数字是 area / peak",
        "当前场景无真实目标，框都在地板纹理与家具边缘 —— 正是需要 NPU 精判过滤的虚警",
    ]
    yy = py + 50
    for n in notes:
        d.text((nx, yy), "·", font=F(28, "cn"), fill=AMBER)
        yy = para(d, nx + 22, yy, n, F(26, "cn"), TXT2, maxw=nw - 24, maxlines=3) + 12
    y = py + max(ph, yy - py) + 24
else:
    y += 40

# ============================================================
# 右栏
# ============================================================
ry = BODY_Y

ry = section(d, RX, ry, RW, "05", "尺寸覆盖实测", CYAN, 42)
d.text((RX, ry), "单目标合成靶 · 中心 (320,180) · 真机", font=F(25, "cn"), fill=TXT3)
ry += 38
for i, (size, chan) in enumerate([
    ("2 ~ 4 px", "全分辨率"), ("6 ~ 12 px", "全分辨率 + 2×"),
    ("15 ~ 24 px", "全分辨率 + 2×"), ("30 ~ 40 px", "2× + 3×"),
    ("50 ~ 70 px", "3× + 4×"),
]):
    cy = ry + i * 58
    card(d, [RX, cy, RX + RW, cy + 48], r=10, w=1)
    d.text((RX + 16, cy + 11), size, font=F(26, "mono_b"), fill=TXT)
    d.text((RX + 202, cy + 14), chan, font=F(23, "cn"), fill=TXT3)
    d.text((RX + RW - 24, cy + 7), "√", font=F(30, "cn_b"), fill=GREEN, anchor="ra")
ry += 5 * 58 + 10
card(d, [RX, ry, RX + RW, ry + 62], r=12, fill=(13, 38, 32), outline=GREEN, w=2)
d.text((RX + RW // 2, ry + 13), "合并后覆盖 2 ~ 80 px", font=F(31, "cn_b"), fill=GREEN, anchor="ma")
ry += 88

ry = section(d, RX, ry, RW, "06", "分段耗时拆解", CYAN, 42)
for i, (name, ms, col) in enumerate([
    ("采集 cap", 32.2, CYAN_D), ("PL 检测", 13.8, CYAN),
    ("跟踪 trk", 2.8, CYAN_D), ("编码 enc", 12.9, CYAN_D),
]):
    sy = ry + i * 70
    d.text((RX, sy), name, font=F(25, "cn"), fill=TXT2)
    d.text((RX + RW, sy), "%.1f ms" % ms, font=F(25, "mono_b"), fill=col, anchor="ra")
    bw = int((RW - 6) * ms / 34.0)
    d.rounded_rectangle([RX, sy + 34, RX + RW, sy + 52], radius=9, fill=(27, 39, 58))
    d.rounded_rectangle([RX, sy + 34, RX + bw, sy + 52], radius=9, fill=col)
ry += 4 * 70 + 2
card(d, [RX, ry, RX + RW, ry + 90], r=12, fill=CARD_H, outline=CYAN, w=2)
d.text((RX + 20, ry + 12), "端到端时延", font=F(26, "cn"), fill=TXT2)
d.text((RX + 20, ry + 44), "41 ms", font=F(44, "mono_b"), fill=CYAN)
d.text((RX + RW - 20, ry + 50), "27.6 fps 稳定", font=F(24, "cn"), fill=GREEN, anchor="ra")
ry += 112

ry = section(d, RX, ry, RW, "07", "两种工作模式", CYAN, 42)
for i, (mode, fps, rec, note, col) in enumerate([
    ("高速", "20.8 fps", "48.5%", "全图 CNN 一次推理", AMBER),
    ("高召回", "14.3 fps", "86.0%", "PL 候选 + NPU 精判级联", GREEN),
]):
    cy = ry + i * 92
    card(d, [RX, cy, RX + RW, cy + 82], r=12, w=1, outline=col)
    d.text((RX + 16, cy + 10), mode, font=F(28, "cn_b"), fill=col)
    d.text((RX + 16, cy + 48), note, font=F(21, "cn"), fill=TXT3)
    d.text((RX + RW - 18, cy + 8), fps, font=F(28, "mono_b"), fill=TXT, anchor="ra")
    d.text((RX + RW - 18, cy + 46), "<8px 召回 " + rec, font=F(22, "cn"), fill=col, anchor="ra")
ry += 2 * 92 + 8

ry = section(d, RX, ry, RW, "08", "NPU 模型三件套", CYAN, 42)
for i, (m, inp, out, acc) in enumerate([
    ("cls128", "128×128", "2 类", "90~95%"),
    ("grid16", "512×512", "16 格", "87~97%"),
    ("grid64", "512×512", "64 格", "72~85%"),
]):
    cy = ry + i * 56
    d.text((RX + 4, cy), m, font=F(25, "mono_b"), fill=CYAN)
    d.text((RX + 148, cy + 2), inp, font=F(23, "mono"), fill=TXT2)
    d.text((RX + 320, cy + 2), out, font=F(23, "cn"), fill=TXT2)
    d.text((RX + RW, cy + 2), acc, font=F(23, "mono_b"), fill=GREEN, anchor="ra")
d.line([RX, ry + 3 * 56 + 2, RX + RW, ry + 3 * 56 + 2], fill=LINE, width=1)
ry += 3 * 56 + 20

ry = section(d, RX, ry, RW, "09", "结论与当前状态", CYAN, 42)
for i, (mark, txt, col) in enumerate([
    ("√", "三域已在目标平台完成各自实测", GREEN),
    ("√", "合并位流的 IP 数据通路逐位无损", GREEN),
    ("!", "NPU 的 DMA 通路因引脚裁剪待修复", AMBER),
]):
    cy = ry + i * 64
    d.text((RX + 2, cy - 4), mark, font=F(32, "cn_b"), fill=col)
    para(d, RX + 40, cy, txt, F(26, "cn"), TXT2, maxw=RW - 44, maxlines=2)
ry += 3 * 64 + 6
ry = para(d, RX, ry,
          "级联的价值在召回，不在速度 —— 「低小慢」场景下这个取舍是必要的。",
          F(24, "cn"), AMBER, maxw=RW, maxlines=3) + 34

# ---------------- 右 ⑩ 与传统方案的关键差异 ----------------
ry = section(d, RX, ry, RW, "10", "与传统做法的关键差异", CYAN, 42)
DIFF = [
    ("检测范式", "全图 CNN 一次推理", "PL 候选 → NPU 精判级联"),
    ("目标尺寸", "固定尺度，<10 px 漏检", "多尺度合并 2~80 px"),
    ("形态学方向", "Top-Hat（默认亮背景）", "Black-Hat（实测暗点剪影）"),
    ("候选容量", "5 个", "64 个（0x10 索引窗口）"),
    ("计算分工", "纯软件（A53 做主算）", "PL / NPU / PS 三域分工"),
]
d.text((RX + 4, ry), "维度", font=F(22, "cn"), fill=TXT3)
d.text((RX + 164, ry), "传统做法", font=F(22, "cn"), fill=TXT3)
d.text((RX + 476, ry), "本方案", font=F(22, "cn"), fill=CYAN)
ry += 34
d.line([RX, ry, RX + RW, ry], fill=LINE, width=1)
ry += 10
for i, (dim, old, new) in enumerate(DIFF):
    cy = ry + i * 84
    if i % 2 == 0:
        d.rounded_rectangle([RX, cy - 4, RX + RW, cy + 72], radius=8, fill=CARD)
    d.text((RX + 8, cy + 6), dim, font=F(23, "cn_b"), fill=TXT2)
    for j, ln in enumerate(wrap(d, old, F(22, "cn"), 300)):
        d.text((RX + 164, cy + 4 + j * 30), ln, font=F(22, "cn"), fill=TXT3)
    for j, ln in enumerate(wrap(d, new, F(22, "cn"), RW - 484)):
        d.text((RX + 476, cy + 4 + j * 30), ln, font=F(22, "cn"), fill=GREEN)
ry += 5 * 84

# ============================================================
# 底部
# ============================================================
FY = 3306
d.line([M, FY, W - M, FY], fill=LINE, width=2)
for i, (k, v) in enumerate([
    ("平台", "FMQL30TAI 悟净 Lite ｜ PL 78,600 LUT @50 MHz ｜ PS 4×A53 @1 GHz ｜ NPU ZG330 8 TOPS INT8"),
    ("数据", "全部为板上实测：docs/24（验收汇总）· docs/27（链路调优）· docs/14 v0.6（接口约定）"),
]):
    fy = FY + 26 + i * 52
    d.text((M, fy), k, font=F(26, "cn_b"), fill=CYAN_D)
    d.text((M + 74, fy), v, font=F(24, "cn"), fill=TXT3)

# ============================================================
# 自检：任何区块越到底部栏就报错
# ============================================================
over = []
if y > FY - 8:
    over.append("左栏结束 y=%.0f 超过底部 %.0f" % (y, FY))
if ry > FY - 8:
    over.append("右栏结束 y=%.0f 超过底部 %.0f" % (ry, FY))
for o in over:
    print("  [WARN] 版面溢出：" + o)
if not over:
    print("   版面检查通过（左栏结束 y=%.0f，右栏结束 y=%.0f，底部 %.0f）" % (y, ry, FY))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "docs", "poster")
os.makedirs(OUT, exist_ok=True)
png = os.path.join(OUT, "作品海报_A2.png")
img.save(png, "PNG", optimize=True, dpi=(DPI, DPI))
print("  PNG : %s  (%.1f MB, %d×%d, %d DPI)" % (png, os.path.getsize(png) / 1e6, W, H, DPI))
pdf = os.path.join(OUT, "作品海报_A2.pdf")
img.save(pdf, "PDF", resolution=DPI)
print("  PDF : %s  (%.1f MB)" % (pdf, os.path.getsize(pdf) / 1e6))
print("  尺寸: %.0f × %.0f mm" % (W / DPI * 25.4, H / DPI * 25.4))
