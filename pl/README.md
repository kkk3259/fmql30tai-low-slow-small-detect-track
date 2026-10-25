# PL 模块（成员 P / FPGA 负责人）

FPGA 可编程逻辑部分的 Verilog 源码、约束、仿真与综合脚本。

> 更新时间：**2026-10-25**（S 依据 P 提交 `a69adc0` 补记）　｜　状态：**IP2 三级流式重构完成；综合 71.0%（LUT 55,772 / 78,600）；AXI 全链路仿真打通（`VERDICT AXI-TOP-OK`）；待时序收敛 + 上板验证**
> 报告素材见 [`docs/06-FPGA实现与验证.md`](../docs/06-FPGA实现与验证.md)；进展与卡点见 [`docs/13-PL上板进展与卡点.md`](../docs/13-PL上板进展与卡点.md)、[`docs/15-布局失败与LUTRAM减负.md`](../docs/15-布局失败与LUTRAM减负.md)

---

## 1. 一句话现状

| 项 | 状态 |
|---|---|
| IP2 三级（Top-Hat / CFAR / CCL）流式+行缓存重构 | ✅ 完成，与旧版**逐位一致**（共仿真 `VERDICT IDENTICAL`） |
| 640×360 综合（Procise，JFMQL30TAI676H） | ✅ 通过：LUT 站点 43,292 + LUTRAM 12,480 = **55,772 / 78,600 = 71.0%**；FF 19,453（12.4%）；**CU48E1（DSP）5 / 400**；块 RAM 0（数据源 `docs/15` §2） |
| 布局（Place） | 🟡 曾失败 `PLACE-0021 network simplex infeasible`（根因 LUTRAM 压满 SLICEM 列），减负 41% 后待重跑（见 `docs/15`） |
| 时序（100 MHz 工作域） | ❌ **已发布位流里从未约束、没被分析**；仓库内 `board_lite.fdc` 仍只有 1 条 `create_clock`（见 `docs/14` §5/§6.1） |
| 位流生成 | ✅ `blink_top.bit` 5.98 MB、`ip2_board_top.bit` 均可出；**板上 LED 候选数饱和到 7（仿真 4）** —— 功能层根因 `cand_buf` 被 `chain_rst_n` 误清零**已修复**，待上板复验 |
| 板级自测顶层（不接 PS，自出图案 + LED 指示） | ✅ 写好并仿真通过；LED 丝印↔引脚映射见 `constr/board_leds.md`（实测） |
| **PS↔PL 数据通路（AXI4）** | ✅ **已实现**：`ip2_axi_master_rd/wr.v` + `ip2_axi_top.v` + `ip2_pix_fifo.v`（片内帧缓冲 2^18 ≥ 640×360）；接口契约见 `docs/14` |
| AXI 全链路仿真 | ✅ **`VERDICT AXI-TOP-OK`**，候选表 36 B 与 Python 参考完全一致（`tb_axi_top.v`） |
| IP1 预处理 / IP3 NMS / IP4 ROI | ⚠️ 仍是"存全图"版本，**未参与本轮 640 综合、未流式化** |
| 摄像头接入 | ❌ 未做（本项目不由摄像头直连 PL，图像经 PS 采集后写入 udmabuf，见 `docs/16` §8） |

---

## 2. RTL 清单

### 2.1 流式版（上板用，参与 640×360 综合）

| 文件 | 功能 | 片上存储（640×360） |
|---|---|---|
| `rtl/win5.v` | 5×5 窗口行缓存（循环 RAM 延迟线 + 5 行抽头） | 2 实例 × 4×641×8 |
| `rtl/tophat_5x5_stream.v` | 开运算：erode(IS_MAX=0,PAD=255) → dilate(IS_MAX=1,PAD=0) | gd 环形线 2569×8 |
| `rtl/cfar_threshold_stream.v` | 单趟 CA-CFAR，**真实标准差**：`thr = mean + K·sd + FLOOR`（WIN=31, K=4, FLOOR=3）。判决写成 `L² > k²·(A·S2−S1²)`（L = x·A−S1−FLOOR·A），**既不开方也没有除法**；S1、S2 两个滑动盒共用同一个 31×31 窗口 | rb1 20306×8 + rb2 9841×8 + rb3 20306×16 ≈ **0.57 Mbit** |
| `rtl/candidate_extract_stream.v` | 单趟连通域：两行标签 + 并查集 + 即时累加 → 36 字节候选表 | 无（仅两行标签 640×7×2） |
| `rtl/ip2_top_stream.v` | 三级串联，`i_ready` 反压贯通到顶层 | — |
| `rtl/ip2_pattern_gen.v` | 板级自测图案发生器（渐变背景 + 4 个 3×3 亮点 + 1 个 80×80 大块） | — |
| `rtl/ip2_frame_top.v` | 帧循环（喂 → 等 36 字节 → 复位 32 拍 → 下一帧），LED 显示候选数 | — |
| `rtl/ip2_board_top.v` | 板级顶层：IBUFDS(C8/C7) → BUFG → ÷2 → 100 MHz → 帧循环 | — |

### 2.2 旧全帧版（保留作参考基线，**不要用于上板**）

| 文件 | 说明 |
|---|---|
| `rtl/tophat_5x5.v` / `rtl/cfar_threshold.v` / `rtl/candidate_extract.v` / `rtl/ip2_top.v` | 存全图 + 多趟处理，640×360 需 ~11 Mbit 存储、LUT 160%，装不下 |
| `rtl/preproc_axis.v` | IP1：BGR→灰度 + 2× 降采样（**未流式化**，仍是存全图） |
| `rtl/postproc_axis.v` / `rtl/roi_pack.v` | IP3 NMS / IP4 ROI 打包（**未流式化**） |
| `rtl/gauss3_stream.v` | 3×3 高斯流水线样板（未用于正式链路） |

### 2.3 参数（`ip2_top_stream` 例化处可覆盖）

```
W=640, H=360, MAX_CAND=5         // 640×360 @ MAX_COMP=64
CFAR: WIN=31, K=4, FLOOR=3         // 真实 std，平方比较判决（不开方）
CCL : MAX_COMP=64, MIN_AREA=2, MAX_AREA=200
```

---

## 3. 架构要点（上板前必读）

```
像素流 ─► win5(2 实例) ─► tophat(erode→dilate) ─► CFAR(双滑动盒) ─► CCL(单趟标记+并查集) ─► 36 字节候选表
```

1. **全链路只用 valid/ready 握手**（自定义接口，不是 AXI4-Stream）。输出寄存器**必须在 `o_ready` 时更新**——否则背压停顿时数据与 valid 会错位（这是踩过的坑，`win5.v:134-140`）。
2. **CFAR 内部光栅是"扩展"的**：`W30=W+30, H30=H+30`（每行左右各补 15 个虚拟 PAD 列）。所以 CFAR 在 PAD 位置**拉低 `i_ready`**，反压必须一路回到顶层，否则上游会丢像素。
3. **CFAR 的因果对齐**（最难的一段，改之前务必看代码注释）：
   - `diff(t) = |x(t−CENTER_OFF) − mean(t)|`，`CENTER_OFF = 15·W30+15`
   - 两个盒子（S1 与 S2）**共用同一个 31×31 窗口**，所以只有一套裁剪面积 `area1`（按 `row−15` 裁剪）—— 相比早期 MAD 版少了一整套除数、延迟线和第二个裁剪器
   - `x(C)` 从 dbuf1 的第三个读口取（延迟 `2·CENTER_OFF`），`mean(C)` 从 mbuf 取（延迟 `CENTER_OFF`）
4. **BRAM 用量为 0 是设计选择**：本项目存储是 1 写 3 读 / 1 写 2 读，块 RAM 最多 2 口，映射不了 → 全部推断成 **LUTRAM（DMEM128D1/DMEM256S1）**，代价 13,536 LUT 当量，好处是 9.3 Mbit 块 RAM 全空。

---

## 4. 资源（640×360，Procise 实测，非估算）

| 模块 | LUT 站点 | FF | LUTRAM 当量 |
|---|---|---|---|
| `candidate_extract_stream`（CCL） | 37,270 | 15,157 | 0 |
| `cfar_threshold_stream` | 6,506 | 1,260 | 5,016 |
| `tophat_5x5_stream`（含 2×win5） | 833 | 3,057 | 576 |
| **合计** | **44,610** | **19,474** | **13,536** |

- LUT 当量合计 = 44,610 + 13,536 = **58,146 / 78,600 = 74.0%**
- FF = 19,474 / 157,200 = 12.4%；BRAM = **0 / 253 块**；DSP = 0
- 对比重构前：LUT 112,269（160%，装不下）→ 44,610。**关键修复**：CCL 的 `S_POST` 原来在一个时钟内展开 128 个 16 位除法器，改成每拍处理 1 个标签（只剩 2 个除法器）。
- 时间：elaborate 97.5 s / synthesize 663.9 s / 峰值内存 2.6 GB

---

## 5. 怎么跑仿真（一键回归）

```powershell
cd D:\firstharness\repo\pl\tools
& "D:\firstharness\venv\Scripts\python.exe" run_sim.py           # 全部
& "D:\firstharness\venv\Scripts\python.exe" run_sim.py cfar64    # 单跑一项
```

当前回归基线（**这四个数字是"已知且可接受"的，不要拿它们当 bug**）：

| 项 | 差异 | 说明 |
|---|---|---|
| `tophat` | 186 / 1024 | 其中 **185** 是 OpenCV `MORPH_TOPHAT` 的 `BORDER_REFLECT_101` 边界语义差异（旧版同样 185），另 1 处是首像素启动 |
| `cfar64` | **0** / 4096 | 与 `gen_cfar_std_ref.py` 生成的整数 std 参考逐位一致 |
| `cfar128` | **0** / 9216 | 同上 |
| `ccl` | **0** / 36 字节 | — |
| `chain`（128×72 全链） | **0** | — |

> `.hex` 激励/参考都被 `pl/sim/.gitignore` 忽略，跑回归前先重新生成：
> `python tools/gen_cfar_stimulus.py`（写 `sim/input_cfar.hex` + `sim/ref_cfar.hex`）、`python tools/gen_ip2_stimulus.py`、`python tools/gen_ccl_stimulus.py`、`python tools/gen_integration.py`，然后 `python tools/run_sim.py`。

> 说明：`synth/equiv/tb_chain_equiv.v`（新 vs 旧 HEAD 并排共仿真）只用于证明**流式重构本身**等价（win5/tophat/CCL 与 CFAR 两趟→单趟），曾达 `VERDICT IDENTICAL`。
> CFAR 判决从「MAD 近似」改成「真实 std」之后，与旧 MAD 黄金版**不再逐位一致**（阈值常数变了），新的等价基准是 `pl/tools/gen_cfar_std_ref.py` 生成的整数 std 参考。

---

## 6. 引脚约束（官方来源，可直接用）

约束文件：[`constr/board_lite.fdc`](constr/board_lite.fdc)（Procise 用 `.fdc`，语法同 XDC）
JTAG 接线表：[`constr/jtag_wiring.md`](constr/jtag_wiring.md)

| 信号 | 引脚 | IOSTANDARD | 出处 |
|---|---|---|---|
| `clk_p` / `clk_n` | **C8** / **C7** | `DIFF_SSTL15` | 官方 demo `impl_constraints.xdc`：`create_clock -period 5.000`（**200 MHz 差分**） |
| `rst_n` | **F8** | `LVCMOS15` | 同上（官方名 `sys_rst`） |
| `led[0..3]` | **J1 / M6 / H7 / J8** | `LVCMOS15` | J1、M6 见官方 xdc；H7、J8 见《硬件使用手册》LED 表 |

- 时钟来源：板载 `SIT9121AI-2D2-XE200.000000K` → `PL_DDR_EXT_CLK_P/N`，200 MHz。板上的 100 MHz 晶振官方未在 demo 里使用，我们 **200 MHz ÷ 2 = 100 MHz** 作为主频。
- 官方约束文件原始出处：20260916 资料包 `fpai_demo_fpga.rar → constrs_1/impl_constraints.xdc`（本机解压副本 `D:\firstharness\dl\xdc\impl_constraints.xdc`），内含 HDMI(TMDS_33)/SFP/FMC/PL-JTAG 等全部引脚。

---

## 7. 怎么综合 / 出位流（Procise）

Procise 没有可用批处理入口，必须由人在 GUI Shell 里执行：

1. 开始菜单 → **Start Procise Shell** → 弹框选 `D:\FudanMicro\Procise\bin\procise.exe` → 打开
2. 在 shell 里：

```tcl
clear_design
source D:/firstharness/synth/test_ip2.tcl     ;# 只到 elaborate（资源摸底，约 1.6 分钟）
synthesize                                    ;# 约 11 分钟
```

或全流程（出位流）：

```tcl
clear_design
source D:/firstharness/synth/board_ip2.tcl    ;# rtl_analyze → synthesize → place → route → bitgen
```

- 脚本目录：`D:\firstharness\synth\`（`test_ip2.tcl` 640×360 elaborate、`board_ip2.tcl` 板级全流程、`test_ccl_only.tcl` CCL 单独探针）
- 输出：`D:\FudanMicro\Procise\ip2_board_top.bit` 等
- 本机 Procise：`2025.1.1 temp`，`SVN Version: 32494` —— 与官方位流头部 `PatchID=32494` 同一构建，**不需要额外打位流补丁、不需要 license 申请**
- 下载：GUI `Tools -> Configure Device…` → **Connect to board** → 右键 FPGA → Assign New Configuration File → Program

---

## 8. 已知差异 / 待办

1. **边界语义**：CFAR 用"裁剪窗口"（边缘窗口变小），与 OpenCV `REFLECT_101` 只有最外一圈不同；目标在内部时不影响检测。
2. **真实 std，但不开方**：判决等价于 `(x·A−S1−FLOOR·A)² > k²·(A·S2−S1²)`，与 PS 侧 `k=4.0` 严格一致；既不实例化开方器也不做除法（早期用 MAD 近似，差一个 1.4826 常数，已废弃）。
3. **并列排序**：peak 相同时候选顺序未定义（比对时按"峰值→x→y"规范排序）。
4. **无 AXI 接口**：现在是纯流式 valid/ready，接 PS 需要再包一层 AXI4-Stream（或 AXI-Lite 寄存器 + DMA）。
5. **IP1/IP3/IP4 未流式化**，上板链路打通后需要同样改造。
6. **`i_bin` 位宽警告**：`ip2_top_stream.v:35` 把 8 bit `o_data` 接到 1 bit `i_bin`，iverilog/Verific 都会报 pruning warning，功能无影响（`candidate_extract_stream` 只用 bit0 之外还看 `i_enh`）。
7. **CFAR 判决是单周期组合长路径（未做时序验证）**：31 输入加法 → 11×26 乘 → 减 → 18×18 乘 → 比较。100 MHz 下可能不收敛，若 `place/route` 的 Timing Summary 报负 slack，解法是给判决加 2 级流水（乘积与 `L²` 各打一拍，同时把 `x_out`/`out_gate` 延迟 2 拍对齐），不改变延迟线上的因果结构。
