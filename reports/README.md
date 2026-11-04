# reports · 综合/实现报告

本目录汇总 PL 工程的资源占用与时序数据，供评审对照代码查看。

## 一、已有数据（来自板上实测与工程记录）

### 1. 独立检测器位流（IP2 + PS，Procise）

| 项 | 值 |
|---|---|
| LUT | 54,345 / 78,600（69.14%） |
| FF | 17,703（11.26%） |
| BRAM | 64 / 265 |
| DSP | 4 / 400 |
| WNS | +1.744 ns |
| 实测帧率 | 29 fps |

### 2. 单域 Vivado 位流（ours，50 MHz）

| 项 | 值 |
|---|---|
| LUT | 61.9%（48,649 / 78,600） |
| BRAM | 0 |
| DSP | 0 |
| WNS | +0.041 ns @ 50 MHz |

### 3. 三域位流（ours3d_s5）

| 项 | 值 |
|---|---|
| LUT | 84.4% |
| BRAM | 71% |
| WNS | +0.030 ns |
| 位流大小 | 5,980,027 B |

> 数据出处：`docs/28-双工具链策略与Procise三域验证.md`、`docs/45-系统算法与流程完整说明.md`、`docs/指标台账.md`。

## 二、原始报告文件（待补）

以下 Vivado 原始报告未随仓库提交，可由任一方式取得：

1. 在装有 Vivado 2018.2/2018.3 的机器上执行 `pl/tools/build_bd.tcl`，脚本末尾会自动生成
2. 从出位流的开发机 `build/` 或工程目录复制

清单：

| 文件 | 内容 | 生成方式 |
|---|---|---|
| `utilization.rpt` | 资源占用（LUT/FF/BRAM/DSP） | `report_utilization` |
| `timing.rpt` | 时序汇总（WNS/TNS/20 条最差路径） | `report_timing_summary -max_paths 20` |
| `drc.rpt` | 设计规则检查 | `report_drc` |
| `synth_1/runme.log` | 综合日志 | 综合运行目录 |
| `impl_1/runme.log` | 实现日志（布局布线） | 实现运行目录 |

拿到后放进本目录即可，文件名保持上表写法。
