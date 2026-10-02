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

**数据流**：彩色大图 → IP1（洗成干净小灰度图）→ IP2（抠目标、过门限、标候选）→ 交给队友裁 ROI 给 NPU。

## 怎么跑仿真（以 Top-Hat 为例）

```powershell
cd pl/sim
D:\firstharness\venv\Scripts\python.exe ..\tools\gen_ip2_stimulus.py   # 生成激励+参考
C:\iverilog\bin\iverilog.exe -o tb_tophat.out ..\tb\tb_tophat.v ..\rtl\tophat_5x5.v   # 编译
C:\iverilog\bin\vvp.exe tb_tophat.out                                   # 仿真
D:\firstharness\venv\Scripts\python.exe ..\tools\cmp_hex.py              # 比对
```

## 已知差异 / 待优化（写进报告用）

1. **边界处理**：RTL 用 `clamp`（复制边缘），OpenCV 默认 `REFLECT_101`（镜像）。仅图片最外一圈受影响，**边界最大误差 3 LSB，内部零误差**。已按"边界允许 ≤3 LSB"口径处理（报告里如实注明）。
2. **CFAR 浮点 sqrt**：当前用 real 算术对齐 OpenCV（单元验证用）；上板前替换为定点 + MAD 近似（避开开方，是"资源-精度取舍"的加分点）。
3. **候选提取 v1**：当前是 8×8 分块简化版；精确版（连通域标记 CCL + 质心/面积/峰值）是后续加分项。
4. **架构**：当前"存全图再处理"，扩展到 640×360 前需改成"行缓存 + 流水线"。
5. **接口**：当前自定义 valid/ready 握手，集成官方通路时换 AXI4-Stream（tdata/tvalid/tready/tlast）。
6. **反压测试**：`tb/tb_tophat_bp.v` 用随机 o_ready 验证握手不丢数据。
