# PL 模块（成员 P / FPGA 负责人）

FPGA 可编程逻辑部分的 Verilog 源码、仿真与工具脚本。

## 已完成模块

| 模块 | 文件 | 功能 | 验证结果 |
|---|---|---|---|
| IP1 预处理 | `rtl/preproc_axis.v` | 灰度化 + 2×降采样 + 3×3 高斯 | ✅ 内部像素 ≤1 LSB |
| IP2-① Top-Hat | `rtl/tophat_5x5.v` | 5×5 形态学（腐蚀+膨胀） | ✅ 零误差 |
| IP2-② CFAR | `rtl/cfar_threshold.v` | 31×31 自适应阈值 | ✅ 零误差 |
| IP2-③ 候选提取 | `rtl/candidate_extract.v` | 8×8 分块粗筛 v1 | ✅ 零误差 |
| IP2 整合 | `rtl/ip2_top.v` | Top-Hat → CFAR → 候选 | ✅ 内部零误差 |
| 流水线样板 | `rtl/gauss3_stream.v` | 3×3 高斯（行缓存+流水线+AXI4-Stream） | ✅ 深内部零误差 |

**数据流**：彩色大图 → IP1（洗成干净小灰度图）→ IP2（抠目标、过门限、标候选）→ 交给队友裁 ROI 给 NPU。

## 怎么跑仿真（统一 4 步，任何模块都一样）

> ⚠️ 所有 testbench 已加**文件检查**：激励文件缺失会立刻打印
> `ERROR: 缺 xxx.hex，请先运行 pl/tools/gen_xxx.py` 并停止，
> **不会静默跑出全 0 的假结果**。

| 步骤 | 做什么 | 示例（Top-Hat） |
|---|---|---|
| ① 生成激励+参考 | Python 按 OpenCV 标准答案产出 `input_*.hex` + `ref_*.hex` | `python ..\tools\gen_ip2_stimulus.py` |
| ② 编译 | Verilog 编成仿真程序 | `iverilog -o tb_tophat.out ..\tb\tb_tophat.v ..\rtl\tophat_5x5.v` |
| ③ 仿真 | 跑出 `output_*.hex` | `vvp tb_tophat.out` |
| ④ 比对 | 逐像素比 output 和 ref | `python ..\tools\cmp_hex.py` |

> 命令都在 `pl/sim` 目录下执行；`D:\firstharness\venv\Scripts\python.exe` 是带 numpy/OpenCV 的虚拟环境。

**各模块对应关系**：

| 模块 | 生成脚本（①） | 激励文件 | 编译（② 的 tb + rtl） |
|---|---|---|---|
| IP1 | gen_stimulus.py | input.hex | tb_preproc + preproc_axis |
| Top-Hat | gen_ip2_stimulus.py | input_gray.hex | tb_tophat + tophat_5x5 |
| CFAR | gen_cfar_stimulus.py | input_cfar.hex | tb_cfar + cfar_threshold |
| 候选提取 | gen_cand_stimulus.py | input_cand.hex | tb_cand + candidate_extract |
| IP2 整合 | gen_integration.py | input_integration.hex | tb_ip2_top + ip2_top(全链) |
| 流式高斯 | gen_gauss_stimulus.py | input_gauss.hex | tb_gauss3_stream + gauss3_stream |

> `*.hex` 已被 `.gitignore` 忽略（产物不入库），所以 **新 clone 后必须先跑 ①**。

## 已知差异 / 待优化（写进报告用）

1. **边界处理**：RTL 用 `clamp`（复制边缘），OpenCV 默认 `REFLECT_101`（镜像）。仅图片最外一圈受影响，**边界最大误差 3 LSB，内部零误差**。已按"边界允许 ≤3 LSB"口径处理（报告里如实注明）。
2. **CFAR 浮点 sqrt**：当前用 real 算术对齐 OpenCV（单元验证用）；上板前替换为定点 + MAD 近似（避开开方，是"资源-精度取舍"的加分点）。
3. **候选提取 v1**：当前是 8×8 分块简化版；精确版（连通域标记 CCL + 质心/面积/峰值）是后续加分项。
4. **架构**：IP1/IP2 当前仍是"存全图再处理"；已做出流式样板 `rtl/gauss3_stream.v`（行缓存+流水线+AXI4-Stream，深内部零误差），下一步把 Top-Hat/CFAR 也流水线化。
5. **接口**：当前自定义 valid/ready 握手，集成官方通路时换 AXI4-Stream（tdata/tvalid/tready/tlast）。
6. **反压测试**：`tb/tb_tophat_bp.v` 用随机 o_ready 验证握手不丢数据。
