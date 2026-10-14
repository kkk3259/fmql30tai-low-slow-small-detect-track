# -*- coding: utf-8 -*-
"""
tools/check_budget.py —— PL 资源预算检查（双平台纪律工具）

为什么需要它：
  现在开发用的 FMQL45T900 资源是最终平台 FMQL30TAI 的 2.8 倍
    FMQL45T900：350K LC / 218,600 LUT / 900 DSP / 19.2 Mb BRAM
    FMQL30TAI ：125K LC /  78,600 LUT / 400 DSP /  9.3 Mb BRAM
  如果不卡预算，会出现"在 45T900 上能跑、搬到 30TAI 放不下"。

本工具把你实际综合出来的资源占用换算成【占 30TAI 的百分比】，
超过 100% 直接报警 —— 这是"保证能迁移"的核心纪律。

用法：
  # ① 直接粘一行数字（最省事）
  python tools/check_budget.py --lc 45210 --lut 28100 --dsp 120 --bram 3.2

  # ② 读 Vivado 综合报告（自动解析 utilization 表）
  python tools/check_budget.py --report path/to/post_synth_util.rpt

  # ③ 读 Procise 报告（格式不同，尽量解析；不行就用 ① 手动粘）
  python tools/check_budget.py --report path/to/procise_report.rpt
"""
import argparse
import io
import os
import re
import sys

# ============================================================ 目标平台（最终参赛平台）预算
BUDGET = {
    "LC":      125000,
    "LUT":     78600,
    "DSP":     400,
    "BRAM_Mb": 9.3,
}
# 参考：现在开发用的 45T900 资源（仅用于显示余量，不作判定）
DEV_BOARD = {
    "LC":      350000,
    "LUT":     218600,
    "DSP":     900,
    "BRAM_Mb": 19.2,
}


def parse_report(path):
    """从综合报告里尽量提取资源占用（Vivado / Procise 通用启发式）"""
    if not os.path.exists(path):
        print("❌ 报告文件不存在: " + path)
        return None
    t = io.open(path, encoding="utf-8", errors="replace").read()
    out = {}

    def grab(pats, keys):
        """按顺序尝试多个正则，命中第一个就写入 out[key]"""
        key = keys[0]
        for p in pats:
            m = re.search(p, t, re.I)
            if m:
                try:
                    out[key] = float(m.group(1).replace(",", ""))
                    return True
                except (ValueError, IndexError):
                    continue
        return False

    # 形如：| Slice LUTs                 | 28100|     0 |     78600 | 35.75 |
    # LUT：多个候选写法，按优先顺序兜底（Vivado 主格式 / 其他工具）
    grab([r"Slice\s+LUTs\s*\|?\s*([\d,]+)",      # Vivado: "Slice LUTs | 28100"
          r"CLB\s+LUTs\s*\|?\s*([\d,]+)",        # 某些工具
          r"LUT\s+as\s+Logic\s*\|?\s*([\d,]+)"  # Vivado 变体
          ], ["LUT"])
    grab([r"Slice\s+Registers\s*\|?\s*([\d,]+)"], ["FF"])
    grab([r"\bDSPs?\s*\|?\s*([\d,]+)"], ["DSP"])
    # BRAM：优先直接读 Mb；否则读块数换算（Xilinx "Block RAM Tile" 1 块 = 36 Kb）
    grab([r"Block\s+RAM\s+Tile\s*\|?\s*([\d,]+)"], ["BRAM_TILE"])
    grab([r"Block\s+RAM\s+(?:Tile\s+)?[^\d]*([\d.]+)\s*Mb"], ["BRAM_Mb"])
    grab([r"Logic\s+Cells?\s*\|?\s*([\d,]+)"], ["LC"])
    if "BRAM_TILE" in out and "BRAM_Mb" not in out:
        out["BRAM_Mb"] = out.pop("BRAM_TILE") * 36.0 / 1024.0
    else:
        out.pop("BRAM_TILE", None)
    return out or None


def main():
    ap = argparse.ArgumentParser(description="PL 资源预算检查（按 FMQL30TAI 卡）")
    ap.add_argument("--report", help="综合报告文件（Vivado/Procise .rpt）")
    ap.add_argument("--lc", type=float, help="逻辑单元数")
    ap.add_argument("--lut", type=float, help="LUT 数")
    ap.add_argument("--ff", type=float, help="寄存器数")
    ap.add_argument("--dsp", type=float, help="DSP 数")
    ap.add_argument("--bram", type=float, help="BRAM 容量（Mb）")
    ap.add_argument("--bram-tile", type=float, help="BRAM 块数（36Kb 块）")
    a = ap.parse_args()

    vals = {}
    if a.report:
        r = parse_report(a.report)
        if r:
            vals.update(r)
            print("已从报告解析: " + ", ".join("{}={}".format(k, v) for k, v in r.items()))
        else:
            print("⚠️ 未能从报告自动解析，请用 --lc/--lut/--dsp/--bram 手动指定")

    for k, v in [("LC", a.lc), ("LUT", a.lut), ("FF", a.ff),
                 ("DSP", a.dsp), ("BRAM_Mb", a.bram)]:
        if v is not None:
            vals[k] = v
    if a.bram_tile is not None and "BRAM_Mb" not in vals:
        vals["BRAM_Mb"] = a.bram_tile * 36 / 1024 / 1024 * 1000  # 36Kb/块 -> Mb

    if not vals:
        ap.print_help()
        return 2

    print("")
    print("=" * 78)
    print("PL 资源预算检查（判定基准：最终参赛平台 FMQL30TAI）")
    print("=" * 78)
    print("  {:<8} {:>12} {:>12} {:>14} {:>10}".format("资源", "本次占用", "30TAI预算", "占30TAI比例", "判定"))
    print("  " + "-" * 74)

    bad = []
    for key in ("LC", "LUT", "FF", "DSP", "BRAM_Mb"):
        if key not in vals:
            continue
        used = vals[key]
        bud = BUDGET.get(key)
        if bud is None:
            print("  {:<8} {:>12.0f} {:>12} {:>14} {:>10}".format(key, used, "—", "—", "参考"))
            continue
        pct = 100.0 * used / bud
        flag = "✅ 通过"
        if pct > 100:
            flag = "❌ 超预算"
            bad.append(key)
        elif pct > 80:
            flag = "⚠️ 接近上限"
        print("  {:<8} {:>12.1f} {:>12.1f} {:>13.1f}% {:>10}".format(key, used, bud, pct, flag))

    print("")
    print("  参考：开发板 FMQL45T900 的资源 = 350K LC / 218,600 LUT / 900 DSP / 19.2 Mb BRAM")
    print("       （是 30TAI 的约 2.8 倍 —— 在它上面开发必须按 30TAI 卡预算）")
    print("")
    if bad:
        print("  ❌ 结论：{} 项超出 30TAI 预算 —— 必须优化后再迁移，否则上不了 30TAI".format(len(bad)))
        print("     超出项：" + "、".join(bad))
        return 1
    print("  ✅ 结论：所有资源均在 30TAI 预算内，可安全迁移")
    return 0


if __name__ == "__main__":
    sys.exit(main())
