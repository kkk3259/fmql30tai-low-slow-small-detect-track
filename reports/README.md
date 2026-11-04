# 报告与日志（reports/）

> 本目录是板上运行位流的综合/实现产物。
> 评委可不重跑工程，直接查此处的资源、时序与日志。

---

## 一、文件清单

| 文件 | 来源命令 | 说明 |
|---|---|---|
| `utilization.rpt` | `report_utilization` | 资源占用（综合后） |
| `timing.rpt` | `report_timing_summary -max_paths 20` | 时序汇总 + 最差路径 |
| `vivado_run.log` | Vivado 完整输出 | 含综合、实现、DRC、位流生成全过程 |
| `run_steps.txt` | 脚本打印 | 各阶段完成标记 |
| `build_flow.tcl` | — | 生成该位流的完整脚本（可复现） |

---

## 二、资源占用（关键数字）

**器件**：xc7z030ffg676-2（FMQL30TAI676H 对标型号）
**顶层**：`ai7030_ours_top_se5`（三域联合版，SE=5）
**时钟**：`clk_fpga_0` = 50 MHz

| 资源 | 用量 | 总量 | 占用率 |
|---|---|---|---|
| Slice LUTs | **63,823** | 78,600 | **81.20%** |
| └ LUT as Logic | 55,821 | 78,600 | 71.02% |
| └ LUT as Memory (LUTRAM) | 8,002 | 26,600 | 30.08% |
| Slice Registers (FF) | 66,930 | 157,200 | 42.58% |
| Block RAM Tile | 200.5 | 265 | 75.66% |
| └ RAMB36 | 196 | 265 | 73.96% |
| └ RAMB18 | 9 | 530 | 1.70% |
| DSP48E1 | 2 | 400 | 0.50% |
| Bonded IOB | 132 | 250 | 52.80% |

补充：F7 Muxes 5,615（14.29%）、F8 Muxes 2,344（11.93%）。

**其中平台底座（AI_Mate + PS7 + DDR3 + HDMI）约占 33,751 LUT，自研检测器约占 30,000 LUT。**

---

## 三、时序（关键：请注意检查类型）

```
WNS(ns)   TNS(ns)  失败端点   WHS(ns)   THS(ns)  失败端点   WPWS(ns)  失败端点
 0.030     0.000        0       0.022     0.000       0      -0.409       2
```

| 检查类型 | 结果 | 判断 |
|---|---|---|
| **Setup（WNS）** | **+0.030 ns**，TNS=0，**0 个失败端点** | ✅ 满足 |
| **Hold（WHS）** | **+0.022 ns**，THS=0，**0 个失败端点** | ✅ 满足 |
| Pulse Width（WPWS） | −0.409 ns，**2 个失败端点** | ⚠️ 见下 |

### 关于 WPWS 的 2 个失败端点

报告末行的「Timing constraints are not met」来自这 2 个脉冲宽度检查，**不在自研模块上**：

```
失败时钟：clk_out1_AI_CORE_CLK_ST
来源    ：AI_Mate 平台的时钟输出（厂商网表 ps_ai_wrap_demo.edf 内部）
自研检测器时钟：clk_fpga_0 = 50 MHz —— Setup/Hold 全部通过
```

即：**自研检测器的 180,044 个时序端点全部满足；2 个脉冲宽度违规在厂商 AI_Mate 网表的时钟域内，属于既有状态，非本次设计引入。**

---

## 四、DRC 结果

```
INFO: [Vivado 12-3199] DRC finished with 0 Errors, 60 Warnings
```

**0 个 Error。** 60 个 Warning 中主要两类，均在平台网表内部：

| 类型 | 数量 | 说明 |
|---|---|---|
| `REQP-1840` RAMB18 async control | 多数 | AI_Mate 内部 FIFO 的 RAM 由异步复位寄存器驱动，属厂商网表既有 |
| `RTSTAT-10` No routable loads | 1 条（138 个网络） | 平台内部 FIFO 的 `aempty_fwft_i` 等未接负载 |

自研 RTL 无 DRC Error，无未约束端口。

---

## 五、实现流程关键日志

```
[Route 35-328] Router estimated timing not met.        ← 布线中途估计值，最终收敛
[Route 35-416] Intermediate Timing Summary | WNS=-0.031 |   ← 中间态估计
[Route 35-57]  Estimated Timing Summary | WNS=-0.031 |
```

**说明**：布线过程中间的「Estimated/Intermediate Timing Summary」显示 WNS=−0.031，那是估计值；**布线完成后 `report_timing_summary` 的最终结果是 WNS=+0.030、0 失败端点**（见 `timing.rpt` 第 129 行）。

---

## 六、与上一版的对比（优化效果）

| 指标 | 优化前（bd24） | 优化后（本报告） | 变化 |
|---|---|---|---|
| Slice LUTs | 71,347（90.77%） | **63,823（81.20%）** | **−7,524（−9.57%）** |
| LUT as Memory | 13,666 | **8,002** | **−5,664** |
| Block RAM | 189 | **200.5** | +11.5 |
| WNS | −0.031 ns | **+0.030 ns** | **由负转正** |
| 位流大小 | 5,980,031 B | 5,980,031 B | — |

**优化手段**：CFAR 的两条环形延迟线（20,306×8 与 9,841×8）原用组合读，综合成分布式 RAM 占 13,666 个 LUT；改为**同步读**（读地址提前一拍，`raddr = (wpa+2) mod DEP`）后可推断为 BRAM，代价 11.5 块 BRAM，换下 5,664 个 LUTRAM。

**这一改动经仿真逐位验证**：64×64 与 128×72 两组测试图，改动前后输出与金标**差异 0**。

---

## 七、如何自行复现

```tcl
# Vivado 2018.3，器件 xc7z030ffg676-2
# 1. 打开工程后
open_run impl_1
report_utilization        -file utilization.rpt
report_timing_summary     -file timing.rpt -max_paths 20
report_drc                -file drc.rpt

# 2. 日志位置
#    <工程>.runs/synth_1/runme.log
#    <工程>.runs/impl_1/runme.log
```

**注意**：三域联合版依赖厂商文件（`ps_ai_wrap_demo.edf` 132 MB + `JFM_Kits` 2 GB），不在提交包内；可完整重建的独立检测器版见 `1_FPGA工程/build_bd.tcl`，其资源约 55,000 LUT / 70%。
