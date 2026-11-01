# handoff/ —— 交给 PS 侧（S）的硬件交付物

本目录存放 PL 侧产出的、PS 侧打 BOOT.bin 需要的二进制。这些是构建产物，不进源码流程，但为了不让 S 反复找文件，直接放进仓库。

## 当前文件

| 文件 | 大小 | 来自 | 用途 |
|---|---|---|---|
| `ip2_bd_wrapper.hdf` | 1,390,354 B | `synth/vivado/ip2_ps/ip2_ps.sdk/ip2_bd_wrapper.hdf`（2026-10-26 21:20） | **硬件平台包**，S 用它打 BOOT.bin |

`ip2_bd_wrapper.hdf` 里面（解压即得，本身就是 zip）：

| 条目 | 大小 | 说明 |
|---|---|---|
| `ip2_bd_wrapper.bit` | 5,980,026 B | **FPGA 位流**（我们 640×360 检测 IP + PS 互联） |
| `sysdef.xml` | 883 B | 给 SDK 的顶层描述 |
| `ip2_bd.hwh` | 202,696 B | 硬件描述（含寄存器段地址、PS 配置参数） |
| `ip2_bd_bd.tcl` | 37,951 B | Block Design 重建脚本 |
| `ps7_init.c/.h` / `ps7_init_gpl.c/.h` | 565 KB / 565 KB | **PS 初始化代码**（DDR、MIO、FCLK、GP1/HP0 都在里面），FSBL 里调的就是它 |
| `ps7_init.html` / `ps7_init.tcl` | 3.0 MB / 37 KB | 同上，参考用 |

## 关键参数（S 打 BOOT.bin 和写驱动时要对上的）

| 项目 | 值 |
|---|---|
| 器件 | `xc7z030ffg676-2`（Vivado 2018.2 建，物理器件 JFMQL30TAI676H；标签生成时 Vivado 会提示 device mismatch，**忽略即可**）|
| PL 寄存器基址 | **`0x83C00000`**（64 KB 段，挂 `M_AXI_GP1`）|
| AXI 时钟 | `FCLK_CLK0 = 50 MHz`（GP1 与 HP0 同频 50 MHz）|
| 用到的 PS 口 | `M_AXI_GP1`（PS 主 → PL 从，读写寄存器）、`S_AXI_HP0`（PL 主 → PS DDR，读帧/写候选表）|
| 关闭的口 | `M_AXI_GP0`、`S_AXI_HP1~3`、ACP |
| DDR | 沿用出厂配置 `MT41K256M16 RE-125`、533 MHz |

> ⚠️ 基址为什么是 `0x83C00000` 而不是文档早期写的 `0xA0000000`：
> `build_bd.tcl` 第 10 步原来用 `get_bd_addr_segs -of_objects [get_bd_cells ip2_0]` 找寄存器段，但 slave cell 本身不拥有地址段（段挂在 PS 的地址空间里），遍历是空集，`set_property offset` 静默不生效，最后被 `assign_bd_address` 自动分到 `0x83C00000`。
> 现在脚本已改为从 `/processing_system7_0/Data` 地址空间里按名字匹配，并显式钉死 `0x83C00000`，与这份 HDF 一致。`ps/pl_link.py`、`ps/pl_selftest.py`、`docs/14`、`docs/20` 都已同步成 `0x83C00000`。

## 重打 BOOT.bin 需要的顺序（S 参考）

```
FSBL（用本 HDF 重新生成！旧的 FSBL 不认识我们的 PS 配置）
  → ip2_bd_wrapper.bit   ← 来自本 HDF
  → bl31.elf
  → u-boot.elf
```

旧的 BOOT.bin 里的 FSBL 一定不能复用：它跑的是出厂 `ps7_init`，里面只有 GP0 + HP0~3，没有我们的 GP1，所以 PS 访问 `0x83C00000` 必然 Bus error。

## 怎么重新生成这份 HDF（P 自己看）

```tcl
# Vivado 2018.2，Tcl Console 里：
cd D:/firstharness/synth/vivado
source build_bd.tcl
# 跑完后：launch_runs impl_1 -to_step write_bitstream -jobs 4 ; wait_on_run impl_1
# 再：File → Export → Export Hardware（勾 Include bitstream）
```

⚠️ 不要再点 "Run Implementation"：它会清空 `impl_1` 输出、把已生成的 `.bit` 删掉，然后 Export Hardware 就报 "位流不存在"。
只需要 `launch_runs impl_1 -to_step write_bitstream`（3~5 min，不重跑布局布线）。

如果 Export Hardware 报 `The hardware handoff file (.sysdef) does not exist`，手动补：

```tcl
write_sysdef -hwdef  ip2_ps/ip2_ps.runs/impl_1/ip2_bd_wrapper.hwdef \
             -bitfile ip2_ps/ip2_ps.runs/impl_1/ip2_bd_wrapper.bit \
             -file    ip2_ps/ip2_ps.srcs/sources_1/bd/ip2_bd/hw_handoff/ip2_bd.sysdef -force
```

然后再 Export Hardware 即可。

## 资源与时序（答辩可以直接引用）

| 指标 | 数值 |
|---|---|
| Slice LUTs | 30,139 / 78,600 = **38.34%**（其中 LUT as Memory 8,253 = 31.03%）|
| Slice Registers | 11,459 = 7.29% |
| Block RAM Tile | 64 / 265 = **24.15%**（帧缓冲 fifo 进了块 RAM）|
| DSP | 4 |
| WNS / TNS | **+1.356 ns** / 0，失败端点 **0** —— 100 MHz 都满足 |
