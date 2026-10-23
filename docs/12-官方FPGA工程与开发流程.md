# 12 - 官方 FPGA 工程与开发流程（2026 嵌赛打包资料）

> **资料来源**：`D:\Downloads\2026嵌赛FPGA开发\2026嵌赛FPGA开发\20260916\`（微云分享 `share.weiyun.com/ZcPwQ9gq` 下载，2.11 GB / 9 个文件）
> **整理日期**：2026-10-23
> **重大意义**：这套资料补齐了此前"必须向企业索取"的全部材料 —— **不再有缺口（Procise 不校验 License，实测已跑通 elaborate→synthesize→place→route→bitgen 全流程）**。

---

## 一、资料清单（9 个文件 / 2.11 GB）

| 文件 | 大小 | 内容 | 状态 |
|---|---|---|---|
| **`fpai_demo_fpga.rar`** | 6.29 MB | **完整 Vivado 工程**（398 条目，解压 295 文件 / 152 MB）| ✅ 已解压到 `D:\Downloads\Wujing\FPGA_DEMO\` |
| **`BIT.rar`** | 6.18 MB | **位流**：`30tai_detpost` / `30tai_lite_detpost` 两套（.bit + BOOT.bin）| 待解压 |
| **`BOOT_Gen.rar`** | 3.71 MB | **BOOT.bin 生成工具**：`7030ai_psin.bif` + 位流 + bl31.elf + FSBL + u-boot | 待解压 |
| **`fpai_demo_app.rar`** | 193.22 MB | **PS 应用源码**（3222 条目，含 `deps/modelzoo_utils` 全套）| 待解压 |
| **`JFM_Kits.zip`** | 1182.43 MB | **Vivado IP 补丁工具包**（3830 条目，含 30TAI 时序库）| 待解压 |
| **`30TAI使用教程.pdf`** | 1.79 MB | **11 页：IP 补丁 → Vivado 工程 → BOOT 生成 → PS 程序 → 上板运行** 全流程 | ✅ 已提取文本 |
| **`FPAI_DEMO说明.pdf`** | 0.29 MB | **8 页：工程结构、约束差异、数据流、custom op 接口、C API** | ✅ 已提取文本 |
| `FMSH_Procise_2025.1.1_temp_...rar` | 769.14 MB | Procise 安装包（已有）| 已有 |
| `procise解压密码.txt` | — | 密码 `FMSH_FPGA_sw` | 已知 |

---

## 二、⭐ 官方管脚约束（`constrs_1/impl_constraints.xdc`）

### 2.1 PL 系统时钟 —— **P 之前一直找不到的**

```tcl
create_clock -period 5.000 [get_ports sys_clk_p]        # 5 ns = 200 MHz
set_property IOSTANDARD DIFF_SSTL15 [get_ports sys_clk_p]
set_property IOSTANDARD DIFF_SSTL15 [get_ports sys_clk_n]
set_property PACKAGE_PIN C8 [get_ports sys_clk_p]
set_property PACKAGE_PIN C7 [get_ports sys_clk_n]
```

| 信号 | 引脚 | IOSTANDARD | 频率 |
|---|---|---|---|
| **`sys_clk_p`** | **C8** | **`DIFF_SSTL15`** | **200 MHz** |
| **`sys_clk_n`** | **C7** | **`DIFF_SSTL15`** | 200 MHz |

**⇒ 与硬件手册第 5 页"PL 侧 200MHz"一致。**

### 2.2 复位与 LED —— **IOSTANDARD 是 1.5V，不是 1.8V/3.3V**

```tcl
set_property PACKAGE_PIN F8 [get_ports sys_rst]
set_property IOSTANDARD LVCMOS15 [get_ports sys_rst]

set_property PACKAGE_PIN E7 [get_ports rx_gtx_full_reset]
set_property IOSTANDARD LVCMOS15 [get_ports rx_gtx_full_reset]

set_property IOSTANDARD LVCMOS15 [get_ports {led[0]}]
set_property PACKAGE_PIN J1 [get_ports {led[0]}]      # LED1
set_property IOSTANDARD LVCMOS15 [get_ports {led[1]}]
set_property PACKAGE_PIN M6 [get_ports {led[1]}]      # LED2
```

**⚠️ BANK13 的 VCCO 是 1.5V（`LVCMOS15`）** —— 这一点此前 `pin_map.md` 未记录。

### 2.3 HDMI 输出（完整）

```tcl
set_property PACKAGE_PIN AC17 [get_ports HDMI_CLK_P]
set_property PACKAGE_PIN AA15 [get_ports {HDMI_TX_P[0]}]
set_property PACKAGE_PIN Y16  [get_ports {HDMI_TX_P[1]}]
set_property PACKAGE_PIN W16  [get_ports {HDMI_TX_P[2]}]
set_property IOSTANDARD TMDS_33 [get_ports HDMI_CLK_P]
set_property IOSTANDARD TMDS_33 [get_ports {HDMI_TX_P[*]}]
```

### 2.4 SDI / FMC（Lite 版）

```tcl
set_property PACKAGE_PIN AB3 [get_ports FMC_HPC_DP0_M2C_N]
set_property PACKAGE_PIN AB4 [get_ports FMC_HPC_DP0_M2C_P]
create_clock -period 6.734 [get_ports FMC_HPC_GBTCLK0_M2C_C_P]   # 6.734 ns ≈ 148.5 MHz（1080p60）

## WUJING BOARD（完整版）
##set_property PACKAGE_PIN U6 [get_ports FMC_HPC_GBTCLK0_M2C_C_P]
##set_property PACKAGE_PIN U5 [get_ports FMC_HPC_GBTCLK0_M2C_C_N]

## WUJING LITE BOARD（我们的板子）
set_property PACKAGE_PIN R6 [get_ports FMC_HPC_GBTCLK0_M2C_C_P]
set_property PACKAGE_PIN R5 [get_ports FMC_HPC_GBTCLK0_M2C_C_N]
```

**⇒ Lite 版与完整版的唯一约束差异就是这一处（R6/R5 vs U6/U5）。**

### 2.5 PJTAG（EMIO JTAG）—— 与硬件手册 4.7 节一致

```tcl
set_property PACKAGE_PIN AD16 [get_ports PJTAG_TDO]
set_property PACKAGE_PIN AB14 [get_ports PJTAG_TMS]
set_property PACKAGE_PIN AB15 [get_ports PJTAG_TCK]
set_property PACKAGE_PIN AD15 [get_ports PJTAG_TDI]
set_property IOSTANDARD LVCMOS33 [get_ports PJTAG_TCK]
set_property IOSTANDARD LVCMOS33 [get_ports PJTAG_TMS]
set_property IOSTANDARD LVCMOS33 [get_ports PJTAG_TDI]
set_property IOSTANDARD LVCMOS33 [get_ports PJTAG_TDO]
set_property PULLUP true [get_ports PJTAG_TDO]
create_clock -period 20.000 -name jtag_clk -waveform {0.000 10.000} [get_ports PJTAG_TCK]
```

### 2.6 `ai7030.xdc` 里的关键约束（时序/DRC）

```tcl
# 将 4 个 DRC 检查降级为 Warning（AI_Mate 网表本身不满足，属正常）
set_property SEVERITY {Warning} [get_drc_checks {REQP-44}]
set_property SEVERITY {Warning} [get_drc_checks {REQP-46}]
set_property SEVERITY {Warning} [get_drc_checks {REQP-52}]
set_property SEVERITY {Warning} [get_drc_checks {REQP-56}]

# AI Core 的 PLL 必须锁到 PLLE2_ADV_X1Y3
set_property LOC PLLE2_ADV_X1Y3 [get_cells U0_ps_ai_peripheral/ZGolo/u_AI_Mate_top/clkrst_wrapper_u0/AI_CORE_CLK/inst/plle2_adv_inst]

# SDI GTX 恢复时钟 148.5 MHz
create_clock -period 6.734 [get_pins rx_sdi_inst/SDI0/SDI/GTX_i/gtxe2_i/RXOUTCLK]
```

---

## 三、⭐ FPGA 工程结构（`fpai_demo_fpga.rar` 解压后）

```
fpai_demo_fpga/
├── constrs_1/
│   ├── ai7030.xdc                      2.9 KB   时序/DRC 约束
│   └── impl_constraints.xdc            2.5 KB   管脚约束（见上）
├── PS_AI IP/                           44 文件 / 4.9 MB   PS IP（processing_system7_v5_5）
├── fpai_demo_vivado.srcs/              35 文件 / 12.2 MB  Block Design
├── fpai_demo_vivado.ip_user_files/     14 文件 / 7.1 MB   IP 静态文件
└── rtl/                               166 文件 / 135.7 MB
    ├── ai7030_edif_top.v               11.7 KB  顶层模块
    ├── AI_Mate_stub.v                  22.8 KB  AI_Mate 的 wrapper（★ 看接口用）
    ├── ps_ai_peripheral.sv             89.6 KB
    ├── ps_ai_wrapper.sv                55.9 KB
    ├── edif/
    │   ├── AI_Mate.edif                69.6 MB  ★★★ NPU 网表（含 DetPost 硬算子）
    │   └── AI_Mate_no_detpost.edif     46.2 MB  NPU 网表（不含 DetPost，省 PL 资源）
    ├── adder_op/                                ★★★ custom op 完整示例（P 照这个改）
    │   ├── adder.v                      2.0 KB  运算逻辑
    │   ├── adder_top.v                  7.5 KB  顶层（寄存器口 + DMA 口）
    │   ├── dma.v                        3.1 KB  PL DDR 读写
    │   ├── reg_ctrl.v                   9.5 KB  寄存器控制
    │   ├── pulse_cross.v                1.8 KB  跨时钟域
    │   └── AVR/avr_brs.v / avr_frs.v / avr_rs.v
    ├── display/                                 HDMI 输出全套
    │   ├── TMDSEncoder.vhd              6.8 KB  TMDS 编码
    │   ├── vtc.v                        2.4 KB  ★ 视频时序控制器（无 SDI 时用它出测试图）
    │   ├── color_bar.v                 10.5 KB  彩条发生器
    │   ├── frame_ctrl.v                42.3 KB
    │   ├── uihdmitx.v                   3.8 KB
    │   └── ...
    ├── sdi/                                     SDI 输入全套
    │   ├── rx_sdi.v                    12.6 KB
    │   ├── x7gtx_sdi_wrapper.v         27.3 KB
    │   ├── YCbCr422_2_RGB888.v          4.2 KB
    │   └── ...
    ├── gp/                                      GP 口管理
    │   ├── gp0_manager.sv / gp_io.sv / mna_gp2axi.sv / monitor_gp.v ...
    └── utils/
        ├── mna_itf.sv                  12.9 KB
        ├── axi_to_mna.v                 7.9 KB
        ├── demo_clkrst_wrapper.v        2.1 KB
        └── async_to_sync_reset.v        0.8 KB
```

**⚠️ `rtl/edif/AI_Mate.edif` 69.6 MB —— 这就是 ZG330 NPU 的加密网表。PL 里例化它就有 NPU 了。**

---

## 四、⭐ 开发流程（`30TAI使用教程.pdf` 全文要点）

### 4.1 安装 Vivado IP 补丁（`JFM_Kits.zip`）

```text
1.1 解压 JFM_Kits.zip 到一个英文路径（不要有中文、空格、特殊字符）
1.2 关闭 Vivado，新建用户环境变量：
      变量名：JFM_PATH
      变量值：工具包解压位置（IP_PATCH 文件夹的上一级，如 E:\JFM_Kits）
    验证：重启 Vivado，在 Tcl Console 执行 puts $::env(JFM_PATH)
1.3 关闭 IP cache：
      Project Settings → IP → IP Cache → Cache scope = Disabled
1.4 综合所有 IP：
      每个 IP 生成时把综合选项设为 Out of context per IP（而非 Global），点 Generate 而非 Skip
      Design Runs 里每个 IP 应显示 Synth_design Complete!
1.5 加载工具包（Tcl Console，注意用正斜杠）：
      source E:/JFM_Kits/ip_patch/run.tcl
1.6 加载脚本：
      add_hook_tcl_to_prj
1.7 加载 30TAI 时序库（首次使用必做）：
      replace_7z030ai_file
    注：切到非 30TAI 器件时，需 reset_database_to_default 恢复
```

**关键文件：`JFM_Kits\ip_patch\030ai\zynq.rtd`（21.3 MB，30TAI 时序库）**

### 4.2 新建 Vivado 工程

```text
（1）Vivado 版本：2018.03
（2）器件：xc7z030ffg676-2
（3）关闭 IP cache（见 1.3）
（4）Add Sources → Design Sources：加入 fpai_demo_fpga\rtl 下所有文件
（5）Add Sources → Constraints：加入 fpai_demo_fpga\constrs_1 下所有文件
（6）导入 fpai_demo_vivado.srcs\sources_1\bd 中的 Block Design
（7）Project Settings → IP → Repository：添加 fpai_demo_fpga\PS_AI IP 所在路径
（8）Tcl Console：source $::env(JFM_PATH)/ip_patch/run.tcl
（9）Tcl Console：add_hook_tcl_to_prj
```

### 4.3 ⚠️ 生成位流（重要提示）

```text
点击 Flow Navigator → PROGRAM AND DEBUG → Generate Bitstream

⚠️ 按流程依次点 Run Synthesis → Run Implementation → Generate Bitstream 可能存在问题，
   建议【跳过前两个步骤，直接点 Generate Bitstream】。
```

### 4.4 生成 BOOT.bin（`BOOT_Gen.rar`）

```text
3.1 解压 BOOT_Gen.zip，用文本编辑器打开 BOOT_Gen/7030ai_psin.bif
    修改其中路径为解压目录（路径不要出现反斜杠，确保能找到各文件）
3.2 把 Vivado 生成的 .bit 拷到解压目录，文件名必须与 bif 中一致
    打开 Procise → Create Image → 生成 bin（输出在解压目录）
3.3 替换 BOOT.bin 两种方式：
    （1）读卡器：直接把 BOOT.bin 替换到 FAT 分区（⚠️ 不要格式化磁盘）
    （2）SSH：
         mount /dev/mmcblk0p1 /root/bits
         替换 /root/bits/BOOT.bin
         reboot
     ⚠️ 必须真正挂载到 /root/bits 再替换；直接拷进去位流不会生效
```

### 4.5 编译与运行 PS 程序

```text
4.1 交叉编译环境安装 Icraft_3.XX 及 CustomOp_3.XX
4.2 把整个 fpai_demo_app 文件夹（含 deps）拷到交叉编译环境
    ⚠️ 注意不要在 30TAI 板载系统上编译
    编译参考：fpai_demo_app/examples/1_single_input+ai/PLin+SingleNet+HDMI/README.md
4.3 adder_demo：拷到板上，确保可执行权限后执行（验证 custom op 通路）
4.4 sdicamera+yolov5+hdmi：需要以下文件/文件夹
    configs/ZG/sdicamera+yolov5+hdmi.yaml
    imodel/ZG/yolov5s_352x640_ZG.json  （文件名与 yaml 配置一致）
    imodel/ZG/yolov5s_352x640_ZG.raw
    names/coco.names
    sdicamera+yolov5+hdmi               （可执行程序）
```

### 4.6 ⭐⭐⭐ **无 SDI 相机的做法（我们正需要）**

```text
【无 SDI】
  修改 configs/ZG/sdicamera+yolov5+hdmi.yaml：
      pipeline → camera → vtc = true
  保存。
  在【断电状态】下将 HDMI 接入开发板，上电启动。
  确保 sdicamera+yolov5+hdmi 有执行权限，执行：
      ./sdicamera+yolov5+hdmi ./configs/ZG/sdicamera+yolov5+hdmi.yaml
  在 HDMI 显示器中查看【滚动的灰度图】。

【接入 SDI】
  同上，但把 vtc 改为 false，并接 SDI 摄像头。
```

**⇒ `vtc: true` = 内部视频时序发生器，无外部视频源也能产生画面。这解决了我们"没有 SDI 相机"和"HDMI 黑屏"两个问题。**

---

## 五、⭐ custom op 接口定义（`FPAI_DEMO说明.pdf`）

### 5.1 两路接口

参考设计向 PL 端 custom op 提供两路接口：

| 接口 | Master | 用途 |
|---|---|---|
| **寄存器访问端口** | **PS 为 master** | PS 读写 custom op 的寄存器 |
| **数据访问端口** | **PL 的 custom op 为 master** | custom op 读写 PL DDR |

### 5.2 寄存器访问端口

| 信号 | 位宽 | 方向 | 说明 |
|---|---|---|---|
| `User_Reg_awwaddr` | 32 | 输入 | 写地址 |
| `User_Reg_awwdata` | 32 | 输入 | 写值 |
| `User_Reg_awwvalid` | 1 | 输入 | 写有效 |
| `User_Reg_awwready` | 1 | 输出 | 写就绪 |
| `User_Reg_araddr` | 32 | 输入 | 读地址 |
| `User_Reg_arvalid` | 1 | 输入 | 读地址有效 |
| `User_Reg_arready` | 1 | 输出 | 读地址就绪 |
| `User_Reg_rdata` | 32 | 输出 | 读返回数据 |
| `User_Reg_rvalid` | 1 | 输出 | 读数据有效 |
| `User_Reg_rready` | 1 | 输入 | 读数据就绪 |

### 5.3 数据访问端口（**512 位宽**）

| 信号 | 位宽 | 方向 | 说明 |
|---|---|---|---|
| `User_Ddr_awwaddr` | 32 | 输出 | 写地址 |
| `User_Ddr_awwdata` | **512** | 输出 | 写值（64 字节/拍）|
| `User_Ddr_awwinfo` | 72 | 输出 | 写辅助信息（`[70:7]` = 64 字节的字节使能）|
| `User_Ddr_awwvalid` | 1 | 输出 | 写有效 |
| `User_Ddr_awwready` | 1 | 输入 | 写就绪 |
| `User_Ddr_araddr` | 32 | 输出 | 读地址 |
| `User_Ddr_arvalid` | 1 | 输出 | 读地址有效 |
| `User_Ddr_arinfo` | 32 | 输出 | 读辅助信息 |
| `User_Ddr_arready` | 1 | 输入 | 读地址就绪 |
| `User_Ddr_rdata` | **512** | 输入 | 读返回数据 |
| `User_Ddr_rvalid` | 1 | 输入 | 读数据有效 |
| `User_Ddr_rinfo` | 32 | 输入 | 读返回辅助信息 |
| `User_Ddr_rready` | 1 | 输出 | 读数据就绪 |

**握手机制**：标准 ready/valid —— master 发 data + valid，slave 发 ready，两者同时有效完成一次传输。

### 5.4 ⭐ custom op 寄存器地址空间

> **custom op 的寄存器地址空间为 `0x400C'0000 ~ 0x400F'FFFF`**

**⚠️ 此前 AXI 探测只扫了 `0x40000000 ~ 0x4000FFFF`，完全没覆盖这个区间 —— 必须重扫。**

### 5.5 custom op 使用流程（以 adder 为例）

```text
（1）PS 通过寄存器访问端口配置：读数据首地址、写数据首地址、访问数据量、启动寄存器
（2）custom op 启动后从 PL DDR 读输入 → 计算 → 写回 PL DDR → 产生结束标志
（3）PS 通过寄存器端口轮询结束标志，直至完成
```

### 5.6 ⭐ PS 侧 C API

```c
// 读寄存器（custom op 寄存器空间 0x400C0000 ~ 0x400FFFFF）
int value = device.defaultRegRegion().read(uint32_t address, bool relative = false);

// 写寄存器
device.defaultRegRegion().write(uint32_t address, uint32_t value, bool relative = false);

// 分配 PL DDR 空间（alignment 默认 64 字节）
auto mem_chunk = device.defaultMemRegion().malloc(uint64_t byte_size,
                                                 bool auto_free = false,
                                                 uint64_t alignment = 64);

// 写 PL DDR
mem_chunk.write(uint64_t dest_offset, char* src, uint64_t byte_size);

// 读 PL DDR
mem_chunk.read(char* dest, uint64_t src_offset, uint64_t byte_size);
```

### 5.7 示例程序位置

```
examples/1_single_input+ai/PLin+SingleNet+HDMI/src/
  ├── adder_demo.cpp              加法器 demo 源码（custom op 最小验证）
  └── sdicamera+yolov5+hdmi.cpp   参考设计源码
```

---

## 六、⭐ 参考设计的数据流（官方原文）

```text
（1）SDI 摄像头输入视频流（1080p@60Hz）。PL 端 rx_sdi 模块解析为 RGB888 并复制成两路：
     一路经预处理后存入 PL DDR，供 AI 使用；
     另一路经预处理后存入 PS DDR，供 HDMI 显示使用。
（2）PS 启动 AI，AI 完成神经网络运算后，将输出结果写回 PL DDR。
（3）PS 从 PL DDR 取回输出结果，完成后处理计算，将输出写回 PS DDR。
（4）从 PS DDR 读取缓存视频数据，通过 HDMI 输出到显示器。
```

**⇒ 注意：AI 的输入/输出都在 PL DDR，不在 PS DDR。这是性能关键（PL 直接访问 DDR，不经过 PS）。**

---

## 七、与当前项目的对照

### 7.1 此前"待向企业索取"的材料，现在都有了吗

| # | 材料 | 现状 |
|---|---|---|
| 1 | PLIN + HDMI/VPU 参考工程（含 runtimeapp）| ✅ **有**：`fpai_demo_app.rar`（193 MB）+ 大学计划网盘 `fpai_demo_package_2604070x.zip` |
| 2 | `Icraft_3.36.1_onchip.deb` | ✅ 已有（已装到板上）|
| 3 | `CustomOp_3.36.1_onchip.deb` | ✅ 已有（已装）|
| 4 | `IcraftMdz_ThirdParty.deb` | ✅ 已有 |
| 5 | **Vivado IP 补丁** | ✅ **有**：`JFM_Kits.zip`（1.18 GB），含 `ip_patch/run.tcl` + `030ai/zynq.rtd` |
| 6 | **Procise Bit 补丁** | ✅ 已集成在 Procise 的 Tools 菜单 |
| 7 | **悟净 Lite 的 PL 引脚 / xdc** | ✅ **有**：`impl_constraints.xdc`（时钟 C8/C7，复位 F8，HDMI AC17/AA15/Y16/W16，SDI R6/R5）|
| 8 | **含 ZG330 的位流** | ✅ **有**：`BIT.rar` 的 `30tai_lite_detpost/`（+ PL 工程可自行重新生成）|
| 9 | **FPGA 工程源码** | ✅ **有**：`fpai_demo_fpga.rar`（含 `AI_Mate.edif` 69.6 MB）|
| 10 | **Procise License** | ❌ **仍缺**（唯一）|

### 7.2 P 的卡点变化

| P 之前的卡点 | 现在 |
|---|---|
| PL 系统时钟引脚找不到 | ✅ **C8 / C7，200 MHz，`DIFF_SSTL15`** |
| xdc 全注释 | ✅ **可直接用官方 `impl_constraints.xdc` 改造** |
| Vivado IP 补丁要申请 | ✅ **`JFM_Kits.zip` 里全有** |
| 没有 PL 工程参考 | ✅ **完整 Vivado 工程 + custom op 示例（`adder_op/`）** |
| Procise License 未申请 | ❌ **仍需解决**（MAC `ae:59:f4:2d:3a:99`）|

### 7.3 对自研 IP 的影响

**P 的 IP1（灰度化+2×降采样）/ IP2（Top-Hat+CFAR）/ IP3（NMS）/ IP4（ROI 打包）有两条集成路线：**

| 路线 | 做法 | 优点 | 缺点 |
|---|---|---|---|
| **A. 独立 AXI 通路** | 自己在 PL 里做 AXI4-Stream/FULL 接口，PS 通过独立 reg + DMA 访问 | 自由，快 | **必须自己做 Vivado 工程 + block design，工作量大；且用不了 AI_Mate 的 DetPost** |
| **B. 接入官方框架（推荐）** | 照 `rtl/adder_op/adder_top.v` 的结构，把 IP 改成 `User_Reg_*` + `User_Ddr_*` 接口，插入官方工程 | **直接复用官方工程/约束/位流生成流程；可用 DetPost；PS 侧 C API 现成** | 接口固定（512 位数据口），需适配 |

**⇒ 强烈建议走 B 路线。`adder_op` 是最小的可抄模板（`adder.v` 2 KB + `adder_top.v` 7.5 KB + `dma.v` 3.1 KB + `reg_ctrl.v` 9.5 KB）。**

---

## 八、剩余待办

| # | 事项 | 谁 | 说明 |
|---|---|---|---|
| 1 | **解压 `JFM_Kits.zip` 到英文路径，装 IP 补丁** | P | 1.18 GB，解压后设置 `JFM_PATH` |
| 2 | **解压 `BIT.rar` 确认位流** | S/P | 特别是 `30tai_lite_detpost/` |
| 3 | **板子开机后重扫 AXI `0x400C0000`** | S | 之前扫错范围了 |
| 4 | **照 `adder_op` 把 IP1 改成 custom op 接口** | P | 先做最小验证 |
| 5 | **Procise License 申请** | P | MAC `ae:59:f4:2d:3a:99`，走 QQ 群 `790072144` |
| 6 | **试 `vtc: true` 模式（无 SDI 出 HDMI 画面）** | S | 需要先有编译好的 `sdicamera+yolov5+hdmi` 可执行程序 |

---

## 九、官方联系渠道

**赛题指南第 7 页原文：**

> **技术交流：关注大赛官方公众号及复旦微赛事官方交流 QQ 群：`790072144`（复旦微嵌入式 FPGA QQ 群）**

**⇒ 这是唯一官方对接渠道。此前一直在找邮箱，是走偏了。**
