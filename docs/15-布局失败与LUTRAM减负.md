# 15 · 640×360 布局失败（PLACE-0021）与 LUTRAM 减负记录

> 日期：2026-10-23 ｜ 器件：JFMQL30TAI676H（对标 xc7z030ffg676-2）｜ 工具：Procise 2025.1.1
> 结论一句话：**综合能过、资源也装得下（71%），但 Place 的 legalize 阶段失败——根因是 LUTRAM 太集中压满 SLICEM 列；已删掉一条冗余的 16 bit 平方流延迟线（LUTRAM −41%），需要重跑一次综合+布局确认。**

---

## 1. 现象

`synth/board_ip2.tcl`（ip2_board_top，640×360 全链 + 图案发生器 + 帧循环）跑到 Place 阶段失败：

```
Phase 2.1 Distribute Placement | Time: 1080.7s
hpwl = 267660.4
Phase 2.2 Legalize Placement
solver infeasible by network simplex
 ERROR: PLACE-0021: place error: Global Placement failed.
source D:/firstharness/synth/board_ip2.tcl elapsed_time 2219.10 seconds
```

各阶段耗时：

| 阶段 | 耗时 | 结果 |
|---|---|---|
| `rtl_analyze`（Elaborate） | 16.5 s | |
| `synthesize` | **1109.5 s（18.5 min）** | 产出 `ip2_board_top.edif`（77.9 MB） |
| `opt_design` | 4.4 s | |
| Place Phase 1（初始化） | 93 s | |
| Place Phase 2.1（global） | 1080.7 s | 完成（hpwl=267,660） |
| **Place Phase 2.2（legalize）** | — | **network simplex infeasible** |
| Route / Bitgen | — | 未执行 |

---

## 2. 综合资源（这一步是成功的，数字可直接引用）

从 `ip2_board_top.edif` 统计（`synth/area_hier.py`）：

| 项 | 数值 | 占 78,600 LUT |
|---|---|---|
| LUT 站点（LUT6 39,129 + LUT2 1,957 + LUT5 787 + LUT3 722 + LUT4 606 + LUT1 91） | 43,292 | — |
| LUTRAM（798,720 bit ÷ 64） | 12,480 | — |
| **LUT 当量合计** | **55,772** | **71.0 %** |
| FF | 19,453 | 12.4 %（157,200） |
| **CU48E1（DSP，即乘法器）** | **5 / 400** | 1 % |
| 块 RAM（RAMH18/36） | 0 / 530+265 | 0 % |

值得单独说明的一点：CFAR 改成"真实标准差 + 不开方"之后用了 5 个乘法器（8×8 两处平方、8×11、11×26、18×18），Procise 把它们全部推断进 CU48E1（DSP），LUT 几乎没涨。所以改 std 之前 74.0% → 改之后 **71.0%**（std 版反而更省：少一条 `mbuf` 和一套裁剪面积）。

---

## 3. 根因：不是"总面积不够"，是 LUTRAM 只能落在 SLICEM 列

- 本设计把几乎所有存储都推成了 分布式 RAM（LUTRAM：`DMEM128D1`/`DMEM256S1`），块 RAM 一个没用（历史原因：早期数组是 1 写 3 读，块 RAM 只有 2 口映射不了；后来虽改成 1 写 1 读，但没回头迁块 RAM）。
- 在 7 系列架构里，分布式 RAM 只能落在 SLICEM 片，而 SLICEM 只占全部 LUT 位点的约 **1/4**：
 - 器件 LUT 位点 78,600 → SLICEM 约 **19,650** 个
 - 本设计 LUTRAM 需要 12,480 个 LUT 当量 → 占 SLICEM 的 63.5 %
- 同时逻辑 LUT 用了 43,292 个（55 %），placer 还要把这些逻辑挤进不能放 RAM 的 3/4 位点里，global placement 之后 legalize 找不到合法位置 → `network simplex infeasible`。
- 一句话：总资源 71% 看着宽松，但"能放 RAM 的 25% 位点"用掉了 63.5%，局部已经爆了。

---

## 4. 已做的减负（本次提交）

删掉 `rb3`（20,306×16 的平方流延迟线）：

```verilog
// 原：盒2 的移出值单独存一条平方流延迟线
wire [15:0] d2_old = full_a ? rb3[rpa] : 16'd0;
// 现：同一像素、同一延迟，读出后再平方即可（(x(t-DLY))² ≡ x²(t-DLY)）
wire [7:0] d1_old = full_a ? rb1[rpa] : 8'd0;
wire [15:0] d2_old = d1_old * d1_old;
```

| 项 | 改前 | 改后 |
|---|---|---|
| LUTRAM | 798,720 bit（12,480 当量） | **473,824 bit（7,404 当量）** |
| LUTRAM 占 SLICEM | 63.5 % | **37.7 %** |
| LUT 当量合计 | 55,772（71.0 %） | 约 **50,700（64.6 %）** |
| 代价 | — | 多一个 8×8 乘法器（进 DSP，不占 LUT） |

仿真验证（逐位一致，未改任何计算结果）

| 用例 | 结果 |
|---|---|
| `run_sim.py cfar64` | `4096` 像素，差异 **0** |
| `run_sim.py cfar128` | `9216` 像素，差异 **0** |
| `run_sim.py chain`（128×72 全链） | 36 字节候选，差异 **0** |

---

## 5. 如果这次还不够（备选方案，按性价比排序）

1. 把两条大延迟线迁到块 RAM：`rb1`（20,306×8）+ `rb2`（9,841×8）用 `RAMH18K` 显式例化（模板：`D:\FudanMicro\Procise\language_templates\Verilog\Device Primitive Instantiation\FMA\RAM(ROM)\BlockRAM\RAMH18K.v`）。块 RAM 有 530 块全空，迁完 LUTRAM 再降 ~2,900 当量。代价：块 RAM 是**同步读**，需要重排 1 拍的流水对齐（风险中等，需重新验证逐位一致）。
2. **win5 行缓存**（4 条 ×641×8 ×2 实例 ≈ 41 Kbit）迁块 RAM 或改用更深的行缓存结构。
3. **降逻辑 LUT**：`candidate_extract_stream.v` 的 `S_SORT` 原地交换 4 个 64 项数组、`lbl_even/lbl_odd` 的 640:1 组合读 mux（约 3.2 K LUT）可以用"排除标记 + 固定 5 项输出寄存器"和"标签行改 RAM"压下去。
4. 降 `MAX_COMP`（64→32）：能省不少 mux，但连通域数 >32 时结果会变，会破坏与 Python 参考的逐位一致，非不得已不用。

---

## 6. 后续工作项

| 步骤 | 说明 |
|---|---|
| 重跑 `board_ip2.tcl`（约 40 min） | 用减负后的 RTL 重新出位流；若 Place 通过则 Route+Bitgen 一路到底 |
| 记录 Timing Summary（WNS/TNS） | 判决是单周期组合长路径（31 输入加法树 → 乘法 → 比较），这是唯一未验证的风险 |
| 出 `.bit` + `.bin`（raw，无文件头） | 用于 BOOT.bin 位流段替换（payload 恒 5,980,412 B，等长替换） |
| 若仍 PLACE-0021 | 按 §5 第 1 条迁块 RAM，预计再花 0.5~1 天 |
| PS↔PL 接口契约确认 | `docs/14-PS-PL接口约定.md` §7 的 5 个待确认点（已全部确认） |
| HDMI 探针 | `probe/hdmi_probe.v`、`probe/hdmi_probe.fdc`、`rtl/display/oserdese2_10to1.v`（仓库里还没有） |

---

## 7. 设计要点回顾

- 从 7.5 Mbit 全帧存储降到 474 Kbit 流式存储，资源从 381 % 降到 64.6 %：收益来自架构选择（流式/行缓存/单趟融合），而不是工具调参。
- 把除法器从 128 个并行降到 2 个（S_POST 逐标签流水），LUT 从 112 K 降到 44 K。
- 用平方比较代替开方：`(A·x − S1 − floor·A)² > k²·(A·S2 − S1²)`，5 个乘法器全部落进 DSP。
- 布局失败的根因是 LUTRAM 只能落 SLICEM 列，不是总面积不够。

---

## 8. 后续进展（2026-10-25 补记）

> 本节依据提交记录与仓库实际文件补记，保留上文原始分析。

### 8.1 LED 候选数饱和到 7 —— 根因已定位（两处）

P 在 `a69adc0` 中定位到 `cand_buf` 在 `F_WRITE` 状态被 `chain_rst_n` 误清零，已修复。
叠加 `docs/14` §6.1 的时序分析，LED 现象有两层原因：

| 层 | 原因 | 状态 |
|---|---|---|
| **① 功能 bug** | `cand_buf`（36 B 候选表）在 `F_WRITE` 被 `chain_rst_n` 误清零 → 候选表数据被破坏 | **已修复**（仿真 `VERDICT AXI-TOP-OK`，候选表 36 B 与 Python 参考完全一致）|
| **② 时序风险** | 100 MHz 工作域在已发布位流里**从未被约束、没被分析**；CFAR 改"真实 std"后判决路径是「31 输入加法树 → 11×26 与 18×18 乘法 → 40 bit 比较」单周期组合，很可能远超 10 ns | **未验证**（仓库内 `board_lite.fdc` 仍无 `create_generated_clock`）|

### 8.2 AXI 全链路打通（新增文件）

| 文件 | 作用 |
|---|---|
| **`pl/rtl/ip2_pix_fifo.v`**（新增，71 行）| 读主机 → IP2 链的**片内帧缓冲**，深度 `2^18 ≥ 640×360`，保证像素流连续 |
| `pl/rtl/ip2_axi_top.v`（+67 行）| 改为 `F_RST → F_FILL`（整帧搬入）`→ F_FEED`（连续喂）状态机；修复 `cand_buf` 误清零 |
| `pl/tb/tb_axi_top.v`（+52 行）| 修复 iverilog `always@(*)` 数组敏感表爆炸（改用 function）|
| **`pl/tb/tb_board_frames640.v`**（新增，89 行）| 板上整帧用例的 testbench |
| **`pl/tb/tb_board_pattern640.v`**（新增，88 行）| 板上图案用例的 testbench |
| **`pl/constr/board_leds.md`**（新增，75 行）| **LED 丝印 ↔ 引脚实测对照**（D18=J1 心跳、D20=M6 bit0、D19=H7 bit1、D21=J8 bit2；高电平点亮）|

⇒ 仿真结论：`VERDICT AXI-TOP-OK`，候选表 36 B 与 Python 参考完全一致。

### 8.3 仓库与本地不一致（需 P 确认）

`docs/14` §6.1 写"`create_generated_clock` 已写进 `pl/constr/board_lite.fdc`"，但 S 在 2026-10-25 查证：

```
pl/constr/board_lite.fdc 4364 B 2026-10-23 10:28:06
内含时序约束仅 1 条：create_clock -name sys_clk -period 5.000 ... [get_ports {clk_p}]
无 create_generated_clock / set_input_delay / set_output_delay / set_false_path
pl/synth/ 目录在仓库内不存在
```

**⇒ 带时序约束的位流工程已纳入版本库，可复现**
