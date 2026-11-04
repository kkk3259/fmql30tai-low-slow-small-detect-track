# 悟净 Lite 板上 4 颗 PL LED 的丝印 ↔ FPGA 引脚对照（实测）

> 数据来源：2026-10-23 用 `led_map_top.bit`（`synth\board\led_map_top.v`）实测。
> 该位流把 4 个引脚驱动成 4 种完全不同的行为，人眼一一对上号。

## 硬件事实（来自官方资料）

| 信号 | FPGA 引脚 | IOSTANDARD | 出处 |
|---|---|---|---|
| `PL_LED1` | `J1` | LVCMOS15（BANK13，1.5 V） | 官方 `fpai_demo` 工程 `constrs_1/impl_constraints.xdc` |
| `PL_LED2` | `M6` | LVCMOS15（BANK13） | 同上 |
| `PL_LED3` | `H7` | LVCMOS15 | 悟净 Lite 硬件手册 4.11 节 |
| `PL_LED4` | `J8` | LVCMOS15 | 同上 |
| （PS 侧） | `PS_MIO7` | — | 硬件手册 4.11 节，由 Linux 心跳驱动 |

## 实测对照表（2026-10-23 现场确认）

| FPGA 引脚 | 测试现象（`led_map_top.bit`） | 板上丝印 |
|---|---|---|
| `J1`（`led[0]`） | 慢闪，约 1.34 秒翻转一次 | **D18** |
| `M6`（`led[1]`） | **常亮**（驱动 `1'b1`） | **D20** |
| `H7`（`led[2]`） | 快闪，约 6 Hz | **D19** |
| `J8`（`led[3]`） | **常灭**（驱动 `1'b0`） | **D21** |

> 另有 `D7`、`D8` 两颗**始终常亮**，是电源指示灯，与位流无关（`blink_top` 那轮它们也亮）。

## 点亮极性（重要）

- `M6` 驱动 `1'b1` → 对应 LED **常亮**
- `J8` 驱动 `1'b0` → 对应 LED **常灭**

⇒ 高电平点亮（active-high）：`led[n] = 1` 灯亮，`= 0` 灯灭。

这一点很关键：此前 `blink_top`（只约束了 `J1`，其余三脚悬空）时看到"别的灯也亮"，
是因为悬空引脚在弱上拉下的漏电流，**不能**据此推断极性。

## `ip2_board_top` 位流里 LED 的含义

```verilog
assign led[0] = fcnt[7]; // 心跳：每 128 帧翻转 ≈ 0.63 s
assign led[3:1] = (ncand > 8'd7) ? 3'd7 : ncand[2:0]; // 本帧检出候选数（饱和到 7）
```

| 位 | 引脚 | 丝印 | 含义 |
|---|---|---|---|
| `led[0]` | J1 | **D18** | 心跳（说明帧循环在跑），0.63 s 翻转 |
| `led[1]` | M6 | **D20** | `ncand` 的 **bit0**（权值 1） |
| `led[2]` | H7 | **D19** | `ncand` 的 **bit1**（权值 2） |
| `led[3]` | J8 | **D21** | `ncand` 的 **bit2**（权值 4） |

> 注意 `assign led[3:1] = ncand[2:0]` 是**位对位**映射：
> `led[1]←ncand[0]`、`led[2]←ncand[1]`、`led[3]←ncand[2]`。
> 所以权值是 D20=1、D19=2、D21=4，不是 2/4/8。

读法：`ncand = D21×4 + D19×2 + D20×1`（只看亮/灭；D18 是心跳不算，D7/D8 是电源灯不算）。

- `ncand = 4` → `led[3:1] = 100` → **只有 D21 亮**（D19、D20 灭）
- `ncand = 3` → `011` → D19、D20 亮，D21 灭
- `ncand = 5` 或更大 → `101`/`111` → **D21 一定亮**
- `ncand = 0` → **三颗全灭**

## 复现方法

```tcl
clear_design
source synth/board_ledmap.tcl ;# → led_map_top.bit
```

```tcl
clear_design
source synth/board_ledseq.tcl ;# → led_seq_top.bit（每步只亮一颗，8 秒循环）
```

`led_seq_top.bit` 用于在丝印看不清、或换板子时重新确认映射：
0~1 s 只驱动 J1、2~3 s 只驱动 M6、4~5 s 只驱动 H7、6~7 s 只驱动 J8，奇数秒全灭。
