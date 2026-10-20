# -*- coding: utf-8 -*-
"""
把参数扫描结果画成曲线图（给报告用）

读 results\\sweep_synth.csv，画两张子图：
  左：Pd ~ 目标尺寸（3 条线 = 3 个对比度）
  右：Pd ~ 目标对比度（3 条线 = 3 个尺寸）

用法：python tools\\plot_sweep.py
输出：results\\sweep_pd_curve.png
"""
import csv
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJ = os.path.dirname(_HERE)
CSV = os.path.join(_PROJ, "results", "sweep_synth.csv")
OUT = os.path.join(_PROJ, "results", "sweep_pd_curve.png")


def load(path):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            rows.append(dict(radius=float(r["target_radius_px"]),
                             amp=float(r["target_amp_gray"]),
                             pd=float(r["Pd_percent"]),
                             fp=int(r["false_alarms"]),
                             cand=float(r["avg_cand_per_frame"])))
    return rows


def main():
    if not os.path.exists(CSV):
        raise SystemExit("找不到扫描结果，请先运行: python tools\\sweep_synth.py")
    rows = load(CSV)
    radii = sorted(set(r["radius"] for r in rows))
    amps = sorted(set(r["amp"] for r in rows))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.2))

    # ---- 左图：Pd ~ 目标尺寸 ----
    marks = ["o", "s", "^"]
    for i, amp in enumerate(amps):
        ys = [next(r["pd"] for r in rows if r["radius"] == rad and r["amp"] == amp) for rad in radii]
        ax1.plot(radii, ys, marker=marks[i % 3], linewidth=2, markersize=8,
                 label="目标对比度 {} 灰阶".format(int(amp)))
    ax1.axhline(50, color="gray", linestyle="--", linewidth=1)
    ax1.text(radii[0], 52, "50% 检出率线", color="gray", fontsize=9)
    ax1.set_xlabel("目标半径（像素，原图尺度）", fontsize=11)
    ax1.set_ylabel("检出率 Pd (%)", fontsize=11)
    ax1.set_title("检出率 vs 目标尺寸", fontsize=12)
    ax1.set_ylim(-5, 105)
    ax1.set_xticks(radii)
    ax1.grid(alpha=0.3)
    ax1.legend(fontsize=9)

    # ---- 右图：Pd ~ 目标对比度 ----
    for i, rad in enumerate(radii):
        ys = [next(r["pd"] for r in rows if r["radius"] == rad and r["amp"] == amp) for amp in amps]
        ax2.plot(amps, ys, marker=marks[i % 3], linewidth=2, markersize=8,
                 label="目标半径 {} px".format(rad))
    ax2.axhline(50, color="gray", linestyle="--", linewidth=1)
    ax2.set_xlabel("目标对比度（灰阶）", fontsize=11)
    ax2.set_ylabel("检出率 Pd (%)", fontsize=11)
    ax2.set_title("检出率 vs 目标对比度", fontsize=12)
    ax2.set_ylim(-5, 105)
    ax2.set_xticks(amps)
    ax2.grid(alpha=0.3)
    ax2.legend(fontsize=9)

    fig.suptitle("软件基线 v1 检测能力边界（合成序列，120 帧/组，CFAR k=4.0 floor=3.0）",
                 fontsize=12.5)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(OUT, dpi=150)
    print("曲线图已保存: " + OUT)

    # ---- 文字结论 ----
    print("")
    print("=== 结论（可写入报告）===")
    for amp in amps:
        vals = [next(r["pd"] for r in rows if r["radius"] == rad and r["amp"] == amp) for rad in radii]
        print("  对比度 {:>2.0f} 灰阶: Pd = {}".format(amp, " / ".join("{:.0f}%".format(v) for v in vals)))
    print("  虚警（背景杂波导致）: {} 个/{}帧".format(rows[0]["fp"], int(next(r for r in rows)["cand"] * 0 + 120)))
    best = max(rows, key=lambda r: r["pd"])
    print("  最高检出: 半径 {}px / 对比度 {:.0f} 灰阶 -> Pd {:.0f}%".format(
        best["radius"], best["amp"], best["pd"]))


if __name__ == "__main__":
    main()
