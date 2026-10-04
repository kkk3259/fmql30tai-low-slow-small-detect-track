# PL 模块（成员 P / FPGA 负责人）

FPGA 可编程逻辑部分的 Verilog 源码、仿真与工具脚本。

> 报告素材见 [`docs/11-FPGA实现与验证.md`](../docs/11-FPGA实现与验证.md)

## 已完成模块（全部逐字段/逐像素验证）

| 模块 | 文件 | 功能 | 验证结果 |
|---|---|---|---|
| IP1 预处理 | `rtl/preproc_axis.v` | BGR→灰度(14位精确系数) + 2×降采样，**无高斯** | ✅ 灰度 0 误差 |
| IP2-① Top-Hat | `rtl/tophat_5x5.v` | 5×5 形态学 | ✅ 零误差 |
| IP2-② CFAR | `rtl/cfar_threshold.v` | 31×31 自适应阈值（**定点 MAD + 积分图 O(1)**） | ✅ 0 误差 |
| IP2-③ 候选提取 | `rtl/candidate_extract.v` | **CCL 8连通 BFS** → 质心/面积/峰值 top8 | ✅ 零误差 |
| IP2 整合 | `rtl/ip2_top.v` | Top-Hat → CFAR → CCL | ✅ 128×72 / 320×180 逐字段一致 |
| IP3 后处理 | `rtl/postproc_axis.v` | NMS 合并过近候选（16 位降采样坐标，**不 ×2**） | ✅ 逐字段一致 |
| 流水线样板 | `rtl/gauss3_stream.v` | 3×3 高斯（行缓存+流水线+AXI4-Stream） | ✅ 深内部零误差 |

**数据流**：彩色大图 → IP1（灰度+降采样）→ IP2（增强+CFAR+候选）→ IP3（NMS）→ 候选列表(57字节,16位降采样坐标) → NPU/PS。

## 怎么跑仿真（统一 4 步）

> ⚠️ 所有 testbench 已加**文件检查**：激励文件缺失会立刻打印
> `ERROR: 缺 xxx.hex` 并停止，**不会静默跑出全 0 假结果**。

| 步骤 | 做什么 |
|---|---|
| ① 生成激励+参考 | `python ..\tools\gen_xxx.py`（产出 `input_*.hex` + `ref_*.hex`） |
| ② 编译 | `iverilog -o tb_xxx.out ..\tb\tb_xxx.v ..\rtl\xxx.v` |
| ③ 仿真 | `vvp tb_xxx.out`（产出 `output_*.hex`） |
| ④ 比对 | 逐像素/字段比 output 和 ref |

> 命令在 `pl/sim` 目录下执行；`D:\firstharness\venv\Scripts\python.exe` 带 numpy/OpenCV。

**各模块对应关系**：

| 模块 | 生成脚本 | 激励文件 | tb + rtl |
|---|---|---|---|
| IP1 | gen_stimulus.py | input.hex | tb_preproc + preproc_axis |
| Top-Hat | gen_ip2_stimulus.py | input_gray.hex | tb_tophat + tophat_5x5 |
| CFAR | gen_cfar_stimulus.py | input_cfar.hex | tb_cfar + cfar_threshold |
| 候选提取 | gen_cand_stimulus.py | input_cand.hex | tb_cand + candidate_extract |
| IP2 整合(128×72) | gen_integration.py | input_integration.hex | tb_ip2_top + ip2_top |
| IP2 整合(320×180) | gen_integration_320.py | input_integration_320.hex | tb_ip2_top_320 + ip2_top |
| IP3 | gen_postproc_stimulus.py | input_postproc.hex | tb_postproc + postproc_axis |
| 流式高斯 | gen_gauss_stimulus.py | input_gauss.hex | tb_gauss3_stream + gauss3_stream |
| 视频逐帧 | run_video_frames.py | 直接读视频 | （复用 tb_ip2_top） |

> `*.hex` 已被 `.gitignore` 忽略，新 clone 后必须先跑 ①。

## 已知差异 / 待优化

1. **边界处理**：积分图 CFAR 用"裁剪窗口"（边缘窗口变小），与 OpenCV `REFLECT_101` 仅最外一圈不同；目标置于内部，不影响检测。
2. **MAD 近似 std**：CFAR 用整数 MAD 替代 std（资源-精度取舍，k 4.0→5），避开开方、可综合。
3. **并列排序**：peak 相同时候选顺序未定义（不影响正确性；比对时按"峰值→x→y"规范排序）。
4. **架构（上板前必做）**：IP1/IP2 当前仍"存全图再处理"，640×360 会占较大 BRAM；需流水线化（行缓存 + AXI4-Stream），样板见 `gauss3_stream.v`。
   - ⚠️ **流水线化 WIP**：`win5.v`（流式 5×5 窗口）+ `tophat_5x5_stream.v` 已写出但**未完成**（内部 15/16 正确，有 1 像素对齐偏差 + 边界回绕），调试笔记已写在两文件头部，暂不用于正式验证。
5. **接口**：当前自定义 valid/ready，集成官方通路时换 AXI4-Stream。
