# -*- coding: utf-8 -*-
"""append22.py —— 给 docs/22 追加第 7/8 节（离线推进 + 当前阻塞）"""
import io

p = r"D:\firstharness\repo\docs\22-两小时自主验收记录.md"
s = io.open(p, encoding="utf-8").read()

add = """

## 7. 离线推进（板子卡死期间完成，2026-10-29 晚）

板子在 NPU 会话后整机冻结（链路 Up、无 IP、ARP 无 MAC），只能断电；等待期间做了三件不依赖板子的事：

### 7.1 挖出“假数据”的根因：候选表窗口地址错了
- RTL 真值（`repo/pl/rtl/ip2_axi_top.v`）：窗口在 **`0x10`**（写索引 / 同址读数据），`0x14`=VERSION，`0x18~0x38`=36 字节兼容视图，`0x3C`=状态镜像。
- 但 7 个 PS 脚本全写成 `0x40/0x44`（来自一版已回退的 8 位地址实验）。**6 位地址下 `0x40` 绕回 `0x00`，写它会误触发一帧**。
- 后果：之前“只读到 5 个候选 / 读回来是垃圾”的判断**全部无效**，需重测。
- 已用 `ps/fix_win.py` 统一 7 个脚本；`cand_read.py --view auto` 的判定改为「`rd(0x10)==rd(0x18)` → 有窗口」，且**不发任何写操作**（避免把 A 版里的 `0x10`=FRAME_ID 写坏）。
- 权威文档：`docs/23-寄存器映射与候选表窗口.md`。

### 7.2 按 S 的 Pd-Fa 表定下算法路线
S 的 `tools/bench_cfar_tradeoff.py`（report 第 16 节）结论：

| 配置 | 召回 | 候选/帧 |
|---|---|---|
| TopHat k=4 | 55% | 34.7 |
| TopHat k=3 | 75% | 99.4 |
| **BlackHat k=3** | **86%** | **47.5（推荐）** |
| BlackHat k=2, win=51 | 94% | 183 |

→ 已在 `tophat_5x5_stream.v` 增加 `parameter MODE`（0=Top-Hat 亮目标；1=Black-Hat 暗目标），并从 `ip2_top_stream.v` / `ip2_axi_top.v` 一层层传下去；`MODE=0` 的 SE=21 单元仿真回归通过（9216 点全部收齐）。

### 7.3 待板子回来的准备
- 调参位流已就绪：`D:\\firstharness\\dl\\ip2_retune_load.bin`（`md5 38b80fb1dd82f86b03c99acda0bf4a68`，5,979,916 B，前缀 `FF FF FF FF`）。
- A 的合并位流就绪：`ai7030_ip2merged_load.bin`（`md5 8a709b90183f42f300b8291d58bf3165`）。
- 自动化脚本 `D:\\firstharness\\dl\\phaseD_poll.ps1`：板子一回来自动跑「开机体检 → 语法校验 → 烧调参位流 → 尺寸矩阵 → 恢复实时链路」，结果写 `D:\\firstharness\\dl\\hour2\\phaseD.txt`。

## 8. 当前阻塞与下一步（按优先级）

| # | 事项 | 阻塞点 |
|---|---|---|
| 1 | 断电重启板子 | **需人工按电源/RST_POR** |
| 2 | 烧调参位流 → 第二张尺寸矩阵（回答“能认多大”） | 等 1 |
| 3 | 实时链路 + 真实场景候选数（含消抖放开） | 等 1 |
| 4 | NPU 复测 | 需 A 先确认：`ip_patch` 空壳范围 / level shifter 使能 / PL 中断号；**每次失败都要断电** |
| 5 | Black-Hat + K=3 变体位流 | 可离线构建，建议先用 K=1 的矩阵做基线再对比 |
"""

if "## 7. 离线推进" not in s:
    s = s.rstrip() + add
    io.open(p, "w", encoding="utf-8", newline="\n").write(s)
    print("已追加 7/8 节，当前行数:", len(s.splitlines()))
else:
    print("已存在第 7 节，跳过")
