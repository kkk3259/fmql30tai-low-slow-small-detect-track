# 28 · 双工具链策略与 Procise 三域验证

> 记录时间：2026-10-30 晚
> 结论一句话：Vivado 是干活的手，Procise 是认识芯片的钥匙。手不换，钥匙只用它开门。

## 1. 为什么要写这一页

项目里同时存在两条工具链，团队里也有人问"到底该用 Vivado 还是 Procise"。这几天（10-29 ~ 10-30）两条路都真跑过、都有实测数据，结论已经清楚，写下来避免反复试错。

## 2. 两条路的实测战绩

| 维度 | Vivado 2018.3 | Procise 2025.1.1 |
|---|---|---|
| 我们的 IP2 + PS 出位流 | **已出，板上跑了一周**；LUT 54,345 / 78,600（69.14%），FF 17,703（11.26%），BRAM 64/265，DSP 4/400，**WNS +1.744 ns**，实测 29 fps | 只验到 elaborate |
| NPU（AI_Mate）支持 | 缺 `5.3.2.1_100AI_LV`，本机没有；替用方案是删 3907 个 AI 引脚 → NPU 通道断 | 装官方 `ip_patch` 后，带 AI 引脚的 PS7 **ELAB_OK** |
| 迭代一轮耗时 | 10~15 分钟 | 35~75 分钟（历史实测），且只能手点 GUI |
| 报错可读性 | 好，`[Synth 8-448]` 精确到文件行号 | 差，多次出现"空错误"，`procise.log` 只有 4 行空壳 |
| 源码兼容 | `.sv`、二维数组、for/generate、Xilinx IP 全吃 | `.sv` 不收（`IO-0121`）；SystemVerilog `interface` 静默失败；MIG/SDI 原语大概率不吃 |
| 位流上板 | `.bin` 32 位字节交换 + `fpga_manager` 已验证 | 同走 `bitgen`，未验 |
| 官方支持度 | 官方三域 demo 就是 Vivado 工程 | 芯片原厂工具 |

## 3. 分工

```
主线（必须保住）：Vivado + 现有 ip2_ps4 位流
 检测算法、候选表、网页、跟踪、演示，全部在这条线上迭代
 产物：synth\vivado\ip2_ps4\...\ip2_bd_wrapper.bit

支线（限时突破）：Procise 三域
 只回答一个问题：PS + NPU + IP2 能否同板综合出位流
 止损：2026-10-31 24:00 前出不了位流 → 冻结支线，按"IP2 单域交付"写报告
```

## 4. 代码约束（这是双工具链能成立的前提）

IP2 全部 RTL 限定在 Verilog-2001 可综合子集：

- 不用 `logic` / `always_ff` / `always_comb` / `interface` / `modport`
- 不用二维数组作端口、不用结构体
- 存储器推断写在独立 `always @(posedge clk)` 块里，读写不同块（Verific 与 Procise 都要求）
- 复位统一同步复位（`always @(posedge clk)` 内 `if (!rst_n)`），避免 RAM 被拆成触发器

这条约束不是事后追认的，是 10-26 流式重构时就定下的（当时是为了让 Procise 推断 BRAM），现在成了双工具链兼容的基础。

## 5. Procise 装补丁的操作（每工程、每会话都要做）

补丁**不写安装目录**，而是拷进工程目录并在当前会话 `source` 一次：

```tcl
set ::env(JFM_PATH) "D:/firstharness/JFM_Kits"
create_project -name myproj -device JFMQL30TAI676H
save_project ;# 必须先存，run.tcl 要读工程目录
source D:/firstharness/JFM_Kits/ip_patch/run.tcl
```

`run.tcl` 干两件事（已读全文确认）：

1. `copy_patch`：把 `edif/`、`edif_transform/`、`process_control/`、`paspd/`、`tools/*.tcl`、`all_src_files.tcl`、`xadc_filter/` 拷到 `<工程目录>/ip_patch/`；
2. `jfm_run`：备份 `all_src_files.tcl` → `.bak`，再 `source` 加密脚本，在**当前会话**注册 100AI 器件数据与流程钩子。

补丁来源：官方 `JFM_Kits.zip`（1.18 GB 包），解压后 `JFM_Kits\ip_patch` 为完整版，含 `edif` / `edif_transform` / `tools` / `xadc_filter`；另一份 40 MB 的包是缺这些内容的子集。

## 6. 已验证到哪一步（截至 2026-10-30 19:21）

| 步骤 | 结果 |
|---|---|
| 只 `ps_ai_wrapper.v`（含 3900 AI 引脚 PS7）+ 补丁 | **ELAB_OK**（装补丁前同文件 ELAB_FAIL） |
| + `ps_ai_peripheral.v` | **ELAB_OK** |
| + `AI_Mate_stub.v` | **ELAB_OK** ⇒ **PS + NPU 结构在 Procise 里立起来了** |
| + `mna_itf.v` | **ELAB_FAIL**（静默）→ 该文件是 SystemVerilog `interface`（11 个 `interface` 块、118 处 `logic`），改名 `.v` 无效，且 `ps_ai_wrapper` 并不需要它 |
| + 我们的 IP2 8 个文件 | 待跑 `procise_scan2.tcl` |

## 7. Procise 已知的坑（都是实测踩出来的）

| 症状 | 原因 | 对策 |
|---|---|---|
| `ELAB_FAIL:` 后面什么都没有，GUI 也没红字，`procise.log` 只有几行 | Procise elaborate 内部吞掉了异常 | 只能**二分扫描**（`procise_scan.tcl` / `procise_scan2.tcl`），靠 OK/FAIL 序列定位文件 |
| `ERROR: IO-0121: Unknown file "xxx.sv"` | `add_design_file` 只收 v/vh/edf/edif/fdc/ucf | 用 `work/p3d_rtl/sv2v/` 里的 `.v` 副本 |
| 静默失败在某文件上，该文件含 `interface` / `logic` | SystemVerilog 语法 | 该文件若可省则省；不可省则改写成 Verilog-2001 |
| `add_design_file` 加 68 MB `AI_Mate.edif` 卡死 | 网表过大 | 先 `AI_Mate_stub.v`（端口一致）过结构闸门，再换真 edif |
| `SETTOP_OK` 但模块根本不存在 | `set_top` 不校验模块是否存在 | 光看 `SETTOP_OK` 不能判断成功，必须看 `ELAB_OK` |
| `close_project` 不存在 | Procise 2025.1.1 没有该命令 | 不调用 |
| 脚本里写中文注释会把换行吞掉 | PowerShell/编码问题 | 脚本一律纯 ASCII |

## 8. 双工具链策略小结

> 本设计采用双工具链策略：以 Vivado 作为日常研发与验证环境（迭代快、可脚本化），以复旦微官方 Procise 完成含 AI 硬核的三域集成验证（唯一支持 100AI 器件的工具链）。经实测，Procise 对 SystemVerilog 与 Xilinx IP 原语支持有限，故 PL 自定义逻辑严格采用 Verilog-2001 可综合子集编写，保证双工具链兼容。

## 9. 相关脚本

| 脚本 | 用途 |
|---|---|
| `synth/procise_patch_test.tcl` | 最小验证：装补丁 + 只有 `ps_ai_wrapper.v` → 证明补丁有效 |
| `synth/procise_scan.tcl` | 从 wrapper 起逐个加文件，定位第一个导致 ELAB_FAIL 的文件 |
| `synth/procise_scan2.tcl` | 在"PS+NPU 已知 OK"地基上扫我们的 IP2 文件 |
| `synth/procise_min_3domain.tcl` | 最小三域全量（18 文件）→ elaborate + rtl_analyze + synthesize |
| `synth/procise_patch_full.tcl` | 官方 demo 全量 96 文件（含 MIG/SDI/GTX，已知不可行，仅留档） |
