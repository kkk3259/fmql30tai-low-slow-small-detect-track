# pl/constr —— 引脚与时序约束（**已可用**，2026-10-23）

> ✅ 本目录现在有可直接使用的 Procise 约束文件：`board_lite.fdc`。
> 之前"缺 PL 系统时钟引脚 / 不知道 Procise 用什么格式"的问题**已全部解决**（来源见下）。

## 目录内容

| 文件 | 说明 |
|---|---|
| `board_lite.fdc` | **Procise 约束文件（可用）**：时钟 + 复位 + 4 个 LED |
| `jtag_wiring.md` | **U19（PL_JTAG）20 针针序 + DLC10 接线表**（下载位流用） |
| `pin_map.md` | 引脚映射表（格式无关的"事实来源"，含待补项） |

## 已确证的引脚（全部来自官方资料，非猜测）

| 信号 | 球号 | 电平 | 依据 |
|---|---|---|---|
| **PL 系统时钟 200 MHz** | **`C8`（P）/ `C7`（N）** | `DIFF_SSTL15` | 官方示例工程 `fpai_demo_fpga/constrs_1/impl_constraints.xdc`：`create_clock -period 5.000 [get_ports sys_clk_p]` + `PACKAGE_PIN C8/C7` |
| 复位/按键 `sys_rst` | `F8` | `LVCMOS15` | 同上（`PACKAGE_PIN F8 [get_ports sys_rst]`）；手册 `PL_KEY1 = IO_L11P_T1_SRCC_34 = F8` |
| LED1~4 | `J1` / `M6` / `H7` / `J8` | `LVCMOS15`（J1、M6 已由官方约束确认；H7/J8 按同 BANK 推定） | 官方约束 + 手册 `PL_LED1~4` |
| HDMI（本项目未用） | `AC17` / `AA15` / `Y16` / `W16` | `TMDS_33` | 官方约束 |

> 板上另有一颗 100 MHz 单端晶振（`SIT8008BI-21-Y1E-100.000000` → 网络名 `PL_100MHz`），但官方 demo 用的是 200 MHz 差分时钟，其球号在我们的资料里没有出现；因此本项目统一用 C8/C7 200 MHz + RTL 内 ÷2 得 100 MHz（`ip2_board_top.v` 里就是 `IBUFDS → BUFG → ÷2 → BUFG`）。

## Procise 约束格式（已确认）

Procise 用 **`.fdc`**，语法与 Xilinx XDC 基本一致：

```tcl
create_clock -name sys_clk -period 5.000 -waveform {0.0 2.50000} [get_ports {clk_p}]
set_property PACKAGE_PIN C8 [get_ports {clk_p}]
set_property IOSTANDARD DIFF_SSTL15 [get_ports {clk_p}]
set_property PACKAGE_PIN J1 [get_ports {led[0]}]
set_property IOSTANDARD LVCMOS15 [get_ports {led[0]}]
set_property PULLTYPE PULLUP [get_ports {rst_n}]
```

关键：`.fdc` 必须和 `.v` 一起用 `add_design_file` 加进工程（官方手册示例：`add_design_file -file led_flow/led_flow.v led_flow/led_flow.fdc`）。

> 注：Procise 手册的 IOSTANDARD 列表里只列了 `DIFF_SSTL15_DCI/_R/_T_DCI`，但裸 `DIFF_SSTL15` 实测可用（`blink_top` 已跑通全流程并 bitgen 出位流）。

## 用法

```tcl
add_design_file -file { .../pl/rtl/*.v  D:/firstharness/repo/pl/constr/board_lite.fdc }
set_top -top ip2_board_top
load_design -stage_elaborate -no_hier
rtl_analyze
synthesize
place
route
bitgen ip2_board_top.bit
```

完整脚本见 `synth/board_ip2.tcl`（会同时出 `.bit` 和 `.bin`）。

## 历史

- `board_lite.xdc`（XDC 语法骨架、全部语句注释）已于 2026-10-23 删除：它的作用是在拿不到时钟引脚时占位，现已被 `board_lite.fdc` 取代；留着会被人照着改而掉坑。需要看历史请用 `git log -- pl/constr/board_lite.xdc`。
