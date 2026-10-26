#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""gen_ps7_tcl.py —— 从官方 ps7_parameters.xml 生成 Vivado 用的 PS7 配置 Tcl

用途：
    官方 30TAI 例程（悟净 Lite）的 PS 配置（DDR3 / QSPI / SD / UART / ENET / CAN /
    MIO 全表）存在 XML 里。我们在自己的 Vivado Black Design 里要复用这套出厂配置
    （否则 DDR 时序、QSPI 启动、串口都可能是错的），所以把它转成
        set ps7_cfg [list CONFIG.PCW_XXX {V} ...]
    然后用 `set_property -dict $ps7_cfg [get_bd_cells processing_system7_0]` 应用。

输出：
    D:/firstharness/synth/vivado/ps7_config.tcl

用法：
    D:/firstharness/venv/Scripts/python.exe gen_ps7_tcl.py
"""
import os
import re
import xml.etree.ElementTree as ET

SRC = r"D:/firstharness/official/fpai_demo_fpga/fpai_demo_fpga/fpai_demo_vivado.srcs/sources_1/bd/ps_ai/ip/ps_ai_processing_system7_0_0/ps7_parameters.xml"
OUT = r"D:/firstharness/synth/vivado/ps7_config.tcl"


def main():
    tree = ET.parse(SRC)
    root = tree.getroot()
    params = []
    for p in root.iter("PARAMETER"):
        name = p.get("NAME", "")
        val = p.get("VALUE", "")
        if not name.startswith("PCW_"):
            continue
        # PROTOCOL / 端口使能之类的 <BUSINTERFACE> 不在这里，PARAMETER 里都是普通配置
        params.append((name, val))

    params.sort()
    lines = []
    lines.append("# 本文件由 repo/pl/tools/gen_ps7_tcl.py 自动生成，请勿手改。")
    lines.append("# 来源：%s" % os.path.basename(SRC))
    lines.append("# 用法（Vivado Tcl）:")
    lines.append("#   create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 processing_system7_0")
    lines.append("#   source ps7_config.tcl")
    lines.append("#   set_property -dict $ps7_cfg [get_bd_cells processing_system7_0]")
    lines.append("")
    lines.append("set ps7_cfg [list \\")
    for i, (name, val) in enumerate(params):
        # 值里可能有空格/方括号，用花括号包起来最安全
        lines.append("    CONFIG.%s {%s} \\" % (name, val))
    lines.append("]")
    lines.append("")
    lines.append("# 便于核对：本配置已使能的 PS 端 AXI 端口")
    for k in ("PCW_USE_M_AXI_GP0", "PCW_USE_S_AXI_HP0", "PCW_USE_S_AXI_HP1",
              "PCW_FPGA0_PERIPHERAL_FREQMHZ", "PCW_UIPARAM_DDR_PARTNO"):
        v = dict(params).get(k, "(未配置)")
        lines.append("#   %-32s = %s" % (k, v))
    lines.append("")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))

    print("写出 %s" % OUT)
    print("参数条数 = %d" % len(params))
    d = dict(params)
    for k in ("PCW_USE_M_AXI_GP0", "PCW_USE_S_AXI_HP0", "PCW_FPGA0_PERIPHERAL_FREQMHZ",
              "PCW_UIPARAM_DDR_PARTNO", "PCW_UIPARAM_DDR_FREQ_MHZ",
              "PCW_CRYSTAL_PERIPHERAL_FREQMHZ", "PCW_UART0_UART0_IO",
              "PCW_QSPI_QSPI_IO", "PCW_SD0_PERIPHERAL_ENABLE"):
        print("  %-34s = %s" % (k, d.get(k, "(缺)")))


if __name__ == "__main__":
    main()
