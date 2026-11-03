# -*- coding: utf-8 -*-
"""报告补充图生成器 —— 6 张数据图（全部基于板上实测，不虚构）

输出到 report/figs/：
  图6_PL检测链路模块框图.png   重画（原图写 Top-Hat 5×5，实为 Black-Hat SE=21）
  图13_帧率配置对比.png
  图14_耗时分解.png
  图15_候选数与帧率.png
  图16_尺寸覆盖矩阵.png
  图17_形态学方向权衡.png

用法：D:\\lowslow\\venv\\Scripts\\python.exe report\\make_figs.py
"""
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

# ---- 中文字体 ----
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "figs")
os.makedirs(OUT, exist_ok=True)

BLUE, ORANGE, GREEN, RED, GRAY = "#2E5C8A", "#E07B39", "#3C8C5A", "#C0392B", "#7F8C8D"
LIGHT_BLUE, LIGHT_YEL = "#DCE8F5", "#FDF2D0"


def save(fig, name, dpi=170):
    p = os.path.join(OUT, name)
    fig.savefig(p, dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("   %-30s %7.0f KB" % (name, os.path.getsize(p) / 1024))


# ============================================================
# 图 6（重画）：PL 检测链路
# ============================================================
def fig6():
    fig, ax = plt.subplots(figsize=(13.2, 5.6))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 42)
    ax.axis("off")

    ax.text(50, 39.2, "PL 检测链路：Black-Hat（MODE 可切）→ CFAR → 候选提取",
            ha="center", va="center", fontsize=17, fontweight="bold", color="#1B3A5C")

    boxes = [
        (6.0, "输入", "8 位灰度帧\n640×360", LIGHT_BLUE, BLUE),
        (27.0, "Black-Hat", "形态学增强（提暗点剪影）\nSE=21×21，MODE 可在\nTop-Hat / Black-Hat 间切换", LIGHT_YEL, ORANGE),
        (50.0, "CFAR 门限", "局部均值 + K×标准差\n+ 最低门限\nK=1.0，统计窗 31×31", LIGHT_YEL, ORANGE),
        (73.0, "候选提取", "8 连通 CCL\n质心 / 面积(16 位) / 峰值", LIGHT_YEL, ORANGE),
        (92.5, "输出", "候选表\n最多 64 个", LIGHT_BLUE, BLUE),
    ]
    for x, title, sub, fc, ec in boxes:
        w = 17 if title not in ("输入", "输出") else 10
        b = FancyBboxPatch((x - w / 2, 20), w, 11, boxstyle="round,pad=0.5,rounding_size=1",
                           linewidth=2, edgecolor=ec, facecolor=fc)
        ax.add_patch(b)
        ax.text(x, 27.8, title, ha="center", va="center", fontsize=13.5, fontweight="bold", color="#1B3A5C")
        ax.text(x, 23.6, sub, ha="center", va="center", fontsize=9.4, color="#404040", linespacing=1.5)

    arrows = [(11.2, 18.2), (35.7, 41.2), (58.7, 64.2), (81.7, 87.3)]
    for x0, x1 in arrows:
        ax.add_patch(FancyArrowPatch((x0, 25.5), (x1, 25.5), arrowstyle="-|>",
                                     mutation_scale=17, linewidth=1.9, color=BLUE))
    for x, t in [(23.5, "AXI4-Stream\ntdata/tvalid/tlast"),
                 (46.5, "AXI4-Stream\ntdata/tvalid/tlast"),
                 (69.5, "AXI4-Stream\ntdata/tvalid/tlast")]:
        ax.text(x, 29.6, t, ha="center", va="bottom", fontsize=8.6, color="#B5651D", linespacing=1.4)

    notes = [
        " 形态学方向经实测修正：真实场景目标是「暗点剪影」，单路 Top-Hat 召回仅 55.0%，改 Black-Hat 后 86.0%（同为 86% 召回时候选数 47.5 vs 175.5，相差 3.7 倍）。",
        " CFAR 存在自抑制：目标越大 → 窗内 σ 越高 → 门限被自身抬高。实测 SE 由 5 增大到 61、MAX_AREA 由 200 放宽到 5000 均无效，故 15 px 以上改由软件多尺度覆盖。",
        " 流式结构：各模块「行缓存 + 流水线」，仅缓存 3~5 行，存储由约 230 KB 降至约 2 KB；定点运算用移位实现，不占 DSP。",
    ]
    y = 15.0
    for n in notes:
        ax.text(3, y, n, fontsize=9.2, color="#333333", va="top", wrap=True)
        y -= 3.6

    ax.text(50, 0.8, "候选表经 AXI-Lite 0x10 索引窗口回传（113 字 / 64 候选）；0x18~0x38 为 36 字节兼容视图",
            ha="center", fontsize=9, color=GRAY, style="italic")

    save(fig, "图6_PL检测链路模块框图.png")


# ============================================================
# 图 1（重画）：系统整体框图
#   原图两处问题：③ 未标形态学方向（与图 6 不一致）；
#                 ⑧ 写「HDMI 显示器 720P60」—— 为实测证伪，实际是网页 MJPEG 推流
# ============================================================
def fig1():
    fig, ax = plt.subplots(figsize=(13.6, 6.4))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 46)
    ax.axis("off")

    ax.text(50, 43.4, "低小慢空间目标智能检测与跟踪系统 · 整体框图",
            ha="center", va="center", fontsize=16.5, fontweight="bold", color="#1B3A5C")

    # ---- 三层色带 ----
    bands = [(3.0, 12.0, "PS", "#DCE8F5", BLUE),
             (15.5, 46.0, "PL 可编程逻辑", "#FDF2D0", ORANGE),
             (62.0, 11.5, "NPU", "#E3F2E8", GREEN),
             (74.0, 23.0, "PS", "#DCE8F5", BLUE)]
    for x, w, name, fc, ec in bands:
        ax.add_patch(FancyBboxPatch((x, 36.6), w, 3.6, boxstyle="square,pad=0",
                                    facecolor=fc, edgecolor=ec, linewidth=1.4, alpha=0.85))
        ax.text(x + w / 2, 38.4, "【%s】" % name, ha="center", va="center",
                fontsize=11, fontweight="bold", color="#1B3A5C")

    # ---- 8 个环节 ----
    stages = [
        (8.5,  "① 采集调度",    "V4L2 / 序列回放",       "#DCE8F5", BLUE),
        (21.0, "② 图像预处理",  "灰度化 + 2× 降采样",     "#FDF2D0", ORANGE),
        (33.5, "③ 形态学增强",  "Top-Hat / Black-Hat\nMODE 可切，SE=21", "#FDF2D0", ORANGE),
        (46.0, "④ CFAR 检测",   "K=1.0，窗 31×31",       "#FDF2D0", ORANGE),
        (58.5, "⑤ 候选提取",    "8 连通 CCL\n面积 16 位",  "#FDF2D0", ORANGE),
        (71.0, "⑥ ROI 精判别",  "ZG330 NPU\n7.955 ms/帧",  "#E3F2E8", GREEN),
        (83.5, "⑦ 多目标跟踪",  "卡尔曼 + 贪心匹配",       "#DCE8F5", BLUE),
        (95.0, "⑧ 输出与显示",  "网页 MJPEG 推流",        "#DCE8F5", BLUE),
    ]
    for x, title, sub, fc, ec in stages:
        ax.add_patch(FancyBboxPatch((x - 5.4, 24.0), 10.8, 9.4,
                                    boxstyle="round,pad=0.32,rounding_size=0.7",
                                    facecolor=fc, edgecolor=ec, linewidth=1.7))
        ax.text(x, 31.2, title, ha="center", va="center", fontsize=9.8,
                fontweight="bold", color="#1B3A5C")
        ax.text(x, 27.3, sub, ha="center", va="center", fontsize=7.8,
                color="#404040", linespacing=1.45)

    for i in range(len(stages) - 1):
        x0 = stages[i][0] + 5.4
        x1 = stages[i + 1][0] - 5.4
        ax.add_patch(FancyArrowPatch((x0 + 0.15, 28.7), (x1 - 0.15, 28.7),
                                     arrowstyle="-|>", mutation_scale=13,
                                     linewidth=1.5, color="#7F8C8D"))

    # ---- 输入 / 输出 ----
    ax.add_patch(FancyBboxPatch((3.1, 8.5), 10.8, 7.6, boxstyle="round,pad=0.3,rounding_size=0.7",
                                facecolor="#ECEFF1", edgecolor=GRAY, linewidth=1.5))
    ax.text(8.5, 13.4, "USB 摄像头", ha="center", fontsize=9.4, fontweight="bold", color="#37474F")
    ax.text(8.5, 10.6, "640×480 MJPG\n→ 裁 640×360", ha="center", fontsize=7.6,
            color="#546E7A", linespacing=1.4)
    ax.add_patch(FancyArrowPatch((8.5, 16.3), (8.5, 23.8), arrowstyle="-|>",
                                 mutation_scale=14, linewidth=1.6, color=GRAY))

    ax.add_patch(FancyBboxPatch((89.6, 8.5), 10.8, 7.6, boxstyle="round,pad=0.3,rounding_size=0.7",
                                facecolor="#ECEFF1", edgecolor=GRAY, linewidth=1.5))
    ax.text(95.0, 13.4, "上位机浏览器", ha="center", fontsize=9.4, fontweight="bold", color="#37474F")
    ax.text(95.0, 10.6, "http://<板IP>:8080\n（无需专用客户端）", ha="center", fontsize=7.6,
            color="#546E7A", linespacing=1.4)
    ax.add_patch(FancyArrowPatch((95.0, 23.8), (95.0, 16.3), arrowstyle="-|>",
                                 mutation_scale=14, linewidth=1.6, color=GRAY))

    # ---- 数据流标注 ----
    flows = [(14.9, "彩色帧"), (27.4, "灰度帧"), (39.9, "增强图"),
             (52.4, "二值图"), (64.9, "候选列表"), (77.4, ""), (89.9, "航迹列表")]
    for x, name in flows:
        if name:
            ax.text(x, 21.6, name, ha="center", fontsize=7.6, color="#B5651D")

    # ---- 实测指标条 ----
    ax.add_patch(FancyBboxPatch((3.0, 1.2), 94.0, 5.4,
                                boxstyle="round,pad=0.25,rounding_size=0.5",
                                facecolor="#EAF2FB", edgecolor=BLUE, linewidth=1.3))
    ax.text(50, 5.1, "实测指标（640×360，板上真机）", ha="center", fontsize=9.6,
            fontweight="bold", color="#1B3A5C")
    metrics = [
        ("PL 四尺度", "13.8 ms / 24.3 fps"),
        ("PL 单遍", "10.6 ms / 40.5 fps"),
        ("NPU 单帧", "7.955 ms"),
        ("端到端时延", "41~43 ms"),
        ("尺寸覆盖", "2 ~ 80 px"),
        ("候选容量", "64 个"),
    ]
    for i, (k, v) in enumerate(metrics):
        x = 9.5 + i * 15.6
        ax.text(x, 3.35, k, ha="center", fontsize=7.6, color="#5A6F85")
        ax.text(x, 2.05, v, ha="center", fontsize=8.4, fontweight="bold", color=BLUE)

    save(fig, "图1_系统整体框图.png")


# ============================================================
# 图 13：帧率配置对比
# ============================================================
def fig13():
    cfg = ["灰度\n单遍·5候选", "彩色\n四尺度·5候选", "灰度\n四尺度·5候选", "灰度\n四尺度·5候选",
           "彩色\n四尺度·47候选"]
    fps = [40.5, 24.0, 24.3, 19.9, 7.9]
    pl = [12.5, 14.3, 14.5, 16.9, 13.8]
    enc = [13.8, 31.4, 14.9, 14.0, 14.0]
    colors = [GREEN, ORANGE, BLUE, BLUE, RED]

    fig, axes = plt.subplots(1, 2, figsize=(13.2, 5.4))

    ax = axes[0]
    bars = ax.bar(range(len(cfg)), fps, color=colors, width=0.62, edgecolor="white", linewidth=1.2)
    for i, v in enumerate(fps):
        ax.text(i, v + 0.9, "%.1f" % v, ha="center", fontsize=12, fontweight="bold", color="#222")
    ax.set_xticks(range(len(cfg)))
    ax.set_xticklabels(cfg, fontsize=9.2)
    ax.set_ylabel("端到端帧率 (fps)", fontsize=11)
    ax.set_title("同一硬件、同一位流下的五种配置（实测）", fontsize=13, fontweight="bold", pad=12)
    ax.set_ylim(0, 47)
    ax.grid(axis="y", alpha=0.28, linestyle="--")
    ax.axhline(30, color=GRAY, linestyle=":", linewidth=1.2, alpha=0.7)
    ax.text(len(cfg) - 0.4, 30.9, "相机上限 30 fps", fontsize=8.6, color=GRAY, ha="right")
    ax.text(0.5, 0.06, " 候选数放开到 47 后\n帧率跌至 7.9 fps", transform=ax.transAxes,
            fontsize=9.4, color=RED, ha="center",
            bbox=dict(boxstyle="round,pad=0.45", fc="#FDECEA", ec=RED, lw=1.1))

    ax = axes[1]
    x = np.arange(len(cfg))
    ax.bar(x, pl, width=0.55, label="PL 单帧", color=BLUE)
    ax.bar(x, enc, width=0.55, bottom=pl, label="JPEG 编码", color=ORANGE, alpha=0.85)
    ax.set_xticks(x)
    ax.set_xticklabels(cfg, fontsize=9.2)
    ax.set_ylabel("耗时 (ms)", fontsize=11)
    ax.set_title("耗时构成：彩色编码翻倍，但整链帧率几乎不掉", fontsize=13, fontweight="bold", pad=12)
    ax.legend(fontsize=10, loc="upper left")
    ax.grid(axis="y", alpha=0.28, linestyle="--")
    ax.text(0.5, 0.90, "瓶颈在采集（约 33 ms），不在编码", transform=ax.transAxes,
            fontsize=9.6, color="#1B3A5C", ha="center", style="italic")

    fig.tight_layout()
    save(fig, "图13_帧率配置对比.png")


# ============================================================
# 图 14：耗时分解（端到端 41 ms）
# ============================================================
def fig14():
    stages = ["采集 cap", "PL 检测", "跟踪 trk", "编码 enc"]
    vals = [32.2, 13.8, 2.8, 12.9]
    colors = [GRAY, BLUE, GREEN, ORANGE]

    fig, axes = plt.subplots(1, 2, figsize=(13.2, 4.9))

    ax = axes[0]
    left = 0
    for s, v, c in zip(stages, vals, colors):
        ax.barh(0, v, left=left, height=0.5, color=c, edgecolor="white", linewidth=2, label=s)
        if v > 5:
            ax.text(left + v / 2, 0, "%.1f" % v, ha="center", va="center",
                    fontsize=11, color="white", fontweight="bold")
        left += v
    ax.set_xlim(0, 66)
    ax.set_yticks([])
    ax.set_xlabel("耗时 (ms)", fontsize=11)
    ax.set_title("分段耗时（四段串行相加 = 61.7 ms，实测端到端 41 ms 说明有流水重叠）",
                 fontsize=11.5, fontweight="bold", pad=12)
    ax.legend(ncol=4, fontsize=9.4, loc="upper center", bbox_to_anchor=(0.5, -0.22))

    ax = axes[1]
    bars = ax.barh(stages[::-1], vals[::-1], color=colors[::-1], height=0.56,
                   edgecolor="white", linewidth=1.4)
    for b, v in zip(bars, vals[::-1]):
        ax.text(v + 0.6, b.get_y() + b.get_height() / 2, "%.1f ms" % v,
                va="center", fontsize=11, fontweight="bold")
    ax.set_xlim(0, 40)
    ax.set_xlabel("耗时 (ms)", fontsize=11)
    ax.set_title("采集与编码占 73%，PL 只占 22%", fontsize=12, fontweight="bold", pad=12)
    ax.grid(axis="x", alpha=0.28, linestyle="--")
    ax.text(0.55, 0.16, " 提帧率的杠杆在采集与编码，\n不在 PL —— PL 已从 57.87 ms 降到 13.8 ms",
            transform=ax.transAxes, fontsize=9.4, color="#1B3A5C",
            bbox=dict(boxstyle="round,pad=0.45", fc="#EAF2FB", ec=BLUE, lw=1.1))

    fig.tight_layout()
    save(fig, "图14_耗时分解.png")


# ============================================================
# 图 15：候选数与帧率（证明级联必要）
# ============================================================
def fig15():
    n = np.array([5, 16, 32, 47])
    fps = np.array([40.5, 33.0, 16.0, 7.9])

    fig, axes = plt.subplots(1, 2, figsize=(13.2, 4.9))

    ax = axes[0]
    ax.plot(n, fps, "o-", color=RED, linewidth=2.4, markersize=10, markerfacecolor="white",
            markeredgewidth=2.4, label="实测（单遍检测，同一位流）")
    for xi, yi in zip(n, fps):
        ax.annotate("%.1f fps" % yi, (xi, yi), textcoords="offset points", xytext=(0, 13),
                    ha="center", fontsize=10.5, fontweight="bold", color=RED)
    ax.set_xlabel("每帧送入下游的候选数", fontsize=11)
    ax.set_ylabel("端到端帧率 (fps)", fontsize=11)
    ax.set_title("候选数 → 帧率：PS 侧处理量与候选数成正比", fontsize=12.5, fontweight="bold", pad=12)
    ax.grid(alpha=0.28, linestyle="--")
    ax.set_xlim(0, 52)
    ax.set_ylim(0, 48)
    ax.legend(fontsize=9.6, loc="upper right")

    ax = axes[1]
    ax.axis("off")
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.text(5, 9.3, "为什么级联必须有 NPU 精判", ha="center", fontsize=13.5,
            fontweight="bold", color="#1B3A5C")

    rows = [
        ("放开到 64 个候选", "实际一帧读到 47 个", GRAY),
        ("其中真实目标", "0 个", RED),
        ("全部来自", "床架 / 门框 / 墙缝 / 云层边缘", RED),
        ("若直接当检测结果", "帧率跌到 7.9 fps，且全是虚警", RED),
        ("结论", "PL 只解决「哪里可能有目标」，\n虚警剔除必须交由 NPU 精判", GREEN),
    ]
    y = 7.9
    for k, v, c in rows:
        ax.text(0.4, y, k, fontsize=10.5, color="#404040", va="center", fontweight="bold")
        ax.text(9.6, y, v, fontsize=10.5, color=c, va="center", ha="right")
        ax.plot([0.4, 9.6], [y - 0.62, y - 0.62], color="#DDDDDD", linewidth=1)
        y -= 1.55

    ax.add_patch(FancyBboxPatch((0.25, 0.55), 9.5, 1.25, boxstyle="round,pad=0.12,rounding_size=0.25",
                                facecolor="#EAF7EE", edgecolor=GREEN, linewidth=1.6))
    ax.text(5, 1.18, "这条实测从反面印证了分级架构的必要性", ha="center",
            fontsize=10.6, color=GREEN, fontweight="bold")

    fig.tight_layout()
    save(fig, "图15_候选数与帧率.png")


# ============================================================
# 图 16：尺寸覆盖矩阵（四尺度合并）
# ============================================================
def fig16():
    scales = ["全分辨率\n(1×)", "2× 降采样", "3× 降采样", "4× 降采样"]
    ranges = [(2, 20), (4, 40), (6, 60), (50, 80)]

    fig, ax = plt.subplots(figsize=(13.2, 5.0))
    # matplotlib 3.9+ 移除了 plt.cm.get_cmap，改用固定蓝色梯度
    shades = ["#BDD7EE", "#9DC3E6", "#6FA8DC", "#3D85C6"]

    for i, ((lo, hi), name) in enumerate(zip(ranges, scales)):
        ax.barh(i, hi - lo, left=lo, height=0.52, color=shades[i % len(shades)],
                edgecolor="white", linewidth=1.6)
        ax.text(lo + (hi - lo) / 2, i, "%d ~ %d px" % (lo, hi), ha="center", va="center",
                fontsize=11.5, color="white", fontweight="bold")
        ax.text(lo - 1.2, i, "经 %d× 后等效 %d~%d px" % (i + 1 if i else 1,
                max(2, lo // (i + 1 if i else 1)), hi // (i + 1 if i else 1)),
                ha="right", va="center", fontsize=8.8, color=GRAY)

    ax.barh(len(scales), 78, left=2, height=0.52, color=GREEN, alpha=0.32,
            edgecolor=GREEN, linewidth=2)
    ax.text(41, len(scales), "合并后 2 ~ 80 px，中间无空档",
            ha="center", va="center", fontsize=12.5, color="#1B5E20", fontweight="bold")

    ax.set_yticks(list(range(len(scales))) + [len(scales)])
    ax.set_yticklabels(scales + ["四路合并"], fontsize=10.5)
    ax.set_xlabel("目标边长 (px)", fontsize=11)
    ax.set_xlim(0, 86)
    ax.set_ylim(-0.7, len(scales) + 0.7)
    ax.set_title("软件多尺度：让单一份硬件在时间维度覆盖两个数量级的尺寸",
                 fontsize=13, fontweight="bold", pad=13)
    ax.grid(axis="x", alpha=0.28, linestyle="--")

    ax.text(0.5, -0.19,
            "代价：单遍 10.6 ms → 四尺合并 13.8 ms，实时链路保持 27.6 fps；"
            "相比硬件并联多套结构元（预估 +30% LUT）更划算",
            transform=ax.transAxes, ha="center", fontsize=9.6, color="#1B3A5C",
            bbox=dict(boxstyle="round,pad=0.5", fc="#EAF2FB", ec=BLUE, lw=1.1))

    fig.tight_layout()
    save(fig, "图16_尺寸覆盖矩阵.png")


# ============================================================
# 图 17：形态学方向权衡（16 组配置）
# ============================================================
def fig17():
    # 来自 S33_TABLE10（100 张真实图，640×360）
    ks = ["k=4.0\nwin=31", "k=3.0\nwin=31", "k=2.5\nwin=31", "k=2.0\nwin=51"]
    top_r = [55.0, 75.0, 86.0, 94.0]
    top_c = [34.7, 99.4, 175.5, 286.6]
    blk_r = [61.0, 86.0, 92.0, 96.0]
    blk_c = [15.9, 47.5, 118.0, 240.0]

    fig, axes = plt.subplots(1, 2, figsize=(13.2, 5.4))
    x = np.arange(len(ks))
    w = 0.36

    ax = axes[0]
    b1 = ax.bar(x - w / 2, top_r, w, label="Top-Hat（提亮斑）", color=ORANGE, edgecolor="white", linewidth=1.2)
    b2 = ax.bar(x + w / 2, blk_r, w, label="Black-Hat（提暗斑）", color=GREEN, edgecolor="white", linewidth=1.2)
    for bars in (b1, b2):
        for b in bars:
            ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 1.4, "%.0f%%" % b.get_height(),
                    ha="center", fontsize=10.5, fontweight="bold", color="#222")
    ax.set_xticks(x); ax.set_xticklabels(ks, fontsize=10)
    ax.set_ylabel("合计召回率 (%)", fontsize=11)
    ax.set_ylim(0, 112)
    ax.set_title("召回率：同 k 下 Black-Hat 普遍更高", fontsize=12.5, fontweight="bold", pad=12)
    ax.legend(fontsize=10, loc="lower right")
    ax.grid(axis="y", alpha=0.28, linestyle="--")

    ax = axes[1]
    b1 = ax.bar(x - w / 2, top_c, w, label="Top-Hat", color=ORANGE, edgecolor="white", linewidth=1.2)
    b2 = ax.bar(x + w / 2, blk_c, w, label="Black-Hat", color=GREEN, edgecolor="white", linewidth=1.2)
    for bars in (b1, b2):
        for b in bars:
            ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 6, "%.1f" % b.get_height(),
                    ha="center", fontsize=10.5, fontweight="bold", color="#222")
    ax.axhline(64, color=RED, linestyle="--", linewidth=1.8, alpha=0.8)
    ax.text(-0.42, 70, "8×8 网格容量 64", fontsize=9.4, color=RED, ha="left")
    ax.set_xticks(x); ax.set_xticklabels(ks, fontsize=10)
    ax.set_ylabel("每帧平均候选数", fontsize=11)
    ax.set_ylim(0, 400)
    ax.set_title("虚警代价：同召回下 Black-Hat 低 3.7 倍", fontsize=12.5, fontweight="bold", pad=12)
    ax.legend(fontsize=10, loc="upper right")
    ax.grid(axis="y", alpha=0.28, linestyle="--")

    # 推荐工作点标注放在左上空白区，避免遮柱
    ax.annotate("推荐工作点：Black-Hat k=3.0\n召回 86% / 候选 47.5\n（< 64，一次前向即可判完）",
                xy=(1 + w / 2, 47.5), xytext=(-0.40, 300),
                fontsize=9.4, color=RED, fontweight="bold", linespacing=1.45,
                bbox=dict(boxstyle="round,pad=0.45", fc="#FDECEA", ec=RED, lw=1.4),
                arrowprops=dict(arrowstyle="-|>", color=RED, lw=1.7,
                                connectionstyle="arc3,rad=0.18"))

    fig.text(0.5, -0.035,
             "100 张真实图（缩放至 640×360，与 PL 输入一致）；候选数作为虚警代价的代理指标",
             ha="center", fontsize=9.4, color=GRAY, style="italic")

    fig.tight_layout()
    save(fig, "图17_形态学方向权衡.png")


if __name__ == "__main__":
    print("生成报告补充图 → %s\n" % OUT)
    fig1()
    fig6()
    fig13()
    fig14()
    fig15()
    fig16()
    fig17()
    print("\n完成。")
