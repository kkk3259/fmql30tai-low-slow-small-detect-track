# -*- coding: utf-8 -*-
"""外壳切割图生成器 —— 亚克力 + M3 铜柱（3 块板）

用途：给 FMQL30TAI 悟净 Lite + USB 摄像头做一个开放式桌面支架。
输出：docs/enclosure/切割图.svg（含尺寸标注，可直接给淘宝激光切割）
       docs/enclosure/测量清单.md

⚠️ 重要：下面 PARAMS 里的尺寸**必须你自己拿卡尺量**，代码里的默认值只是
   占位示例，不是官方数据（仓库 docs/ 里没有任何一处记录板卡物理尺寸）。
   量完改数字，重跑本脚本即可。

用法：
    D:\\lowslow\\venv\\Scripts\\python.exe tools\\make_enclosure.py
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

# ============================================================
# ★★★ 全部尺寸待实测 — 按测量清单逐项填 ★★★
# ============================================================
P = {
    # ---------- 开发板（FMQL30TAI 悟净 Lite）----------
    "board_w": 100.0,        # 板宽 mm
    "board_h": 100.0,        # 板深（长）mm
    "board_hole_dx": 90.0,   # 四角安装孔的横向间距（孔心到孔心）
    "board_hole_dy": 90.0,   # 四角安装孔的纵向间距
    "board_hole_d": 3.2,     # 孔径 mm（M3 用 3.2，M2.5 用 2.7）
    "board_standoff": 25.0,  # 板子下方净高（含风扇厚度 + 走线空间）

    # ---------- 摄像头（X001，38×38）----------
    "cam_w": 38.0,           # 模组宽
    "cam_h": 38.0,           # 模组高（深）
    "cam_hole_dx": 28.0,     # 四角孔横向间距（常见 28 或 32，必须量）
    "cam_hole_dy": 28.0,
    "cam_hole_d": 2.2,       # M2 孔径
    "cam_lens_d": 14.0,      # 镜头开孔直径（M12 螺纹外径约 13.5~14.5）
    "cam_lift": 55.0,        # 镜头中心离底板的高度（决定俯角）

    # ---------- 结构 ----------
    "margin": 12.0,          # 板子边缘到亚克力边缘的留边
    "t": 3.0,                # 亚克力厚度
    "post_dx": 50.0,         # 前面板与底板之间两根立柱的横向间距
}

FILLET = 5.0                 # 圆角半径


def emit_svg(P, path):
    import math

    bw, bh = P["board_w"], P["board_h"]
    m = P["margin"]

    # 底板：板子四周各留 margin，加圆角
    plate_w = bw + 2 * m
    plate_h = bh + 2 * m
    cx0, cy0 = 60.0, 60.0                      # 底板左上角在画布中的位置

    def cx(v):                                  # 板坐标 → 画布坐标
        return cx0 + m + v - bw / 2

    def cy(v):
        return cy0 + m + v - bh / 2

    S = []                                      # SVG 片段
    A = S.append
    A('<?xml version="1.0" encoding="UTF-8"?>')
    A('<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="330mm" '
      'viewBox="0 0 420 330">')
    A('<rect width="420" height="330" fill="#ffffff"/>')
    A('<g stroke="#000000" stroke-width="0.3" fill="none" font-family="sans-serif">')

    # ---------- 标题 ----------
    A('<text x="10" y="14" font-size="5" stroke="none" fill="#000">'
      '亚克力激光切割图 · 3mm 板厚 · 单位 mm · 实线=切穿 · 虚线=折弯参考</text>')

    # ---------- ① 底板 ----------
    A(f'<text x="{cx0}" y="{cy0 - 8}" font-size="4.5" stroke="none" fill="#000">'
      f'① 底板（{plate_w:.0f} × {plate_h:.0f}）</text>')
    A(f'<rect x="{cx0}" y="{cy0}" width="{plate_w}" height="{plate_h}" rx="{FILLET}"/>')

    # 板子轮廓（虚线，仅参考）
    bx, by = cx0 + m, cy0 + m
    A(f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" stroke-dasharray="2,1.5" '
      f'stroke="#888"/>')
    A(f'<text x="{bx + bw / 2}" y="{by + bh / 2}" font-size="3.5" stroke="none" '
      f'fill="#888" text-anchor="middle">开发板轮廓 {bw:.0f}×{bh:.0f}</text>')

    # 四角安装孔
    hdx, hdy, hd = P["board_hole_dx"], P["board_hole_dy"], P["board_hole_d"]
    pcx, pcy = bx + bw / 2, by + bh / 2
    holes = [(pcx - hdx / 2, pcy - hdy / 2), (pcx + hdx / 2, pcy - hdy / 2),
             (pcx - hdx / 2, pcy + hdy / 2), (pcx + hdx / 2, pcy + hdy / 2)]
    for hx, hy in holes:
        A(f'<circle cx="{hx}" cy="{hy}" r="{hd / 2}"/>')
    # 孔距标注
    A(f'<line x1="{pcx - hdx / 2}" y1="{cy0 + plate_h + 9}" '
      f'x2="{pcx + hdx / 2}" y2="{cy0 + plate_h + 9}" stroke-width="0.2"/>')
    A(f'<text x="{pcx}" y="{cy0 + plate_h + 13}" font-size="3.2" stroke="none" '
      f'fill="#000" text-anchor="middle">{hdx:.1f}</text>')
    A(f'<line x1="{cx0 + plate_w + 9}" y1="{pcy - hdy / 2}" '
      f'x2="{cx0 + plate_w + 9}" y2="{pcy + hdy / 2}" stroke-width="0.2"/>')
    A(f'<text x="{cx0 + plate_w + 12}" y="{pcy}" font-size="3.2" stroke="none" '
      f'fill="#000">{hdy:.1f}</text>')

    # 走线缺口（右边缘切 U 型槽：三条边，靠边那条不画 = 开口朝外）
    slot_w, slot_h = 14.0, 12.0
    edge_x = cx0 + plate_w
    for i, name in enumerate(["电源 J37", "网口", "USB"]):
        sy = by + bh * (0.22 + 0.2 * i) - slot_h / 2
        sx = edge_x - slot_w
        # U 型：上边 → 内边 → 下边
        A(f'<polyline points="{edge_x},{sy} {sx},{sy} {sx},{sy + slot_h} {edge_x},{sy + slot_h}" '
          f'fill="none"/>')
        A(f'<text x="{edge_x + 3}" y="{sy + slot_h / 2 + 1}" font-size="2.8" '
          f'stroke="none" fill="#666">{name}</text>')

    # 四个脚垫孔
    for fx, fy in [(cx0 + 8, cy0 + 8), (cx0 + plate_w - 8, cy0 + 8),
                   (cx0 + 8, cy0 + plate_h - 8), (cx0 + plate_w - 8, cy0 + plate_h - 8)]:
        A(f'<circle cx="{fx}" cy="{fy}" r="1.5"/>')

    # ---------- ② 前面板（摄像头）----------
    px2, py2 = cx0 + plate_w + 60.0, cy0
    fw = P["cam_w"] + 2 * 14.0
    fh = P["cam_lift"] + 20.0
    A(f'<text x="{px2}" y="{py2 - 8}" font-size="4.5" stroke="none" fill="#000">'
      f'② 前面板（{fw:.0f} × {fh:.0f}）· 摄像头安装</text>')
    A(f'<rect x="{px2}" y="{py2}" width="{fw}" height="{fh}" rx="{FILLET}"/>')

    # 摄像头模组轮廓 + 四角孔
    ccx, ccy = px2 + fw / 2, py2 + P["cam_lift"]
    cdx, cdy, cdh = P["cam_hole_dx"], P["cam_hole_dy"], P["cam_hole_d"]
    A(f'<rect x="{ccx - P["cam_w"] / 2}" y="{ccy - P["cam_h"] / 2}" '
      f'width="{P["cam_w"]}" height="{P["cam_h"]}" stroke-dasharray="2,1.5" stroke="#888"/>')
    for hx, hy in [(ccx - cdx / 2, ccy - cdy / 2), (ccx + cdx / 2, ccy - cdy / 2),
                   (ccx - cdx / 2, ccy + cdy / 2), (ccx + cdx / 2, ccy + cdy / 2)]:
        A(f'<circle cx="{hx}" cy="{hy}" r="{cdh / 2}"/>')
    # 镜头孔
    A(f'<circle cx="{ccx}" cy="{ccy}" r="{P["cam_lens_d"] / 2}"/>')
    A(f'<text x="{ccx}" y="{ccy + P["cam_lens_d"] / 2 + 4}" font-size="2.8" '
      f'stroke="none" fill="#666" text-anchor="middle">镜头孔 Ø{P["cam_lens_d"]:.0f}</text>')

    # 底部两根立柱孔
    post_y = py2 + fh - 9.0
    for sx in (ccx - P["post_dx"] / 2, ccx + P["post_dx"] / 2):
        A(f'<circle cx="{sx}" cy="{post_y}" r="{hd / 2}"/>')

    # 高度标注
    A(f'<line x1="{px2 - 9}" y1="{py2}" x2="{px2 - 9}" y2="{py2 + fh}" stroke-width="0.2"/>')
    A(f'<text x="{px2 - 12}" y="{py2 + fh / 2}" font-size="3.2" stroke="none" '
      f'fill="#000" text-anchor="end">{fh:.1f}</text>')

    # ---------- ③ 立柱：改用现成 M3 铜柱，不再切 ----------
    px3, py3 = cx0, cy0 + plate_h + 40.0
    A(f'<text x="{px3}" y="{py3 - 8}" font-size="4.5" stroke="none" fill="#000">'
      f'③ 立柱不用切 —— 用现成 M3 铜柱</text>')
    A(f'<text x="{px3}" y="{py3 + 6}" font-size="3.6" stroke="none" fill="#333">'
      f'底板侧：M3×{P["board_standoff"]:.0f} 单通铜柱 × 4（支撑开发板）</text>')
    A(f'<text x="{px3}" y="{py3 + 15}" font-size="3.6" stroke="none" fill="#333">'
      f'前面板侧：M3×20 铜柱 × 2 + M3×8 螺丝 × 4（把摄像头前面板支起来）</text>')
    A(f'<text x="{px3}" y="{py3 + 24}" font-size="3.6" stroke="none" fill="#333">'
      f'脚垫：Ø12 橡胶自粘脚垫 × 4（贴在底板四角）</text>')
    A(f'<text x="{px3}" y="{py3 + 36}" font-size="3.4" stroke="none" fill="#666">'
      f'以上五金合计约 ¥15（淘宝「亚克力铜柱套装」一次买齐）</text>')

    # ---------- 装配说明 ----------
    A(f'<text x="60" y="{py3 + 45}" font-size="3.6" stroke="none" '
      f'fill="#000">装配：底板四角拧 M3×{P["board_standoff"]:.0f} 铜柱 → 固定开发板 → '
      f'前面板底部两孔与立柱对接 → 摄像头 M2 螺丝固定 → 镜头朝向目标</text>')
    A(f'<text x="60" y="{py3 + 53}" font-size="3.4" stroke="none" fill="#666">'
      f'材料：3mm 透明亚克力（底板可加厚到 5mm 增加刚性）· 表面：激光切割，不抛光</text>')

    A("</g></svg>")

    with open(path, "wb") as f:
        f.write("\n".join(S).encode("utf-8"))
    return plate_w, plate_h, fw, fh


def emit_checklist(P, path):
    lines = [
        "# 外壳尺寸测量清单",
        "",
        "> 用**游标卡尺**量（钢尺精度不够，孔距差 1mm 就装不上）。",
        "> 量完填进 `tools/make_enclosure.py` 顶部的 `P = {...}`，重跑脚本即可出切割图。",
        "",
        "## 一、开发板（必量）",
        "",
        "| # | 量什么 | 怎么量 | 当前脚本值 |",
        "|---|---|---|---|",
        f"| 1 | **板子外形长宽** | 最长边 × 最宽边（不含凸出的接口） | {P['board_w']:.1f} × {P['board_h']:.1f} mm |",
        f"| 2 | **四角安装孔横向间距** | 左孔心 → 右孔心 | {P['board_hole_dx']:.1f} mm |",
        f"| 3 | **四角安装孔纵向间距** | 上孔心 → 下孔心 | {P['board_hole_dy']:.1f} mm |",
        f"| 4 | **安装孔径** | 卡尺量孔内径 | {P['board_hole_d']:.1f} mm |",
        f"| 5 | **板底净高** | 板面 → 桌面（含风扇、铜柱、走线） | {P['board_standoff']:.1f} mm |",
        "",
        "> ⚠️ 若板子**没有四角安装孔**（有些开发板只有两个），改成量「任意两个可用孔」的间距，",
        "> 并在脚本里把用不到的孔删掉。",
        "",
        "## 二、摄像头 X001（必量）",
        "",
        "| # | 量什么 | 怎么量 | 当前脚本值 |",
        "|---|---|---|---|",
        f"| 6 | **模组长宽** | 官方标 38×38（可转 32×32），以实物为准 | {P['cam_w']:.1f} × {P['cam_h']:.1f} mm |",
        f"| 7 | **四角孔横向间距** | 常见 28 或 32，**必须量** | {P['cam_hole_dx']:.1f} mm |",
        f"| 8 | **四角孔纵向间距** | 同上 | {P['cam_hole_dy']:.1f} mm |",
        f"| 9 | **孔径** | M2 通常 2.2mm | {P['cam_hole_d']:.1f} mm |",
        f"| 10 | **镜头筒外径** | 量 M12 螺纹外径（约 13.5~14.5） | {P['cam_lens_d']:.1f} mm |",
        f"| 11 | **镜头中心离底板高度** | 决定俯角，按你的拍摄需求定 | {P['cam_lift']:.1f} mm |",
        "",
        "## 三、接口位置（决定底板开槽）",
        "",
        "| # | 量什么 | 备注 |",
        "|---|---|---|",
        "| 12 | **J37 电源座** 距板边的距离 + 座宽 | 决定电源槽位置 |",
        "| 13 | **网口** 距板边的距离 + 口宽 | 决定网线槽位置 |",
        "| 14 | **USB 口**（接摄像头）距板边的距离 + 口宽 | 决定 USB 槽位置 |",
        "| 15 | **Mini-USB（USB UART 调试口）** 位置 | 若常插可再开一个槽 |",
        "",
        "> 这些量出来后，在脚本里改 `slot_w` / 槽的 y 坐标即可；不想量就把开槽整段删掉，",
        "> 底板不开槽也完全能用（线从边缘绕出去）。",
        "",
        "## 四、下单话术（直接复制给淘宝）",
        "",
        "```",
        "材料：3mm 透明亚克力",
        "数量：底板 1 块、前面板 1 块（共 2 件，立柱用 M3 铜柱代替不用切）",
        "工艺：激光切割，按图切穿，不做抛光、不做倒角",
        "精度：孔位 ±0.1mm",
        "文件：切割图.svg（已按 1:1 毫米绘制）",
        "```",
        "",
        "**价格参考**：这类小件通常 ¥50~100（含运费），1~2 天出货。",
        "",
    ]
    with open(path, "wb") as f:
        f.write("\n".join(lines).encode("utf-8"))


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "docs", "enclosure")
os.makedirs(OUT, exist_ok=True)

svg = os.path.join(OUT, "切割图.svg")
pw, ph, fw, fh = emit_svg(P, svg)
print("  ✓ 切割图: %s" % svg)
print("      底板 %.1f × %.1f mm ｜ 前面板 %.1f × %.1f mm" % (pw, ph, fw, fh))

ck = os.path.join(OUT, "测量清单.md")
emit_checklist(P, ck)
print("  ✓ 测量清单: %s" % ck)
print()
print("  ⚠️ 当前所有尺寸都是**占位示例**，必须实测后改 tools/make_enclosure.py 顶部的 P 字典。")
