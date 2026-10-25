# 18 · 把自研 IP 接入官方 Vivado 工程（上板落地步骤）

> 目标：**在官方 `fpai_demo_fpga` 工程里例化我们的 `ip2_axi_top`，综合出带 PS 的位流**，
> 让 PS（Linux）能通过 AXI 把 DDR 里的帧喂给我们的 PL 流水线，再把 36 字节候选表读回去。
> 这是"位流路径 3（重打 BOOT.bin）"的具体施工步骤。
>
> 前置结论（已核实）：
> - 官方工程 = `D:\firstharness\official\fpai_demo_fpga\fpai_demo_fpga\fpai_demo_vivado.xpr`（已从 rar 完整解压，含 `ps_ai.bd`、`rtl/`、`PS_AI IP/`）
> - 官方约束 = `constrs_1\impl_constraints.xdc`（C8/C7 200 MHz 差分、J1/M6 LED、F8 复位）
> - JFM_Kits = `D:\firstharness\JFM_Kits`（含 `ip_patch/run.tcl`、`030ai` 补丁目录）
> - **本机尚未安装 Vivado**（必须先装，官方指定 **2018.3**）

---

## 阶段 0：装 Vivado 2018.3（本机缺这一项）

| 项 | 要求 |
|---|---|
| 版本 | **Vivado 2018.3**（官方文档明确；其他版本 `ip_patch` 可能不匹配） |
| 安装选项 | 只勾 **7 Series / Zynq-7000** 器件支持 + Vivado 主程序（SDK 可选，生成 BOOT.bin 用 Procise 的 Create Image 就行） |
| 磁盘 | 约 20~30 GB |
| 来源 | Xilinx 官网（要账号）；或找 S / 学长要安装包（学校常有离线安装包） |

装完把 `vivado.bat` 加进 PATH，或者用开始菜单的 Vivado 2018.3 快捷方式。

---

## 阶段 1：环境变量 JFM_Kits

1. 确认 `D:\firstharness\JFM_Kits\ip_patch\run.tcl` 存在（已有）
2. 设用户环境变量：`JFM_PATH = D:\firstharness\JFM_Kits`
   - 图形界面：此电脑 → 属性 → 高级系统设置 → 环境变量 → 新建
   - 或 PowerShell（管理员）：`[Environment]::SetEnvironmentVariable("JFM_PATH","D:\firstharness\JFM_Kits","User")`
3. 重开 Vivado，Tcl 控制台验证：`puts $::env(JFM_PATH)` → 打印路径即成功

> ⚠️ 路径必须**纯英文、无空格**。中文路径下 Vivado 打补丁会失败（我们踩过 7z 的同类坑）。

---

## 阶段 2：先原样跑一次官方工程（拿 AI_Mate 资源数字）

**这一步不是白跑，它回答一个战略问题：NPU 占多少 PL 资源，我们的 IP 还能不能塞进去。**

1. 打开 `D:\firstharness\official\fpai_demo_fpga\fpai_demo_fpga\fpai_demo_vivado.xpr`
2. **Settings → IP → IP Cache → Cache scope = Disabled**（官方要求，否则 IP 补丁不生效）
3. 每个 IP（`clk_wiz_0`、`mig_7series_0`、各 afifo）右键 → **Generate Output Products**，选 **Out-of-context per IP**，Generate（不要 Skip）
4. Tcl 控制台依次执行：
   ```tcl
   source $::env(JFM_PATH)/ip_patch/run.tcl
   add_hook_tcl_to_prj
   replace_7z030ai_file        ;# 首次必须，加载 30TAI 的时序库
   ```
   （之后如果要换回原厂时序库：`reset_database_to_default`）
5. 器件确认是 `xc7z030ffg676-2`
6. **直接点 Generate Bitstream**（官方明确说：按顺序点 Run Synthesis → Run Implementation 反而会出问题）
7. 跑完打开 **Report Utilization**，记下：

| 资源 | 官方 demo 占用 | 器件总量 | 剩余 |
|---|---|---|---|
| LUT | ______ | 78,600 | ______ |
| FF | ______ | 157,200 | ______ |
| BRAM (36K) | ______ | 265 | ______ |
| DSP48 | ______ | 400 | ______ |

**判据**：我们要 **LUT 42,313 + LUTRAM（折 6,336 LUT）= 48,649**、FF 19,453、BRAM 0、DSP 0。
- 若 `剩余 LUT ≥ 48,649` 且 FF/BRAM 够 → **两者可以共存**
- 否则 → 必须二选一（建议保我们的检测器，NPU 作为对比实验写报告）

---

## 阶段 3：把我们的 IP 加进工程（推荐做法：RTL + Add Module）

**核心原则：用 `ip2_axi_top`（纯逻辑），不要用 `ip2_board_axi_top`。**
后者内含 `IBUFDS + BUFG + ÷2`（板载 200 MHz 晶振分频），但在 BD 里时钟由 **PS 的 `FCLK_CLK0`** 提供，重复加时钟会冲突。

1. **加设计文件**：`Add Sources → Add or create design sources`
   把 `D:\firstharness\repo\pl\rtl\` 下这 11 个文件加进去：
   ```
   ip2_axi_top.v  ip2_axi_master_rd.v  ip2_axi_master_wr.v
   ip2_top_stream.v  win5.v  tophat_5x5_stream.v
   cfar_threshold_stream.v  candidate_extract_stream.v  ip2_pix_fifo.v
   ```
   （`ip2_board_top.v` / `ip2_frame_top.v` / `ip2_pattern_gen.v` 是**自测用**，不带 AXI，不要加）

2. **在 BD 里例化**：打开 `ps_ai.bd` → 右键空白处 → **Add Module…** → 选 `ip2_axi_top`
3. **连线**：

   | 我们的端口 | 连到 |
   |---|---|
   | `clk` | PS `FCLK_CLK0`（在 PS7 配置里设成 **100 MHz**；GP/HP 口最高 100 MHz） |
   | `rst_n` | PS `FCLK_RESET0_N` |
   | `led[3:0]` | 引出到外部端口（约束里已有 J1/M6/H7/J8） |
   | `s_axi_*`（AXI4-Lite 32 bit） | PS `M_AXI_GP0`，中间经 **AXI Interconnect**（1 主 1 从） |
   | `m_axi_*` 读口（64 bit） | PS `S_AXI_HP0`（**HP 口数据宽度设 64 bit**，与我们 `m_axi_rdata[63:0]` 对齐） |
   | `m_axi_*` 写口（64 bit） | PS `S_AXI_HP1` |

4. **Address Editor**：给 `ip2_axi_top` 的 `s_axi` 分配 **4 KB** @ `0xA0000000`
   （⚠️ 不要用 `0x40000000`——S 实测那是 `AI_Mate` 的寄存器窗口；`0x80000000` 是 AI_Mate 的 DMA 区）
5. **Validate Design**（F6）→ 有错就按提示修，常见是时钟/复位没连

---

## 阶段 4：约束文件

- 在 `constrs_1/impl_constraints.xdc` 里**保留**：
  - `led[0..3]` → J1 / M6 / H7 / J8，`IOSTANDARD LVCMOS15`
- **删掉/注释**与本工程无关的端口约束（`sys_rst`、`sys_clk_p/n`、`HDMI_*`、`PJTAG_*`、`FMC_*`），否则会报 "port not found" warning
- 时钟**不用**再 `create_clock`：PS 的 `FCLK_CLK0` 由 BD 自动生成时钟约束

---

## 阶段 5：生成位流并上板

1. **Generate Bitstream** → 产出 `fpai_demo_vivado.runs/impl_1/xxx.bit`
2. 加载方式（先 JTAG，验证通过后再固化）：

   **方式 A（快，掉电丢失）**：
   `Tools → Open Hardware Manager → Open Target → Auto Connect`（这里用的是 PS 的 `PS_JTAG(U18)`，不是 PL_JTAG！因为要连 JTAG 链上的 7030）
   → 右键 `xc7z030_0` → `Program Device` → 选 `.bit`

   **方式 B（固化，掉电保留）**：
   `7030ai_psin.bif` 里把我们新位流的路径填进去 → `bootgen -image 7030ai_psin.bif -arch zynq -o BOOT.bin -w on`
   （或用 Procise 的 **Create Image** 生成 BOOT.bin）→ 覆盖 SD 卡 FAT 分区里的 `BOOT.bin` → 重启

---

## 阶段 6：联调顺序（别一上来就调全链）

| 步 | 做什么 | 期望结果 |
|---|---|---|
| 1 | PS 程序读 `0xA0000000 + 0x14`（VERSION） | 读到 `0x00010000` → 说明 AXI-Lite 通了 |
| 2 | 读 `0x0C`（STATUS） | bit0 busy=0, bit1 done=0 |
| 3 | PS 用 `udmabuf` 分配一块 ≥230,400 B 的物理连续内存，填一帧测试图 | 拿到物理地址 |
| 4 | 写 `0x04` = 帧物理地址；写 `0x10` = 帧号；写 `0x00` = 1（start） | STATUS bit0 busy=1 |
| 5 | 轮询 `0x0C` 直到 bit1 done=1 | 读 `[15:8]` = 候选数（期望 4） |
| 6 | 读结果区 `RESULT_ADDR + 0x00` 起 36 字节 | 与仿真结果逐字节比对 |
| 7 | 读 `RESULT_ADDR + 0x40` 状态字 | bit31 done / bit30 error / [15:0] frame_id |

> 第 1~2 步就能判断"PS↔PL 有没有通"，**这是最容易出问题也最容易验证的一步**，先做它。

---

## 已知坑（提前避开）

| 坑 | 说明 |
|---|---|
| HP 口不支持跨 4 KB 边界的突发 | 我们读突发是 8 拍 × 8 B = 64 B，安全；但帧起始地址要 4 KB 对齐 |
| cache 一致性 | PS 侧写完帧要 `cache flush`，PL 写完结果后 PS 读之前要 `cache invalidate`（`pl_link.py` 里已有对应调用） |
| `User Level Shifter` 默认关闭 | 级联模式下 PS 访问 PL 寄存器前必须先使能（青龙手册：写 `FPS_SLCR` 的 `0x008/0x838/0x004`），否则 PL 中断线浮空 |
| HP 口首次使能无效 | FSBL 里首次使能 HP 不生效，配完 bit 需要**再使能一次** |
| BD 里重复加时钟 | 不要用 `ip2_board_axi_top`（它已含 IBUFDS+÷2） |
| 我们的 IP 是一帧一次状态机 | 每次 start 前内部会整链复位（`F_IDLE → F_RST → F_FILL → F_FEED`），PS 侧不用管 |

---

## 分工建议

| 谁 | 干什么 |
|---|---|
| **S**（PS/Vivado 侧） | 装 Vivado、跑阶段 0~2（拿 AI_Mate 资源数字）、建 BD、连 AXI、生成位流、写 PS 测试程序 |
| **P**（PL 侧） | 提供 11 个 .v + 端口说明（本文 §阶段 3 表格）；出任何综合错误时排查 RTL；负责 RTL 侧的仿真回归 |
| 共同 | 阶段 6 逐条联调；结果写进 `docs/14-PS-PL接口约定.md`（**改动此文件必须双方签字**） |
