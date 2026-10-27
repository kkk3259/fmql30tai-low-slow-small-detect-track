# 19 - 把自研 IP2 加速器接进 PS（AXI 通路）

> 更新时间：2026-10-26
> 前置：`pl/rtl/ip2_axi_*`（数据通路）、`docs/14-PS-PL接口约定.md` v0.2（软件契约，S 已确认）
> 目标：让 A53 上的 Linux 能通过 `/dev/mem` 直接控制 IP2 加速器、拿回候选表

---

## 1. 为什么必须进 Vivado

Procise 不支持 Block Design（没有 Zynq PS 封装、没有 AXI Interconnect/协议转换），
所以"PL 加速器 + PS 主控"的完整系统只能在 Vivado 里搭。分工是：

| 工具 | 用途 | 我们的现状 |
|---|---|---|
| **Procise** | 纯 PL 设计（无 PS）从 RTL 到 bitstream | 50 MHz 版时序收敛，已出位流、已上板 |
| **Vivado** | PS7 + PL 的 Block Design、导出 .hdf 给 SDK | **本次要做** |

RTL 是同一套（`pl/rtl/`），Procise 和 Vivado 都能综合，不需要写两份。

---

## 2. 拓扑

```
        ┌──────────────────────────────┐
        │  processing_system7_0 (PS7)  │
        │  A53 ×4 / DDR3 / QSPI / SD   │
        └───┬───────────────────┬──────┘
            │ M_AXI_GP0 (32bit) │ S_AXI_HP0 (64bit)
            ▼                   ▲
     ┌─────────────┐      ┌─────┴───────┐
     │ AXI Inter-  │      │ AXI Inter-  │
     │ connect     │      │ connect     │
     └──┬──────────┘      └─────┬───────┘
        │ S_AXI (Lite 32b)      │ M_AXI (64b)
        ▼                       ▲
     ┌──────────────────────────┴───────┐
     │  ip2_axi_bd_wrap → ip2_axi_top   │
     │  ┌──────────────┐                │
     │  │ master_rd    │ 读 230,400 B 帧 │
     │  │ pix_fifo     │ 262144 深帧缓存 │
     │  │ ip2_top_stream│ TopHat→CFAR→CCL│
     │  │ master_wr    │ 写 36 B 候选表  │
     │  └──────────────┘                │
     └──────────────────────────────────┘
        时钟：PS FCLK_CLK0 = 50 MHz（同一个时钟域，无跨域 FIFO）
```

---

## 3. 关键设计决定（踩过的坑，别改）

1. **PS 晶振参数沿用官方出厂配置 `33.333333`**，不要"按手册改成 50"。
   依据：官方 30TAI 工程 `ps7_parameters.xml:28` 就是 33.333333，而它烧进板子
   UART/DDR/QSPI 全部正常工作。该参数错了会导致 UART 波特率、DDR 频率全偏。
   我们唯一显式改的是 **FCLK_CLK0 = 50 MHz**（与 50 MHz 位流同频）。
2. **像素流必须连续**：IP2 里 Top-Hat 的行缓存和 CFAR 的 31×31 窗口都假设
   "每个有效拍就换一个像素"。AXI 读回来是突发间隙的，所以必须经
   `ip2_pix_fifo.v`（整帧 262,144 深 ≈ 2 Mbit LUTRAM）再喂链，不能用
   `pe=o_ready` 之类"跳过空拍"的做法（试过，几何关系全乱，候选表全 0）。
3. **寄存器基址固定 `0x83C00000`**，与 `ps/pl_link.py` 里的常量一致；
   不要用自动分配的地址（`assign_bd_address` 后要显式改 offset）。
4. **帧缓冲/结果区物理地址**：帧 `0x30100000`（16 MiB，可放 72 帧）、结果 `0x31000000`。
   注意避开 `0x40000000`（S 明确说被占用）与 `0x80000000`（AI_Mate DMA 用）。

---

## 4. 一键脚本

```powershell
cd D:\firstharness\synth\vivado
& "D:\Xilinx\Vivado\2018.2\bin\vivado.bat" -mode batch -source build_bd.tcl -nojournal
```

脚本 `build_bd.tcl` 做 15 步（每步都有 `[build_bd] ===== N. xxx =====` 打印）：

| 步 | 动作 |
|---|---|
| 1-3 | 建工程（`xc7z030ffg676-2`）、加 10 个 RTL、建 BD |
| 4 | 放 PS7 并套官方出厂配置（`ps7_config.tcl`，619 个参数） |
| 5 | 引出 DDR / FIXED_IO |
| 6-7 | 放 `ip2_axi_bd_wrap`，`apply_bd_automation` 自动接 GP0→S_AXI、M_AXI→HP0 |
| 8-9 | 时钟/复位兜底 + LED 引出 |
| 10 | 地址分配，寄存器段强制 `0x83C00000 / 4K` |
| 11-12 | `validate_bd_design` + 生成 wrapper |
| 13 | 引脚约束（LED=J1，LVCMOS15） |
| 14 | `launch_runs impl_1 -to_step write_bitstream`（约 20~40 分钟） |
| 15 | 导出 `.hwdef` + 资源/时序报告 |

产出：
- 位流 `synth/vivado/ip2_ps/ip2_ps.runs/impl_1/ip2_bd_wrapper.bit`
- 硬件描述 `synth/vivado/ip2_bd.hwdef`（给 SDK 打 BOOT.bin）
- 报告 `synth/vivado/utilization.rpt`、`timing.rpt`

`ps7_config.tcl` 由 `pl/tools/gen_ps7_tcl.py` 从官方 XML 生成，要改参数就改脚本重跑。

---

## 5. 上板（带 PS，不能用 JTAG 直接烧）

带 PS 的设计，**位流必须由 FSBL 从 BOOT.bin 加载**（JTAG 只烧 .bit 的话 PS 不会起来）：

1. Vivado 里 `File → Export → Export Hardware`（勾 Include bitstream）→ 得到 `.hdf`
2. Xilinx SDK：`File → New → Application Project`，选我们的 hdf，建 `fsbl`
3. 再建一个 hello 工程，把 `ps/pl_link.py` 的测试逻辑改成 C（或直接用 Linux 下的 Python，见第 6 节）
4. `Xilinx → Create Boot Image`：`fsbl.elf` + `ip2_bd_wrapper.bit` + `u-boot.elf`
   （顺序必须是 FSBL → bit → u-boot，中间不能颠倒）
5. 把生成的 `BOOT.bin` 覆盖 SD 卡 FAT 分区里的同名文件，插回板子重启

> 如果 S 那边已经有能跑的 BOOT.bin，只需要把我们的 `.bit` 换进去重新打包即可，
> 不必重建 Linux 镜像。

---

## 6. 验收（板上跑）

板子启动 Linux 后，用 `ps/pl_link.py`（S 写的）或下面这段手测：

```python
import mmap, struct, os
BASE = 0x83C00000
fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
m = mmap.mmap(fd, 0x1000, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=BASE)
def rd(o): return struct.unpack("<I", m[o:o+4])[0]
def wr(o, v): m[o:o+4] = struct.pack("<I", v)

print("VERSION = 0x%08X (应为 0x00010000)" % rd(0x14))
wr(0x04, 0x30100000)          # 帧地址
wr(0x08, 0x31000000)          # 结果地址
wr(0x10, 1)                   # 帧号
wr(0x00, 1)                   # start
import time
while True:
    st = rd(0x0C)
    if st & 0x2: break        # done
    if st & 0x4: raise SystemExit("ERROR")
    time.sleep(0.001)
print("STATUS = 0x%08X" % st, "n_cand =", (st >> 8) & 0xFF)
res = m[0x40:0x40+36]          # 不对：结果在 DDR 结果区，见下一行
```

真正取 36 字节候选表要读 **结果区物理地址**（`0x31000000`），用同样的 mmap 手法即可；
`STATUS[15:8]` 就是 `n_cand`，`+0x40` 是状态字、`+0x44` 是邮箱（见 docs/14 §2）。

---

## 7. 已知风险

| 风险 | 影响 | 处置 |
|---|---|---|
| `apply_bd_automation` 认不出接口 | BD 连接失败 | 见 §8 手工连法 |
| Vivado 推断 RAM 失败 | LUT 爆掉/时序崩 | 2026-10-26 已把 3 个模块的 RAM 写改成**同步复位**块（Vivado 不接受带异步复位的 RAM 写），仿真回归仍 0 差异 |
| PS7 参数与板子不符 | UART/DDR 异常 | 沿用官方 `33.333333` + MIO 全表，不改 |
| FCLK 50 MHz 下 PL 时序 | 已在 Procise 验证 +0.041 ns | Vivado 实现后看 `timing.rpt`，若负 slack 再降到 25 MHz |

## 8. 手工连法（automation 失败时）

```tcl
# 在 BD 里删掉 automation 生成的东西后，手工加：
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 axi_gp
set_property -dict [list CONFIG.NUM_MI {1} CONFIG.NUM_SI {1}] [get_bd_cells axi_gp]
connect_bd_intf_net [get_bd_intf_pins processing_system7_0/M_AXI_GP0] [get_bd_intf_pins axi_gp/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins axi_gp/M00_AXI] [get_bd_intf_pins ip2_0/S_AXI]
connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] [get_bd_pins axi_gp/ACLK] \
               [get_bd_pins axi_gp/S00_ACLK] [get_bd_pins axi_gp/M00_ACLK]
# M_AXI → HP0 同理，另建一个 interconnect（HP0 是 64 bit、需要 data width conversion）
```

更简单：把 interconnect 留给 `apply_bd_automation`，只把 `ip2_axi_bd_wrap.v` 里
`S_AXI`/`M_AXI` 的 `X_INTERFACE_INFO` 属性核对一遍（缺属性 → BD 看不到接口）。
