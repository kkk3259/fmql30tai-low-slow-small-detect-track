# 悟净 Lite（FMQL30TAI676H）PL 引脚映射表

> **来源**：《悟净开发板 Lite（轻量版）硬件使用手册 V1.0》（深圳市创芯瑞天科技有限公司，32 页）
> **整理时间**：2026-10-04　**整理人**：S
> **用途**：为 Procise 约束文件（引脚分配）提供依据

---

## 先读这一段（重要）

手册原文明确写着：

> "复旦微悟净 Lite 开发板使用手册所有的参数说明来自于开发板原理图，如有疑问请查看原理图或者联系我司销售、技术支持。"

而原理图在第 32 页，以图片形式给出（PDF 文本提取不到）。
因此本表只收录手册正文文字中能确切读到的引脚，缺失项一律标注"待原理图确认"，不做推测。

**关键缺失**：**PL 系统时钟引脚**（没有它无法综合）→ 见第四节。

---

## 一、已确认的引脚（手册正文明确给出）

### 1.1 PL 按键（2 路）—— 可信度高（有引脚名 + BGA 位号）

| 信号名 | 芯片引脚名 | BGA 位号 | 备注 |
|---|---|---|---|
| `PL_KEY1` | `IO_L11P_T1_SRCC_34` | **F8** | 按键 1 |
| `PL_KEY2` | `IO_L11N_T1_SRCC_34` | **E7** | 按键 2 |

> 手册 4.12 原文："在功能底板上有 4 个按键，1 路复位按键，1 路 MIO 按键，2 路 PL 按键。"

### 1.2 MIPI CSI 摄像头接口 J16（PL 端 BANK12，IO 电平 1.8V）—— 可信度高

| 信号名 | 芯片引脚名 | BGA 位号 | 备注 |
|---|---|---|---|
| `MIPI_LANE0_P` | `IO_L1P_T0_12` | **Y12** | 数据 Lane0 正 |
| `MIPI_LANE0_N` | `IO_L1N_T0_12` | **Y11** | 数据 Lane0 负 |
| `MIPI_LANE1_P` | `IO_L2P_T0_12` | **Y10** | 数据 Lane1 正 |
| `MIPI_LANE1_N` | `IO_L2N_T0_12` | **AA10** | 数据 Lane1 负 |
| `MIPI_CLK_P` | `IO_L12P_T1_MRCC_12` | **AC13** | 时钟正 |
| `MIPI_CLK_N` | `IO_L12N_T1_MRCC_12` | **AD13** | 时钟负 |
| `CAM_GPIO` | `IO_L17N_T2_12` | **AE15** | CAM GPIO |
| `CAM_SCL` | `IO_L18P_T2_12` | **AE17** | I2C 时钟（上拉 3.3V）|
| `CAM_SDA` | `IO_L18N_T2_12` | **AF17** | I2C 数据（上拉 3.3V）|
| `CAM_CLK` | `IO_L19P_T3_12` | **Y17** | CAM CLK |

> 手册 4.19 提示：电路为 LP 模式（100Ω）/ HS 模式（150Ω） 分别预留匹配电阻网络，需按摄像头模组工作模式选择焊接。
> 本项目已决定不使用 MIPI 摄像头（见 `docs/03`），此表仅供备查。

### 1.3 PL LED（4 路）—— 可信度中等

| 信号名 | BGA 位号 | 备注 |
|---|---|---|
| `PL_LED1` | **J1** | 手册 4.11 |
| `PL_LED2` | **M6** | |
| `PL_LED3` | **H7** | |
| `PL_LED4` | **J8** | |

> 与 1.1/1.2 的格式不同：按键与 MIPI 都给了「芯片引脚名（`IO_L..`）+ BGA 位号」，而 LED 只给了 `J1/M6/H7/J8`。
> 这些值格式上是合法的 BGA 位号（FFG676 封装为「字母+数字」），但缺少引脚名无法交叉核对 ⇒ 使用前请对照原理图确认。

---

## 二、PS 侧外设引脚（不需要写进 FPGA 约束，仅供理解架构）

PS 的外设由 PS（ARM）配置，不出现在 PL 的引脚约束里。列出是为便于排查：

| 外设 | 信号 | PS 引脚 | BGA 位号 | 备注 |
|---|---|---|---|---|
| **千兆以太网** | `PHY_TX_CLK` | PS_MIO16_501 | G21 | RGMII 发送时钟（裕太微 YT8521）|
| | `PHY_TXD0~3` | PS_MIO17~20 | G17/G20/G19/H19 | RGMII 发送数据 |
| | `PHY_TX_CTRL` | PS_MIO21_501 | F22 | 发送使能 |
| | `PHY_RX_CLK` | PS_MIO22_501 | G22 | RGMII 接收时钟 |
| | `PHY_RXD0~3` | PS_MIO23~26 | F20/J19/F19/H17 | RGMII 接收数据 |
| | `PHY_RX_CTRL` | PS_MIO27_501 | F18 | 接收有效 |
| | `PHY_MDC` / `PHY_MDIO` | PS_MIO52/53_501 | A20/A19 | MDIO 管理 |
| **SD/TF 卡** | `SD_CLK` | PS_MIO40 | C22 | |
| | `SD_CMD` | PS_MIO41 | C19 | |
| | `SD_D0~D3` | PS_MIO42~45 | F17/D18/E18/C18 | |
| | `SD_CD` | PS_MIO46 | E17 | 卡插入检测 |
| **USB 串口** | `USB_UART_PS_RX` | PS_MIO50_501 | B22 | CP2103GM，**MINI USB 接口** |
| | `USB_UART_PS_TX` | PS_MIO51_500 | B20 | |
| **USB2.0 OTG** | `OTG_DATA0~7` | PS_MIO28~39 | — | USB3320C + USB2514 扩展 4 路 HOST |
| | `OTG_CLK` | PS_MIO36_501 | — | |
| | `OTG_RESETN` | PS_MIO8_500 | — | |
| **PS LED / KEY** | `PS_MIO7` | PS_MIO7 | E23 | |
| | `PS_KEY` | PS_MIO47_501 | B19 | |

---

## 三、JTAG 引脚（不用于 PL 约束，但上板要用）

| 信号名 | 芯片引脚名 | BGA 位号 |
|---|---|---|
| `Z7_PS_TDO` | `IO_L15P_T2_DQS_12` | AD16 |
| `Z7_PS_TCK` | `IO_L14P_T2_SRCC_12` | AB15 |
| `Z7_PS_TMS` | `IO_L14N_T2_SRCC_12` | AB14 |
| `Z7_PS_TDI` | `IO_L15N_T2_DQS_12` | AD15 |

> 手册 4.7：开发板有 **2 个 JTAG**（U18 = PS 端 EMIO_JTAG，U19 = PL 端 JTAG），均为 20pin，可用 J-Link 或 I-Jet。
> **独立模式下需转接板** —— 接手二手板卡时请确认转接板是否齐全。

---

## 四、原缺失项的现状（2026-10-23 更新）

| # | 原缺失项 | 现状 |
|---|---|---|
| **1** | **PL 系统时钟引脚** | **已解决**：`C8`（P）/ `C7`（N），**200 MHz 差分**，`IOSTANDARD DIFF_SSTL15`，`create_clock -period 5.000`。来源 = 官方示例工程 `fpai_demo_fpga/constrs_1/impl_constraints.xdc`（微云 `20260916` 包 → `fpai_demo_fpga.rar`） |
| **2** | **全局复位引脚** | 已解决：`F8`（`sys_rst` = 手册 `PL_KEY1 = IO_L11P_T1_SRCC_34`，LVCMOS15）；工程里另用**内部上电复位**，不强依赖该键 |
| **3** | HEADER 14×2 的 16 路 GPIO | 仍无（本项目未用，不影响交付） |
| **4** | XADC 通道引脚号 | 仍无（本项目未用） |
| **5** | **U19（PL_JTAG）20 针针序** | 已解决：见 `jtag_wiring.md`（1=VTref/3.3V、5=TDI、7=TMS、9=TCK、13=TDO、15=RESET，偶数脚与 3/11/17/19 多为 GND/NC） |

---

## 五、解决路径回顾（已结案）

| 途径 | 结果 |
|---|---|
| **官方示例工程** | **最终来源**：`fpai_demo_fpga.rar` 里的 `constrs_1/impl_constraints.xdc`（含时钟 C8/C7、复位 F8、LED J1/M6、HDMI、PJTAG） |
| **手册原理图** | 从 Lite 手册 PDF 第 16 页导出内嵌图片，读出了 **U18/U19 的插座针序**（存档见 `jtag_wiring.md`） |
| 向学长要约束文件 / 问厂家 | 最终未使用（前两条已够） |

> 不要凭"标准接口"猜针序 —— 这块板的 U19 **不是** ARM 标准 20 针（ARM 的 TMS 在 2 脚，本板在 7 脚），接线前务必按 `jtag_wiring.md` 对针脚编号。

---

## 六、 附加提醒（来自手册，上板必看）

| # | 提醒 | 出处 |
|---|---|---|
| 1 | **PS 时钟必须 50MHz**，不能用 33.333MHz | 4.5 |
| 2 | **HDMI 固定 720P60**；1080P@60 部分显示器闪屏（TMDS 748.5M 超出 HR bank IO 的 710M 上限）| 4.16 |
| 3 | **串口是 MINI USB**，不是 Type-C/Micro | 4.10 |
| 4 | **启动模式由跳线帽决定**（MIO2 级联/独立、MIO3~5 启动源、MIO6 PLL Bypass、MIO7/8 Bank 电压）| 4.2 |
| 5 | **不要擅自改动/焊接元器件**，否则厂家不予赔付 | 用户须知 |
| 6 | PL 侧有**独立 2GB DDR3**（1600MHz×64bit = 12.8 GB/s）| 4.4 |
| 7 | PL 侧资源：约 **125K LC / 400 DSP / 9.3Mb BRAM**；**对标 Xilinx XC7Z030FFG676-2I** | 4.1 |
